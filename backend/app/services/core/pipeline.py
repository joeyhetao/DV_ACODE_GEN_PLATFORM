from __future__ import annotations
import re
import json
import time
from dataclasses import dataclass, field
from urllib.parse import quote
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.services.core.cache import (
    get_generation_cache,
    set_generation_cache,
    get_intent_cache,
    set_intent_cache,
)
from app.services.core.expr_validator import EXPR_TYPE_DISPATCH
from app.services.core.identifier import (
    IDENTIFIER_PARAMS,
    construct_group_name,
    is_sv_identifier,
    sanitize_sv_identifier,
)
from app.services.core.renderer import render_template
from app.services.intent.normalizer import normalize_intent
from app.services.intent.history import lookup_history, save_history, template_params_fingerprint
from app.services.rag.engine import rag_retrieve, dense_top1_score
from app.services.llm.factory import get_default_llm_client, get_default_llm_config_id


class OffTopicIntentError(ValueError):
    """输入与 IC 验证域无关——由 RAG 之后的 dense 余弦阈值闸触发。

    判定信号：原文 → bge-m3 dense embedding → Qdrant top1 余弦 < 阈值。
    用 original_intent（不是 normalized）做 embedding——normalized 会被 LLM 改写成
    "无法判断类型"之类元说明，意外抬高 off-topic 段分数；原文保留了"远离 IC 域"语义。

    继承 ValueError 让 generate.py 旧的 except ValueError 兜底，
    但端点应优先 catch 本异常以返回结构化 detail。
    """
    def __init__(self, top_dense_score: float = 0.0, threshold: float = 0.0):
        self.top_dense_score = top_dense_score
        self.threshold = threshold
        self.detector = "rag_dense_threshold"
        super().__init__("输入似乎与 IC 验证需求无关")


class CodeTypeMismatchError(ValueError):
    """用户选的 code_type 与意图语义明显不符——dense 跨 code_type 比较发现另一类显著更高。

    判定信号：对每个非选中的 code_type 各跑一次 dense_top1_score，若 max(other) ≥
    selected + margin，把那个 other 当 suggestion 抛出。前端把 detail.type=
    "code_type_mismatch" 翻译成"建议改用 X 类（语义匹配度 a vs b）"。

    跟 OffTopicIntentError 同走 422——都是"用户问题、改了再来"。
    """
    def __init__(
        self,
        selected_code_type: str,
        suggested_code_type: str,
        selected_score: float,
        suggested_score: float,
    ):
        self.selected_code_type = selected_code_type
        self.suggested_code_type = suggested_code_type
        self.selected_score = selected_score
        self.suggested_score = suggested_score
        self.detector = "rag_dense_cross_code_type"
        super().__init__(
            f"意图语义与所选 code_type={selected_code_type} 不符，"
            f"更像是 {suggested_code_type}（dense {suggested_score:.4f} vs {selected_score:.4f}）"
        )


class EmptyRetrievalError(RuntimeError):
    """RAG 检索返空——不是 off-topic（已通过 dense 闸），而是基础设施层异常。

    可能原因：Qdrant 服务不可达、collection 为空（模板未导入）、embedding service
    挂掉。前端应当区分 422（用户问题）和 503（系统问题）：
      - off-topic 走 422 让用户改提问
      - empty retrieval 走 503 让 SRE 排查 / 用户稍后重试

    不继承 ValueError，避免 endpoint 旧 except ValueError 被泛化兜底成 422。
    """
    def __init__(self, code_type: str = ""):
        self.code_type = code_type
        super().__init__(f"RAG 检索为空（code_type={code_type}）——疑似模板库或检索服务故障")


class NoMatchingTemplateError(ValueError):
    """LLM step1 明确拒绝所有 RAG 候选（confidence_source=rag_fallback）——
    库内暂无此验证场景的模板，引导用户贡献新模板而非让其在 IntentBuilder 里无意义对话 5 轮。

    触发条件：LLM step1 明确拒绝所有 RAG 候选（confidence_source=="rag_fallback"）即触发。
    top_score 仅供日志/监控参考，不再参与触发判断（cross-encoder 词汇重叠可对
    语义不相关模板给高分，故只信 LLM 判断）。
    NO_MATCH_GATE_ENABLED=false 一键关闸，退回旧 rag_fallback → under_specified 流程。
    """
    def __init__(self, original_intent: str, code_type: str, top_score: float):
        self.original_intent = original_intent
        self.code_type = code_type
        self.top_score = top_score
        self.detector = "no_matching_template"
        params = []
        if original_intent:
            params.append(f"description={quote(original_intent)}")
        params.append(f"code_type={quote(code_type)}")
        self.redirect_to = "/contribute/new?" + "&".join(params)
        super().__init__(
            f"库内无匹配模板（top_score={top_score:.2f}），建议贡献新模板"
        )


class UnderSpecifiedIntentError(ValueError):
    """选中模板但必填参数没有高置信源——契约反转后不再编参数兜底，直接 422 拒。

    判定 "高置信源" = source ∈ {regex, signal_list, default} ∪ (source==llm 且值非"trivial")。
    低置信源 = {semantic_fallback, placeholder, llm-with-trivial-value}。
    任一 required 参数落到低置信源 → 抛此异常。

    v3.0：异常携带 `redirect_to` 让前端无脑 router.push 跳 IntentBuilder 精修，
    URL prefill 用户原文 + missing 参数名 + 已识别 template_id 让 IntentBuilder
    起手即上下文齐全。

    `UNDER_SPECIFIED_GATE_ENABLED=false` 一键关闸退回旧 placeholder 兜底行为。
    """
    def __init__(
        self,
        template_id: str,
        template_name: str,
        missing_params: list[dict],
        original_intent: str = "",
        code_type: str = "",
    ):
        # P1-13：code_type 必须非空——pipeline 入口已经强制要求，但接口层防御性兜底，
        # 避免 IntentBuilder 跳转 URL 缺 code_type 让前端默认 'assertion' 错配。
        if not code_type:
            raise ValueError(
                "UnderSpecifiedIntentError 需要非空 code_type 才能构造 IntentBuilder 跳转 URL"
            )
        self.template_id = template_id
        self.template_name = template_name
        self.missing_params = missing_params
        self.original_intent = original_intent
        self.code_type = code_type
        self.detector = "under_specified_required_param"
        names = ", ".join(p["name"] for p in missing_params)
        # IntentBuilder 跳转 URL：prefill 原文、attach 已识别的 template、列缺什么参数
        params = []
        if original_intent:
            params.append(f"prefill={quote(original_intent)}")
        params.append(f"template_id={quote(template_id)}")
        params.append(f"code_type={quote(code_type)}")
        missing_csv = ",".join(p["name"] for p in missing_params)
        if missing_csv:
            params.append(f"missing={quote(missing_csv)}")
        self.redirect_to = "/intent-builder?" + "&".join(params)
        super().__init__(
            f"模板 {template_id} 已识别，但必填参数缺少高置信源：{names}"
        )


@dataclass
class PipelineInput:
    original_intent: str
    code_type: str
    protocol: str | None = None
    clk: str = "clk"
    rst: str = "rst_n"
    rst_polarity: str = "低有效"
    signals: list[dict] = field(default_factory=list)
    # v3.0 入口标识，仅供日志/统计区分用户旅程：
    #   "direct"        - 用户从 Generate 页直接提交 NL
    #   "intent_builder" - 用户从 IntentBuilder 多轮对话精修后回流
    # 不影响 pipeline 逻辑路由，str 而非 Literal 防破坏外部老调用。
    source: str = "direct"


@dataclass
class PipelineResult:
    """legacy 一步式返回（run_pipeline / batch_tasks 用）。"""
    status: str
    code: str
    template_id: str
    template_name: str
    version: str
    confidence: float
    normalized_intent: str
    intent_hash: str
    rag_candidates: list[dict]
    params_used: dict
    cache_hit: bool = False
    intent_cache_hit: bool = False


@dataclass
class PreviewResult:
    """方案 3 两步式：第一步 preview 输出（含参数来源标识）。"""
    template_id: str
    template_name: str
    template_version: str
    confidence: float
    confidence_source: str                       # "llm_step1" | "rag_fallback" | "intent_cache"
    rag_candidates: list[dict]                   # 含 parameters 字段供前端切换用
    params: dict[str, dict]                      # {name: {value, source, required, description, type}}
    intent_hash: str
    normalized_intent: str
    quick_render: bool = False                   # intent_cache 命中 → True，前端跳确认面板


@dataclass
class RenderInput:
    """方案 3 两步式：第二步 render 输入（用户确认/编辑后的最终参数）。"""
    template_id: str
    template_version: str
    params: dict                                 # value-only dict
    intent_hash: str | None = None               # 透传以关联 history
    confidence: float = 0.0
    normalized_intent: str = ""


async def pipeline_preview(inp: PipelineInput, db: AsyncSession) -> PreviewResult:
    """两步式流水线第一步：意图归一化 → RAG → LLM 选模板/填参数 → 参数源标注。

    不渲染、不写代码缓存。意图缓存命中时返回 quick_render=True 让前端直接调 render。
    """
    from app.models.template import Template

    # Off-topic 早返：用原文（不是 normalized）做 dense 余弦判定，跳过后续整条流水线。
    # 用原文的理由：LLM normalize 会把 off-topic 输入改写成"无法判断类型"之类元说明，
    # 那串字符的 embedding 反而抬高了 off-topic 段分数；原文保留"远离 IC 域"语义。
    # 阈值经 calibrate_offtopic_threshold.py 在 offtopic_corpus.yaml 上校准得出。
    settings = get_settings()
    _t_total = time.perf_counter()
    print(f"[Pipeline] source={inp.source} code_type={inp.code_type}", flush=True)
    selected_dense: float | None = None
    if settings.offtopic_gate_enabled:
        # FEAT-15：off-topic 与 code_type_mismatch 共享一次跨 code_type dense 扫描。
        # 老逻辑只看 selected 子集分数 → 错选 code_type 的真请求会被 off-topic 误拒；
        # 新逻辑用 best_overall = max(selected, max(other)) 做"在域/离域"判定，离域
        # 的同时仍可让 code_type_mismatch 拿到 best_other 信息给出 suggestion。
        _t = time.perf_counter()
        selected_dense = await dense_top1_score(inp.original_intent, code_type=inp.code_type)
        cross_scores = await _compute_cross_code_type_scores(
            inp.original_intent, inp.code_type, selected_dense
        )
        # default sentinel：当 registry 只有一个 code_type 时取不到"非选中"项，
        # best_other_id=None 让 gate 2 跳过；best_other_score=-1.0 让 best_overall
        # 自然退化为 selected_dense（max 不会选到 -1.0）。日志里看到 -1.0000 即此情况。
        best_other_id, best_other_score = max(
            ((ct, s) for ct, s in cross_scores.items() if ct != inp.code_type),
            key=lambda x: x[1],
            default=(None, -1.0),
        )
        best_overall = max(selected_dense, best_other_score)
        print(f"[Timing] stage=offtopic_gate ms={int((time.perf_counter() - _t) * 1000)}", flush=True)

        # gate 1: off-topic —— 全库最高分都低于阈值才算离域。语义切齐前端 Modal 文案
        # "输入与模板库的最高相似度低于阈值"（"模板库" = 全库，不限选中 code_type）。
        if best_overall < settings.offtopic_dense_threshold:
            print(
                f"[Gate] offtopic selected_dense={selected_dense:.4f} "
                f"best_other_id={best_other_id} best_other_score={best_other_score:.4f} "
                f"best_overall={best_overall:.4f} threshold={settings.offtopic_dense_threshold}",
                flush=True,
            )
            raise OffTopicIntentError(
                top_dense_score=best_overall,
                threshold=settings.offtopic_dense_threshold,
            )

        # gate 2: code_type_mismatch —— off-topic 已确认在域，再问"选对了类吗"。
        # 追加 best_other_score >= threshold 前置条件：全库低分时不再给"换类"误导
        # （场景如 selected=0.30 / other=0.42 / gap=0.12，best_other 自身就没"有把握"）。
        if settings.code_type_mismatch_gate_enabled and best_other_id is not None:
            gap = best_other_score - selected_dense
            if (
                gap >= settings.code_type_mismatch_margin
                and best_other_score >= settings.offtopic_dense_threshold
            ):
                print(
                    f"[Pipeline] code_type mismatch: selected={inp.code_type}({selected_dense:.4f}) "
                    f"vs suggested={best_other_id}({best_other_score:.4f}) "
                    f"margin={settings.code_type_mismatch_margin}",
                    flush=True,
                )
                raise CodeTypeMismatchError(
                    selected_code_type=inp.code_type,
                    suggested_code_type=best_other_id,
                    selected_score=selected_dense,
                    suggested_score=best_other_score,
                )

    # Resolve default LLM 提前到 normalize 之前：所有缓存 key 都需要 config_id 分桶，
    # 避免不同 LLM 配置写入的 (template_id, params) 互相覆盖。client 构造无网络 IO，开销可忽略。
    llm = await get_default_llm_client(db)
    llm_config_id = getattr(llm, "config_id", "")

    # Step 1: Intent Normalize
    _t = time.perf_counter()
    normalized, intent_hash = await normalize_intent(inp.original_intent, db, llm=llm)
    print(f"[Timing] stage=normalize ms={int((time.perf_counter() - _t) * 1000)}", flush=True)

    # Step 2: Intent Cache Lookup
    history = await lookup_history(intent_hash, llm_config_id)
    if history:
        tmpl_id = history.get("template_id")
        tmpl_version = history.get("version", "1")
        history_params = history.get("param_mapping", {})
        # 模板可能被编辑（加/删 required 参数、改 expr_type）。比对当前 template 的
        # parameters 指纹与缓存写入时的指纹——不一致就把这条 intent_cache 视为失效，
        # 落到 RAG/LLM 完整路径，避免 StrictUndefined / 丢参 / expr 校验后续报错。
        tmpl = await db.get(Template, tmpl_id) if tmpl_id else None
        cache_valid = True
        if tmpl is None:
            cache_valid = False
        else:
            cached_fp = history.get("params_fingerprint", "")
            current_fp = template_params_fingerprint(tmpl.parameters)
            if cached_fp and cached_fp != current_fp:
                print(
                    f"[Pipeline] intent_cache schema drift: tmpl={tmpl_id} "
                    f"cached_fp={cached_fp} current_fp={current_fp} → bypass cache",
                    flush=True,
                )
                cache_valid = False

        if cache_valid:
            cached_code = await get_generation_cache(tmpl_id, tmpl_version, history_params, llm_config_id)
            if cached_code:
                # 缓存命中：构建一个最小 PreviewResult，标记 quick_render
                params_with_source = {
                    name: {"value": v, "source": "default", "required": True, "description": "", "type": "string"}
                    for name, v in history_params.items()
                }
                return PreviewResult(
                    template_id=tmpl_id,
                    template_name=tmpl.name if tmpl else "",
                    template_version=tmpl.version if tmpl else tmpl_version,
                    confidence=history.get("confidence", 1.0),
                    confidence_source="intent_cache",
                    rag_candidates=[],
                    params=params_with_source,
                    intent_hash=intent_hash,
                    normalized_intent=normalized,
                    quick_render=True,
                )

    # Step 3 + 4: RAG Retrieve
    _t = time.perf_counter()
    rag_candidates = await rag_retrieve(normalized, db, code_type=inp.code_type)
    print(f"[Timing] stage=rag ms={int((time.perf_counter() - _t) * 1000)}", flush=True)

    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for c in rag_candidates:
        if c["template_id"] not in seen_ids:
            seen_ids.add(c["template_id"])
            deduped.append(c)
    rag_candidates = deduped

    # Step 4b: Keyword Supplement —— 必须先于 EmptyRetrievalError 判断，
    # 这样"RAG 返空 + keyword 有命中"也能救场（fallback 链的设计契约）。
    supplements = await _keyword_supplement(
        normalized + " " + inp.original_intent,
        db,
        inp.code_type,
        existing_ids={c["template_id"] for c in rag_candidates},
    )
    supplement_ids: set[str] = set()
    if supplements:
        print(f"[Pipeline] keyword supplement: {[s['template_id'] for s in supplements]}", flush=True)
        rag_candidates = supplements + rag_candidates
        supplement_ids = {s["template_id"] for s in supplements}

    if not rag_candidates:
        # off-topic 闸已经在 step 0 处理，能到这里意味着 dense top1 ≥ threshold 但
        # 既无 RAG 候选也无 keyword 命中 —— 只可能是基础设施问题（Qdrant 空 /
        # 检索服务异常 / 模板库没导入），与"用户离题"在语义上完全不同。
        print(
            f"[Gate] empty_retrieval: code_type={inp.code_type} dense_top1={selected_dense}",
            flush=True,
        )
        raise EmptyRetrievalError(code_type=inp.code_type)

    # Step 5: LLM Step1 + Step2 （llm 已在前面 resolve，无需重取）
    signal_context = _build_signal_context(inp)
    candidate_dicts = [
        {
            "template_id": c["template_id"],
            "name": c["name"],
            "description": c["description"],
            "score": c["score"],
            "parameters": c["template"].parameters if c.get("template") else [],
        }
        for c in rag_candidates
    ]
    _t = time.perf_counter()
    selection = await llm.select_template(
        normalized, signal_context, candidate_dicts, original_intent=inp.original_intent
    )
    print(f"[Timing] stage=llm_select ms={int((time.perf_counter() - _t) * 1000)}", flush=True)
    print(f"[Pipeline] LLM selection: template_id={selection.template_id!r} confidence={selection.confidence}", flush=True)

    template = None
    confidence_source = "llm_step1"
    # FEAT-11 A：跨 A8/A9/quick_render 闸共享的状态——
    #   verify_ok: True=A8 显式通过，False=A8 拒，None=A8 未启用（quick_render 视为不达标）。
    #   selected_score: LLM 选中的 template_id 在 stage3 reranker 输出里的 score；
    #     原本只在 A9 启用时计算，此处提前到 confidence_source=="llm_step1" 时无条件算
    #     一次，供 A9 与 quick_render 高置信判定共用（成本是一次 dict 查找，可忽略）。
    verify_ok: bool | None = None
    selected_score: float | None = None
    if selection.template_id and selection.template_id.lower() not in ("none", "", "null"):
        template = await db.get(Template, selection.template_id)
        # LLM 选中的若是 keyword 补充注入的候选（RAG 三阶段未召回），标专门的源——
        # 让前端 / 日志能区分"LLM 在 RAG top 中挑"与"靠 keyword 才救回来"。
        if template and selection.template_id in supplement_ids:
            confidence_source = "keyword_supplement"

        # A8 二次验证：step1 选中 + confidence_source=="llm_step1" 时，再发一条 yes/no
        # 问询。若 LLM 二次回答否定 → 降级为 rag_fallback，进而被第五道闸（若开启）
        # 拦下引导贡献。keyword_supplement 路径不验（已经是补救路径，不再加压）。
        # fail-open：LLM 调用 / 解析失败默认 True（详见 base.LLMClient.verify_step1_selection）。
        if template and confidence_source == "llm_step1" and settings.step1_verify_enabled:
            _t = time.perf_counter()
            verify_ok = await llm.verify_step1_selection(
                normalized, selection.template_id, candidate_dicts
            )
            print(
                f"[Timing] stage=step1_verify ms={int((time.perf_counter() - _t) * 1000)} "
                f"ok={verify_ok}",
                flush=True,
            )
            if not verify_ok:
                print(
                    f"[Pipeline] step1 verify=no: id={selection.template_id!r} "
                    f"→ confidence_source 降级为 rag_fallback",
                    flush=True,
                )
                confidence_source = "rag_fallback"
                template = None  # 让下面的 fallback 链按 rag_fallback 走 RAG top1

        # FEAT-11 A：selected_score 无条件计算（confidence_source 仍为 llm_step1 时）。
        # 与下方 A9 gate 共享；quick_render 高置信判定也用同一份值。
        # 隐性规则：当 LLM 选中的是 keyword_supplement 注入的候选（不在 RAG top-N 里）
        # 时，confidence_source 已被改为 "keyword_supplement"，本块不会执行——所以
        # keyword_supplement 路径既不触发 A9 reranker gate 也不参与高置信 quick_render
        # 判定。这是有意的：keyword 补充本身就是 RAG 召回失败的兜底，不应再加额外门槛。
        if template and confidence_source == "llm_step1":
            selected_score = next(
                (c["score"] for c in rag_candidates if c["template_id"] == selection.template_id),
                None,
            )

        # A9 reranker score gate（pipeline 层独立 gate）：A8 verify=yes 之后查 LLM
        # 选中的 template_id 在 stage3 reranker 输出里的 score。低于阈值 → 抛
        # NoMatchingTemplateError 让用户去贡献。
        # 与 FIX-9 移除的 RAG top-1 score 阈值的区分：FIX-9 拦的是"top-1 分数低就
        # 整体否决 LLM 决策"，会让 cpu_req / dma_req 互斥意图被 score=1.0 的握手模
        # 板带偏；A9 拦的是"LLM 信心十足选了某 id，但该 id 客观重排得分仍偏低"，是
        # LLM 决策 + reranker 复核的双信号互证，触发更稀少且方向更精确。
        # 注意：rag_candidates 中的 `score` 字段就是 stage3 reranker score
        # （见 services/rag/engine.py:114 enriched["score"] = item["score"]）。
        if (
            template
            and confidence_source == "llm_step1"
            and settings.step1_reranker_gate_enabled
            and selected_score is not None
            and selected_score < settings.reranker_min_score_threshold
        ):
            print(
                f"[Gate] step1_reranker_gate: id={selection.template_id!r} "
                f"selected_score={selected_score:.4f} < threshold="
                f"{settings.reranker_min_score_threshold} → NoMatchingTemplate",
                flush=True,
            )
            raise NoMatchingTemplateError(
                original_intent=inp.original_intent,
                code_type=inp.code_type,
                top_score=selected_score,
            )

    # Off-topic 检测的唯一信号是 normalize_intent 的 sentinel 输出（在本函数早期已检查并早返）。
    # 这里**不**再用 RAG cross-encoder 分数作为闸——实测发现 reranker 对不同 code_type 子语料
    # 的绝对分数分布完全不一致（assertion 给 0.833、coverage 直接给 1.0），无法跨语料校准；
    # 用任何阈值都会误伤 marginal 真请求（如"4 位 state_reg 0-15 覆盖率"被打到 0.833）。

    # Fallback: LLM 选不到时取 RAG 第一名（marginal 真请求；保留 LLM 上报的 confidence，
    # 不再用 RAG 分数覆盖——RAG cross-encoder 分数是排序指标，不是"确信度"指标）。
    if not template:
        fallback_id = rag_candidates[0]["template_id"]
        template = await db.get(Template, fallback_id)
        print(f"[Pipeline] LLM selected '{selection.template_id}', fallback to: {fallback_id}", flush=True)
        if template:
            from app.schemas.intent import TemplateSelectionOutput
            selection = TemplateSelectionOutput(
                template_id=fallback_id,
                param_mapping=selection.param_mapping,
                confidence=selection.confidence,
            )
            confidence_source = "rag_fallback"

    # 第五道闸：LLM 明确拒绝所有候选（rag_fallback）→ 库内暂无此场景模板，
    # 直接引导贡献，省去无意义的 5 轮 IntentBuilder 对话。
    # 与 under_specified 的区别：under_specified = 模板已识别但参数不全；
    # no_matching_template = 连模板本身都没有高置信命中。
    # FIX-9：去掉 RAG score 阈值条件——cross-encoder 词汇重叠会给语义不相关模板
    # 1.0 分（如 cpu_req/dma_req 互斥意图命中含 req 关键词的握手模板），
    # score 阈值反而否决 LLM 正确的 none 判断。只信 LLM step1。
    if (
        confidence_source == "rag_fallback"
        and settings.no_match_gate_enabled
    ):
        print(
            f"[Gate] no_matching_template: top_score={rag_candidates[0]['score']:.4f}",
            flush=True,
        )
        raise NoMatchingTemplateError(
            original_intent=inp.original_intent,
            code_type=inp.code_type,
            top_score=rag_candidates[0]["score"],
        )

    if not template:
        raise ValueError("未能确定有效模板，请检查模板库或调整意图描述")

    # Step 6: Param Map with source tracking
    regex_mapping = _extract_params_from_intent(inp.original_intent)
    params_with_source = _map_params_with_source(
        template, inp, regex_mapping=regex_mapping, llm_mapping=selection.param_mapping
    )
    print(f"[Pipeline] params={_values_only(params_with_source)}", flush=True)
    print(
        f"[Pipeline] params_resolved: "
        f"{[(n, m.get('source'), m.get('value')) for n, m in params_with_source.items()]}",
        flush=True,
    )

    # Step 6b: Under-specified intent gate（契约反转：必填参数缺高置信源 → 422 拒）
    # 紧跟 _map_params 之后、_values_only 之前——拿全部 source 标签做判定，让用户
    # 知道具体缺哪个参数而不是看到一堆 placeholder 想"系统好像很懂"再交付错代码。
    # intent_text=original_intent：grounding 检查用，防 LLM 凭空编泛用默认值。
    if settings.under_specified_gate_enabled:
        # 用 _build_form_values 取统一构造（与 _map_params_with_source step-1 守卫共享真相源）
        form_values = _build_form_values(inp)
        missing = _detect_under_specified(
            params_with_source, template.parameters or [],
            intent_text=inp.original_intent,
            form_values=form_values,
        )
        if missing:
            names = [m["name"] for m in missing]
            print(
                f"[Pipeline] under_specified gate: template={template.id} "
                f"missing={names}",
                flush=True,
            )
            raise UnderSpecifiedIntentError(
                template_id=template.id,
                template_name=template.name,
                missing_params=missing,
                original_intent=inp.original_intent,
                code_type=inp.code_type,
            )

    # FEAT-11 A：四条件齐绿 → 高置信 RAG，跳过 ConfirmationPanel 直渲。
    # 与 intent_cache 命中走的 quick_render 是同一旗标，前端代码路径透明承接。
    # 判定四条件：
    #   1) confidence_source == "llm_step1"（rag_fallback / keyword_supplement 不算）
    #   2) settings.step1_verify_enabled 且 A8 verify=yes（disabled 时禁直渲——
    #      没二次校验就少了一个独立信号，不够稳）
    #   3) selected_score >= settings.reranker_min_score_threshold（独立于 A9 开关；
    #      score 现在已无条件计算，gate 是否开启不影响本判定）
    #   4) 所有 param sources ∈ {llm, regex, signal_list, default}——
    #      semantic_fallback / placeholder 一定不算（under_specified 闸已拦但
    #      关闸时仍可能漏过，本判定双保险）。
    is_high_conf_rag = _is_high_confidence_rag(
        confidence_source=confidence_source,
        verify_ok=verify_ok,
        selected_score=selected_score,
        params_with_source=params_with_source,
        settings=settings,
    )
    if is_high_conf_rag:
        print(
            f"[Pipeline] FEAT-11 high-confidence RAG: template={template.id} "
            f"selected_score={selected_score:.4f} → quick_render=True",
            flush=True,
        )

    print(f"[Timing] stage=preview_total ms={int((time.perf_counter() - _t_total) * 1000)}", flush=True)

    # 构建 RAG 候选摘要（含 parameters 供前端切换用）
    rag_summary = [
        {
            "template_id": c["template_id"],
            "name": c["name"],
            "score": c["score"],
            "parameters": c["template"].parameters if c.get("template") else [],
        }
        for c in rag_candidates
    ]

    return PreviewResult(
        template_id=template.id,
        template_name=template.name,
        template_version=str(template.version),
        confidence=selection.confidence,
        confidence_source=confidence_source,
        rag_candidates=rag_summary,
        params=params_with_source,
        intent_hash=intent_hash,
        normalized_intent=normalized,
        quick_render=is_high_conf_rag,
    )


_HIGH_CONFIDENCE_PARAM_SOURCES = frozenset({"llm", "regex", "signal_list", "default"})


def _is_high_confidence_rag(
    confidence_source: str,
    verify_ok: bool | None,
    selected_score: float | None,
    params_with_source: dict[str, dict],
    settings,
) -> bool:
    """FEAT-11 A：判断是否所有四条件均满足，足以跳过 ConfirmationPanel 直渲。

    任一条件不达标即 False（保证默认行为不回归）。详细判定见调用点上方注释。
    """
    if confidence_source != "llm_step1":
        return False
    if not settings.step1_verify_enabled or verify_ok is not True:
        return False
    if (
        selected_score is None
        or selected_score < settings.reranker_min_score_threshold
    ):
        return False
    for meta in params_with_source.values():
        if meta.get("source") not in _HIGH_CONFIDENCE_PARAM_SOURCES:
            return False
    return True


async def pipeline_render(req: RenderInput, db: AsyncSession) -> tuple[str, bool]:
    """两步式流水线第二步：用户确认参数后渲染 + 写缓存 + 保存历史。

    返回 (code, cache_hit)。GenerationRecord 由 API 端点写（不在此函数内）。
    """
    from app.models.template import Template
    template = await db.get(Template, req.template_id)
    if not template:
        raise ValueError(f"模板不存在: {req.template_id}")

    # 缓存按当前 default LLM 分桶。轻量版 helper 只查 id 不构造 client。
    llm_config_id = await get_default_llm_config_id(db)

    # Step 5b: Generation cache lookup
    version_str = str(template.version)
    cached_code = await get_generation_cache(template.id, version_str, req.params, llm_config_id)
    if cached_code:
        return cached_code, True

    # Step 7: Render
    code = render_template(template.template_body, req.params, template.id, version_str)

    # Step 8: Cache write + history save
    await set_generation_cache(template.id, version_str, req.params, code, llm_config_id)
    if req.intent_hash:
        await save_history(
            intent_hash=req.intent_hash,
            template_id=template.id,
            param_mapping=req.params,
            confidence=req.confidence,
            code=code,
            llm_config_id=llm_config_id,
            params_fingerprint=template_params_fingerprint(template.parameters),
            template_version=version_str,
        )

    return code, False


async def run_pipeline(inp: PipelineInput, db: AsyncSession) -> PipelineResult:
    """legacy 一步式封装：依次调 preview + render，给 batch_tasks / 既有 /generate 端点用。"""
    preview = await pipeline_preview(inp, db)
    params_value_only = _values_only(preview.params)

    if preview.quick_render:
        # intent_cache 命中：preview 已经把缓存 code 透传了；需要 render 来取 code
        # 但缓存的 code 在 history 里，需要重查 generation_cache
        legacy_cfg_id = await get_default_llm_config_id(db)
        cached_code = await get_generation_cache(
            preview.template_id, preview.template_version, params_value_only, legacy_cfg_id
        )
        if cached_code:
            return PipelineResult(
                status="success",
                code=cached_code,
                template_id=preview.template_id,
                template_name=preview.template_name,
                version=preview.template_version,
                confidence=preview.confidence,
                normalized_intent=preview.normalized_intent,
                intent_hash=preview.intent_hash,
                rag_candidates=[],
                params_used=params_value_only,
                cache_hit=True,
                intent_cache_hit=True,
            )

    render_input = RenderInput(
        template_id=preview.template_id,
        template_version=preview.template_version,
        params=params_value_only,
        intent_hash=preview.intent_hash,
        confidence=preview.confidence,
        normalized_intent=preview.normalized_intent,
    )
    code, cache_hit = await pipeline_render(render_input, db)

    rag_summary = [
        {"template_id": c["template_id"], "name": c["name"], "score": c["score"]}
        for c in preview.rag_candidates
    ]
    return PipelineResult(
        status="success",
        code=code,
        template_id=preview.template_id,
        template_name=preview.template_name,
        version=preview.template_version,
        confidence=preview.confidence,
        normalized_intent=preview.normalized_intent,
        intent_hash=preview.intent_hash,
        rag_candidates=rag_summary,
        params_used=params_value_only,
        cache_hit=cache_hit,
        intent_cache_hit=False,
    )


def _values_only(params_with_source: dict[str, dict]) -> dict:
    """从 {name: {value, source, ...}} 提取纯值字典，供 render_template 使用。"""
    return {name: meta["value"] for name, meta in params_with_source.items()}


async def _compute_cross_code_type_scores(
    intent: str,
    selected_code_type: str,
    selected_score: float,
) -> dict[str, float]:
    """跨 registry 里所有 code_type 跑 dense top1，返回 {code_type_id: dense_top1_score}。

    返回的字典 **包含 selected_code_type 自身**——值复用传入的 selected_score，
    避免重复 embedding 调用。调用方若只需"非选中"子集，自行过滤：
        {ct: s for ct, s in d.items() if ct != selected_code_type}

    被 pipeline_preview 的 gate 1（off-topic）+ gate 2（code_type_mismatch）共享，
    一次调用满足两个闸的判定数据。
    """
    from app.services.registry import get_registry
    registry = get_registry()
    scores: dict[str, float] = {selected_code_type: selected_score}
    for ct in registry.all():
        if ct.id == selected_code_type:
            continue
        scores[ct.id] = await dense_top1_score(intent, code_type=ct.id)
    return scores


async def _keyword_supplement(
    intent: str,
    db: AsyncSession,
    code_type: str,
    existing_ids: set[str],
    top_n: int = 2,
) -> list[dict]:
    """直接查 DB 补充关键词匹配的模板，弥补向量搜索的召回盲区。"""
    from app.models.template import Template
    stmt = select(Template).where(Template.code_type == code_type, Template.is_active == True)
    result = await db.execute(stmt)
    all_templates = result.scalars().all()

    intent_lower = intent.lower()
    scored: list[tuple[int, Template]] = []
    for tmpl in all_templates:
        if tmpl.id in existing_ids:
            continue
        keywords = tmpl.keywords or []
        score = sum(1 for kw in keywords if kw.lower() in intent_lower)
        if score > 0:
            scored.append((score, tmpl))

    scored.sort(key=lambda x: -x[0])

    supplements = []
    for score, tmpl in scored[:top_n]:
        supplements.append({
            "template_id": tmpl.id,
            "name": tmpl.name,
            "description": tmpl.description,
            "score": float(score) * 0.1,
            "template": tmpl,
        })
    return supplements


_ASSERTION_SIGNAL_PATTERNS: list[tuple[str, list[str]]] = [
    # —— 强分隔符模式（保守，明确"X 信号名为 Y"句式）——
    (r'使能(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)',           ['enable']),
    (r'数据(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)',           ['data']),
    (r'valid(?:\s*信号)?\s*[为是：:]\s*([A-Za-z_]\w*)',          ['valid']),
    (r'ready(?:\s*信号)?\s*[为是：:]\s*([A-Za-z_]\w*)',          ['ready']),
    (r'目标(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)',           ['target']),
    (r'起始(?:信号|事件)?\s*[为是：:]\s*([A-Za-z_]\w*)',         ['start_event']),
    (r'(?:结束|应答)(?:信号|事件)?\s*[为是：:]\s*([A-Za-z_]\w*)', ['end_event']),
    (r'状态信号(?:名)?\s*[为是：:]\s*([A-Za-z_]\w*)',            ['state_sig']),
    # —— 叙述式（中文角色词紧邻标识符，标识符 ≥ 2 字符避免误捕单字母变量）——
    # 例：「当写使能 wr_en 无效时」→ enable=wr_en
    (r'(?:写|读)?使能\s+([A-Za-z_]\w{1,})\b',                    ['enable']),
    # 例：「被保护的数据信号 data_in」→ data=data_in（前缀"数据"/"信号"必须存在）
    (r'(?:被保护的?)?数据(?:信号)?\s+([A-Za-z_]\w{1,})\b',       ['data']),
]


def _extract_params_from_intent(intent: str) -> dict:
    """从自然语言描述中用正则提取常见参数值。

    覆盖范围：
      coverage 模板：signal / group_name / signal_width / state_list / bins_expr
      assertion 模板：module_name / max_cycles / max_delay / init_value /
                     enable / data / valid / ready / target / start_event /
                     end_event / state_sig

    enable / data 同时支持两种模式：
      1) 强分隔符："X 信号名 [为/是/:] Y"（如"使能信号为 wr_en"）
      2) 叙述式："X Y"（X=中文角色词，Y=ASCII 标识符 ≥2 字符），如"使能 wr_en 拉高"
         覆盖用户常见 narrative-Chinese 写法，避免完全压在 LLM Step2 上

    不覆盖（依赖 LLM Step2 + signal-list role-hint 兜底）：
      from_state / to_state / condition（fsm_state_transition）— 太语义化
      settle_cycles（reset_behavior）— 与 max_cycles 单位冲突
    """
    params: dict = {}

    # ── coverage 模板参数 ──────────────────────────────────────────────────

    # 信号名：状态信号名为cur_state / 信号名为xxx / 信号xxx
    m = re.search(r'(?:状态)?信号名?[为是：:]\s*(\w+)', intent)
    if m:
        params["signal"] = m.group(1)
        params["group_name"] = m.group(1)

    # 位宽：位宽3位 / 3位宽 / 位宽为3
    m = re.search(r'位宽[为是]?\s*(\d+)|(\d+)\s*位(?:宽)?', intent)
    if m:
        params["signal_width"] = int(m.group(1) or m.group(2))

    # 状态列表：优先从"状态包括/有/为"等关键词后提取，避免误匹配 FSM 等缩写
    # 由于 Python 3 \w 包含 CJK 字符，\b 在 "括IDLE" 这种位置不会触发，需要用上下文锚点
    state_section = re.search(r'(?:状态)?(?:包括|有|为|是|包含)\s*([A-Z][A-Z0-9_、,，\s]+)', intent)
    if state_section:
        states = re.findall(r'[A-Z][A-Z0-9_]+', state_section.group(1))
    else:
        # 兜底：取所有 ≥3 字符的大写序列（过滤掉 FSM 等 2-3 字缩写需另判）
        states = re.findall(r'(?<![A-Za-z])[A-Z][A-Z0-9_]{2,}(?![A-Za-z])', intent)
    if len(states) >= 2:
        params["state_list"] = ", ".join(states)
        params["bins_expr"] = "{" + ", ".join(states) + "}"

    # ── assertion 模板参数 ────────────────────────────────────────────────

    # module_name：模块名为 reg_block / 模块名是 X / 模块: X
    m = re.search(r'模块名?\s*[为是：:]\s*([A-Za-z_]\w*)', intent)
    if m:
        params["module_name"] = m.group(1)

    # max_cycles / max_delay：N 周期内 / N 个周期 / 8 周期
    # 同时填两个 key，模板 parameters 里没声明的会被 _map_params 静默忽略
    m = re.search(r'(\d+)\s*(?:个)?\s*周期(?:内|以内)?', intent)
    if m:
        n = int(m.group(1))
        params["max_cycles"] = n
        params["max_delay"] = n

    # init_value：初始值为 0 / 复位值: 0xFF / 初始值是 1
    # 注意：hex 模式必须排在 \d+ 之前，否则 \d+ 会先匹配 "0xFF" 中的 "0" 就停下
    m = re.search(r'(?:初始|复位)值\s*[为是：:]?\s*(0[xX][\da-fA-F]+|\d+)', intent)
    if m:
        params["init_value"] = m.group(1)

    # 信号名（保守模式，要求强分隔符 [为是：:]）
    for pattern, param_names in _ASSERTION_SIGNAL_PATTERNS:
        m = re.search(pattern, intent, re.IGNORECASE)
        if m:
            for pname in param_names:
                params.setdefault(pname, m.group(1))

    print(f"[Pipeline] extracted from intent: {params}", flush=True)
    return params


def _build_signal_context(inp: PipelineInput) -> str:
    lines = [f"时钟: {inp.clk}", f"复位: {inp.rst}（{inp.rst_polarity}）"]
    if inp.protocol:
        lines.append(f"协议: {inp.protocol}")
    if inp.signals:
        lines.append("信号列表:")
        for s in inp.signals:
            lines.append(f"  - {s['name']} [width={s.get('width', 1)}] role={s.get('role', 'other')}")
    return "\n".join(lines)


_TRIVIAL_LLM_VALUES = {"", "0", "null", "none", "n/a", "todo", "unknown"}


def _llm_value_grounded_in_intent(value, intent_text: str) -> bool:
    """LLM 给的值是否真在用户原文里出现过——防 LLM "善解人意"瞎编。

    判定逻辑：
      - 空 / trivial → False
      - 直接 substring 命中 → True（case-insensitive）
      - 拆分逗号/空格/分号 token，任一长度≥2 的非 trivial token 在原文 → True
        （宽松处理 state_list / identifier_list 这类组合值，只要 LLM 引用了真信号
        名/状态名就放过；纯靠"IDLE, ACTIVE, DONE"这种系统经验填的会被拦）
      - 整数值：把 str(int) 当字符串走上面规则
    """
    if value is None:
        return False
    s = str(value).strip().lower()
    if not s or s in _TRIVIAL_LLM_VALUES:
        return False
    intent_lower = intent_text.lower()
    if s in intent_lower:
        return True
    tokens = re.split(r"[\s,;|/]+", s)
    return any(
        len(t) >= 2 and t not in _TRIVIAL_LLM_VALUES and t in intent_lower
        for t in tokens
    )


def _detect_under_specified(
    params_with_source: dict[str, dict],
    parameters: list[dict],
    intent_text: str = "",
    form_values: list[str] | None = None,
) -> list[dict]:
    """识别"必填但只有低置信源"的参数，供 pipeline 抛 UnderSpecifiedIntentError。

    返回每条 missing 含 {name, description, expr_type, role_hint}——前端拿来生成
    "请补充：…"提示语。空列表表示全部参数都有高置信源。

    低置信源判定：
      - source ∈ {placeholder, semantic_fallback}：必拦
      - source == llm：
          * 值是 trivial（空串/0/null/字面参数名且非模板默认）：必拦
          * 值既不在用户原文里出现 **也不在 form_values 里**（既不 substring 命中也不
            token 命中）：LLM 凭空编 → 拦。
            例外：intent_text 为空（如单参数 mock 测试）则跳过这条检查
      - 其余 (regex / signal_list / default)：放过

    form_values：用户在 GenerateForm 通过结构化字段提供的信号名/值（clk='aclk'、rst='aresetn'
    + signals 列表里每个信号 name）。这些都被注入到 LLM 的 system prompt 作 signal_context，
    LLM 引用它们是合法 grounding。grounding 检查若只看 intent_text 会假阳性。
    """
    missing: list[dict] = []
    for param_def in parameters:
        if not param_def.get("required"):
            continue
        name = param_def.get("name")
        if not name:
            continue
        meta = params_with_source.get(name)
        if not meta:
            continue
        source = meta.get("source")
        value = meta.get("value")
        is_low_conf = False
        if source in ("placeholder", "semantic_fallback"):
            is_low_conf = True
        elif source == "llm":
            if value in (None, 0):
                is_low_conf = True
            elif isinstance(value, str):
                if value.strip().lower() in _TRIVIAL_LLM_VALUES:
                    is_low_conf = True
                elif value == name and param_def.get("default") != name:
                    # LLM 返字面参数名：先做 grounding 检查——信号名恰好与参数名相同
                    # （如 AXI valid/ready）且用户原文中出现该词，视为合法；否则视为 LLM 弃权。
                    if (
                        not intent_text
                        or (
                            not _llm_value_grounded_in_intent(value, intent_text)
                            and not _llm_value_in_form_values(value, form_values or [])
                        )
                    ):
                        is_low_conf = True
            # Grounding 检查：LLM 给的值是否在用户原文 **或 form_values** 里出现
            # 跳过：intent_text 为空（mock 单测）/ 已被 trivial 拦下 / 等于模板 default
            if (
                not is_low_conf
                and intent_text
                and param_def.get("default") != value
                and not _llm_value_grounded_in_intent(value, intent_text)
                and not _llm_value_in_form_values(value, form_values or [])
            ):
                is_low_conf = True
        if is_low_conf:
            missing.append({
                "name": name,
                "description": param_def.get("description", ""),
                "expr_type": param_def.get("expr_type"),
                "role_hint": param_def.get("role_hint"),
            })
    return missing


def _llm_value_in_form_values(value, form_values: list[str]) -> bool:
    """LLM 给的值是否等于用户 form 字段里某个值（case-insensitive）。"""
    if value is None or not form_values:
        return False
    s = str(value).strip().lower()
    if not s:
        return False
    return any(s == str(fv).strip().lower() for fv in form_values if fv)


def _build_form_values(inp: PipelineInput) -> list[str]:
    """收集用户通过 GenerateForm 显式提供的所有结构化值，作 LLM grounding 额外来源。

    本函数是 _map_params_with_source step-1 FIX-2 守卫与 _detect_under_specified
    闸的**共享真相源**——两层判定都必须看同一个 form_values 集合，否则会出现
    "step1 放过但 gate 拦下"或反之的不一致。**禁止在两层各自内联构造**，
    新增 form 字段时（如表单加 clock domain、protocol mode 等）只改这里。

    收集来源：
      - inp.clk / inp.rst / inp.rst_polarity：时钟、复位、复位极性
      - inp.protocol：协议名（仅当用户在表单设置，None/空跳过）。当前模板库无
        protocol 参数，但 _build_signal_context 已经把它注入 LLM system prompt，
        LLM 引用它合法 → 这里也得 ground 通过，否则两层判定漂移。
      - inp.signals[].name：用户填的所有信号名
    """
    values = [inp.clk, inp.rst, inp.rst_polarity]
    if inp.protocol:
        values.append(inp.protocol)
    values.extend(s.get("name", "") for s in inp.signals if s.get("name"))
    return values


def _map_params_with_source(
    template,
    inp: PipelineInput,
    regex_mapping: dict,
    llm_mapping: dict,
) -> dict[str, dict]:
    """方案 3：返回每参数的 value + source 标识（6 类源），供前端徽标显示。

    优先级（与 legacy _map_params 对齐：LLM > regex > signal-list > default > placeholder）：
      1. llm        — LLM Step2 推断
      2. regex      — _extract_params_from_intent 正则提取
      3. signal_list — 用户填写的信号列表 + role-hint 自动映射
      4. default    — 模板 default 字段 / clk/rst/rst_polarity from PipelineInput / 语义兜底
      5. placeholder — required 参数仍缺失时用参数名本身（生成代码会出现字面量，必须用户改）
    """
    parameters: list[dict] = template.parameters or []
    param_meta = {p["name"]: p for p in parameters if p.get("name")}
    result: dict[str, dict] = {}

    def _set(name: str, value, source: str) -> None:
        if name in result:
            return
        meta = param_meta.get(name, {})
        result[name] = {
            "value": value,
            "source": source,
            "required": meta.get("required", False),
            "description": meta.get("description", ""),
            "type": meta.get("type", "string"),
        }

    # 1. LLM 优先（与 legacy {**extracted, **selection.param_mapping} 保持一致）
    #    trivial 弃权值（""/"null"/"unknown" 等）跳过槽位，让 regex → signal_list →
    #    default 链路有机会接管；判定条件**只复刻** _detect_under_specified 里
    #    **context-free** 的两条（None/0 + 字符串集合），目的是让两层语义一致：
    #    "trivial 即弃权"不会因为 step1 抢先 _set 而被绕过。
    #
    #    关于 bool（Python 里 bool 是 int 子类，False == 0、True == 1）：
    #      - False：被首行 `value in (None, 0)` 命中而跳过——与下游
    #        _detect_under_specified `if value in (None, 0)` 分支行为一致
    #        （False 同样被视为低置信）。
    #      - True ：`True in (None, 0)` 为 False（True == 1），又不是 str，所以
    #        会走到 _set 标 source=llm——下游 _detect_under_specified 同样
    #        视 True 为高置信（True 不在 (None, 0) 也不是 trivial 字符串）。
    #      `isinstance(value, str)` 必须保留：一来是 `.strip().lower()` 的前置
    #      防御（None/int/bool 调用 .strip 会 AttributeError），二来明确告诉
    #      读者非字符串值不参与字符串集合判定。当前模板库无 bool 参数；若未
    #      来出现合法 default=False / default=0 的参数，需要同时修 step 1 与
    #      _detect_under_specified。
    #
    #    关于 value == name（字面参数名弃权）的**有意不对称**：
    #      _detect_under_specified `elif value == name and param_def.get("default") != name`
    #      分支把 "LLM 返字面参数名 AND 模板 default != 参数名" 视为低置信，
    #      但该判定**依赖 param_def 上下文**（要看模板有没有 default=参数名，
    #      如 clk default='clk' 是合法值），不属于 context-free 集合。
    #      在 step 1 复刻会误伤合法 default——故统一由 _detect_under_specified
    #      裁决，本 guard 只做无上下文的过滤。
    #
    #    FIX-2 追加守卫（"ungrounded + 有 default → defer"）：
    #      非 trivial 但**完全不在用户原文/form 字段里**的 LLM 值（典型: LLM 把
    #      module_name 填成 'top'、group_name 填成 'cov_group'），原实现把它锁
    #      死 source=llm，使模板 yaml 的 default 永远没机会接管；下游
    #      _detect_under_specified 的 grounding check 又会把它打成低置信源 → 422
    #      把用户赶进 IntentBuilder，**即使模板 default 已经能给出可用值**。
    #      此处先把"模板有 default 且 LLM 值未 grounded"识别出来 → 跳过 _set，
    #      让 step 4 的 default 接管。判定**复用** _llm_value_grounded_in_intent /
    #      _llm_value_in_form_values 两个 helper，与 _detect_under_specified
    #      的 grounding check 同一标准（避免两层判定漂移）。
    #      触发顺序：trivial 守卫 → has-default+ungrounded 守卫 → _set。
    #      mock 单测（intent_text==""）跳过本守卫，与 _detect_under_specified 一致。
    #      模板没有 default 的参数仍走老路径（_set 标 llm，由 _detect_under_specified
    #      最终裁决拦/放）——这条不动是因为没有 default 兜底，让 LLM 值占位
    #      才能保留前端"显示具体出错值"的能力。
    intent_text = inp.original_intent or ""
    form_values = _build_form_values(inp)
    for name, value in llm_mapping.items():
        if value in (None, 0):
            continue
        if isinstance(value, str) and value.strip().lower() in _TRIVIAL_LLM_VALUES:
            continue
        if intent_text:
            param_def = param_meta.get(name, {})
            if (
                "default" in param_def
                and not _llm_value_grounded_in_intent(value, intent_text)
                and not _llm_value_in_form_values(value, form_values)
            ):
                continue
        _set(name, value, "llm")

    # 2. regex（不覆盖 LLM）
    for name, value in regex_mapping.items():
        _set(name, value, "regex")

    # 3. signal-list role-hint
    signals_by_role: dict[str, list[dict]] = {}
    for sig in inp.signals:
        role = sig.get("role", "other")
        signals_by_role.setdefault(role, []).append(sig)

    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in result:
            continue
        role_hint = param_def.get("role_hint")
        if role_hint and role_hint in signals_by_role:
            matched = signals_by_role[role_hint]
            value = matched[0]["name"] if len(matched) == 1 else [m["name"] for m in matched]
            _set(name, value, "signal_list")

    # 4. defaults（clk/rst/rst_polarity from PipelineInput + template default）
    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in result:
            continue
        if name == "clk":
            _set(name, inp.clk, "default")
        elif name in ("rst", "rst_n"):
            _set(name, inp.rst, "default")
        elif name == "rst_polarity":
            _set(name, inp.rst_polarity, "default")
        elif "default" in param_def:
            _set(name, param_def["default"], "default")

    # 5. semantic fallbacks（系统按经验猜，**不是**用户提供）
    #
    # 重要：这里产出的源标签 **不能** 再用 "default"——"default" 留给用户表单
    # （PipelineInput.clk/rst/rst_polarity）和模板 yaml `default` 字段。混在一起
    # 会让 under_specified 闸无法分辨"用户给的"和"系统编的"。
    # 单一例外：signal 从 inp.signals[0] 兜——那是用户真给的信号列表，标 signal_list。
    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in result:
            continue
        if name == "group_name":
            # FIX-2 之后这条 fallback 对生产 4 个 coverage 模板（value/cross/
            # transition/protocol_handshake）实际不可达——它们都加了 default。
            # 留作未来"group_name 无 default"新模板的兜底。
            value = "cov_group"
            for sig_key in ("signal", "valid", "data", "state"):
                if sig_key in result:
                    value = result[sig_key]["value"]
                    break
            _set(name, value, "semantic_fallback")
        elif name == "signal":
            if inp.signals:
                # 用户提供的 signal 列表 → 高置信源
                _set(name, inp.signals[0]["name"], "signal_list")
        elif name == "state_list":
            _set(name, "IDLE, ACTIVE, DONE", "semantic_fallback")
        elif name == "bins_expr":
            width = 4
            if "signal_width" in result:
                try:
                    width = int(result["signal_width"]["value"])
                except (TypeError, ValueError):
                    pass
            _set(name, f"{{[0:{2**width - 1}]}}", "semantic_fallback")

    # 6. placeholder（required 参数兜底用参数名本身）
    for param_def in parameters:
        name = param_def.get("name")
        if name and name not in result and param_def.get("required"):
            _set(name, name, "placeholder")

    # 7. expr_type-driven 校验/sanitize（最后一道防线，覆盖所有源）
    #    优先按模板 YAML 的 parameters[].expr_type 分发；旧模板未声明时回落到
    #    IDENTIFIER_PARAMS 白名单（按参数名判断），保持后向兼容。
    #
    #    分发规则：
    #      sv_identifier        → sanitize_sv_identifier（修改值，标 sanitized=True）
    #      sv_identifier_list   → 逐项 sanitize（修改值，标 sanitized=True）
    #      sv_boolean_expr / sv_bins_expr → validator（不修改值，invalid 时标 validation_error）
    #      integer / free_text / 未知 → 跳过（由 Pydantic / 前端覆盖）
    gn_meta = result.get("group_name")
    if gn_meta and not is_sv_identifier(gn_meta.get("value")):
        # group_name 被系统改写过都不算"用户给的"——后续 under_specified 闸把
        # source 升级成 semantic_fallback 即可正确归类（防止"系统猜了一个又规范化
        # 后冒充 default"绕过校验）。
        constructed = construct_group_name(result)
        if constructed:
            gn_meta["value"] = constructed
            gn_meta["source"] = "semantic_fallback"
            gn_meta["sanitized"] = True
        else:
            # construct 兜底失败（同伴参数也都是非法 ident）→ 把当前值 sanitize 成合法 id。
            # 避免生成 `covergroup 中文名 ...` 这种直接编译报错的代码。
            cleaned, _changed = sanitize_sv_identifier(
                str(gn_meta.get("value", "")), fallback_prefix="cov"
            )
            gn_meta["value"] = cleaned or "cov_group"
            gn_meta["source"] = "semantic_fallback"
            gn_meta["sanitized"] = True

    for name, meta in result.items():
        param_def = param_meta.get(name, {})
        declared_expr_type = param_def.get("expr_type")

        # 透传 expr_type 让前端能拿到（None 不透传）
        if declared_expr_type is not None:
            meta["expr_type"] = declared_expr_type

        # 实际校验用的 type：声明的 or fallback 到 IDENTIFIER_PARAMS
        effective_type = declared_expr_type or (
            "sv_identifier" if name in IDENTIFIER_PARAMS else None
        )
        if effective_type is None:
            continue

        value = meta.get("value")
        if isinstance(value, list):  # signal_list 多匹配 → 跳过（渲染层会处理）
            continue

        if effective_type == "sv_identifier":
            cleaned, changed = sanitize_sv_identifier(str(value), fallback_prefix=name)
            if changed:
                meta["value"] = cleaned
                meta["sanitized"] = True
        elif effective_type == "sv_identifier_list":
            # 逐项 sanitize 后重组
            items = [p.strip() for p in str(value).split(",") if p.strip()]
            cleaned_items: list[str] = []
            any_changed = False
            for item in items:
                cleaned_item, item_changed = sanitize_sv_identifier(item, fallback_prefix="state")
                cleaned_items.append(cleaned_item)
                any_changed = any_changed or item_changed
            if any_changed and cleaned_items:
                meta["value"] = ", ".join(cleaned_items)
                meta["sanitized"] = True
        elif effective_type in EXPR_TYPE_DISPATCH:
            # sv_boolean_expr / sv_bins_expr：纯 validator，不修改值
            err = EXPR_TYPE_DISPATCH[effective_type](str(value))
            if err:
                meta["validation_error"] = err
        # 其他（integer / free_text / 未知 expr_type）跳过

    return result
