"""模板选择语料生成、冲突检测、LLM 冲突分析服务（FEAT-4 Layer 3b）。

管理员审核新贡献时调用，全程对管理员透明：
- generate_corpus_cases：LLM 根据新模板信息生成回归语料用例
- detect_conflicts：嵌入相似度检测新模板是否会抢走现有语料的正确命中
- generate_llm_analysis：LLM 用业务语言解释冲突并给出修改建议

这三个函数统一由 pre-approve-analysis 端点串联调用，结果通过 Redis 短暂存储
（TTL 1h）供 approve 端点读取并将语料写入 DB。
"""
from __future__ import annotations
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.base import LLMClient
from app.services.embedding_client import get_embedding_client
from app.services.rag.engine import rag_retrieve


# ── Pydantic-free dataclasses for internal use ──────────────────────────────

@dataclass
class RawCorpusCase:
    intent: str
    code_type: str
    expected_template_id: str
    expected_template_name: str
    note: str = ""
    source: str = "auto_generated"


@dataclass
class GeneratedCorpusCases:
    """LLM 生成的语料用例集合。"""
    for_new_template: list[RawCorpusCase] = field(default_factory=list)
    for_neighbors: list[RawCorpusCase] = field(default_factory=list)

    @property
    def all_cases(self) -> list[RawCorpusCase]:
        return self.for_new_template + self.for_neighbors


@dataclass
class ConflictDetail:
    """单条冲突详情（内部，含分数；不直接给管理员看分数）。"""
    intent: str
    code_type: str
    current_template_id: str
    current_template_name: str
    current_top1_score: float
    new_template_score: float


@dataclass
class AnalysisResult:
    """LLM 分析结果（业务语言，无技术细节）。"""
    root_cause: str
    recommendation_field: str          # "description" | "keywords"
    recommendation_text: str           # 建议加入目标字段的具体文本
    confidence: float


# ── 静态语料路径 ─────────────────────────────────────────────────────────────

_STATIC_CORPUS_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "tests" / "data" / "template_selection_corpus.yaml"
)


def _load_static_corpus() -> list[dict]:
    """加载 tests/data/template_selection_corpus.yaml 的 correct_mapping 段。"""
    try:
        import yaml
        with _STATIC_CORPUS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("correct_mapping", [])
    except Exception:
        return []


# ── 向量工具 ─────────────────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 语料生成提示词 ────────────────────────────────────────────────────────────

_CORPUS_GEN_SYSTEM_PROMPT = """\
你是一位 IC 验证领域专家，负责为 SVA 模板选择系统生成回归测试语料。

**任务**：根据新模板的信息和最近邻模板的信息，生成意图短语（intent）列表。

**严格规则**：
1. 为新模板生成 3 条"应命中新模板"的意图——这些意图的语义应明确符合新模板的用途
2. 为每个最近邻模板各生成 1 条"应命中该邻居模板，不应命中新模板"的意图——语义应明显区分两者
3. 意图必须是真实工程师会说的话，使用中文，简洁（15-50 字），不要出现模板名称
4. 必须返回合法 JSON，格式如下：

```json
{
  "for_new_template": [
    {"intent": "意图文本", "note": "说明此意图属于新模板的原因（1 句话）"}
  ],
  "for_neighbors": [
    {
      "neighbor_template_id": "sva_xxx_v1",
      "neighbor_template_name": "邻居模板名",
      "intent": "意图文本",
      "note": "说明此意图属于邻居模板而非新模板的原因（1 句话）"
    }
  ]
}
```
"""


def _build_corpus_gen_prompt(
    contribution_name: str,
    contribution_description: str,
    contribution_code_type: str,
    neighbors: list[dict],
) -> str:
    neighbors_block = "\n".join(
        f"  - ID: {n['template_id']}, 名称: {n['name']}, 描述: {n['description']}"
        for n in neighbors
    )
    return (
        f"新模板信息：\n"
        f"  名称: {contribution_name}\n"
        f"  描述: {contribution_description}\n"
        f"  代码类型: {contribution_code_type}\n\n"
        f"语义最近邻模板（可能与新模板产生语义竞争）：\n{neighbors_block}\n\n"
        "请按要求生成回归语料 JSON。"
    )


def _parse_generated_cases(
    raw_json: str,
    new_template_id: str,
    new_template_name: str,
    code_type: str,
) -> GeneratedCorpusCases:
    """解析 LLM 输出的 JSON，容忍 ```json ... ``` 包裹。"""
    text = raw_json.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return GeneratedCorpusCases()

    for_new: list[RawCorpusCase] = []
    for item in obj.get("for_new_template", []):
        if isinstance(item, dict) and item.get("intent"):
            for_new.append(RawCorpusCase(
                intent=item["intent"],
                code_type=code_type,
                expected_template_id=new_template_id,
                expected_template_name=new_template_name,
                note=item.get("note", ""),
                source="auto_generated",
            ))

    for_neighbors: list[RawCorpusCase] = []
    for item in obj.get("for_neighbors", []):
        if isinstance(item, dict) and item.get("intent") and item.get("neighbor_template_id"):
            for_neighbors.append(RawCorpusCase(
                intent=item["intent"],
                code_type=code_type,
                expected_template_id=item["neighbor_template_id"],
                expected_template_name=item.get("neighbor_template_name", ""),
                note=item.get("note", ""),
                source="auto_generated",
            ))

    return GeneratedCorpusCases(for_new_template=for_new, for_neighbors=for_neighbors)


# ── 公开 API ──────────────────────────────────────────────────────────────────

async def generate_corpus_cases(
    contribution_id: str,
    contribution_name: str,
    contribution_description: str,
    contribution_code_type: str,
    keywords: list[str] | None,
    tags: list[str] | None,
    db: AsyncSession,
    llm: LLMClient,
) -> GeneratedCorpusCases:
    """LLM 根据新模板信息生成回归语料用例集合。

    内部先调 check_semantic_duplicate 找语义最近邻（top-2），
    再让 LLM 生成 3 条命中新模板 + 每邻居 1 条命中邻居的意图。

    `db` 必须由 caller 注入（不要在函数内开 AsyncSessionLocal()）——否则会在
    endpoint session 仍然持有的情况下再占一条连接池连接，并发压力下打爆 pool。
    """
    from app.services.core.dedup import check_semantic_duplicate

    neighbors_raw = await check_semantic_duplicate(
        description=contribution_description,
        name=contribution_name,
        tags=tags,
        keywords=keywords,
        top_k=2,
    )

    # 补全邻居模板名称（check_semantic_duplicate 只返 id + score）
    neighbors: list[dict] = []
    if neighbors_raw:
        from sqlalchemy import select
        from app.models.template import Template
        ids = [n["template_id"] for n in neighbors_raw if n.get("template_id")]
        if ids:
            stmt = select(Template.id, Template.name, Template.description).where(Template.id.in_(ids))
            rows = (await db.execute(stmt)).all()
            by_id = {r.id: r for r in rows}
            for n in neighbors_raw:
                row = by_id.get(n["template_id"])
                if row:
                    neighbors.append({
                        "template_id": row.id,
                        "name": row.name,
                        "description": row.description,
                    })

    if not neighbors:
        neighbors = [{"template_id": "sva_data_integrity_v1", "name": "数据完整性无损坏断言", "description": "验证数据信号无损坏"}]

    prompt = _build_corpus_gen_prompt(
        contribution_name=contribution_name,
        contribution_description=contribution_description,
        contribution_code_type=contribution_code_type,
        neighbors=neighbors,
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": _CORPUS_GEN_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
        temperature=0.0,
    )

    new_tid = f"pending_{contribution_id}"
    return _parse_generated_cases(raw, new_tid, contribution_name, contribution_code_type)


async def detect_conflicts(
    new_template_name: str,
    new_template_description: str,
    new_template_keywords: list[str] | None,
    db: AsyncSession,
) -> list[ConflictDetail]:
    """检测新模板是否会与现有语料中的已知正确命中产生冲突。

    算法：
    1. 将新模板 name+description+keywords 拼接后 embed
    2. 加载静态语料（YAML）+ 动态语料（DB template_corpus_cases）
    3. 对每条语料 intent embed 后计算与新模板的余弦相似度
    4. 同时取该 intent 的当前 RAG top-1 分数
    5. new_score > current_top1_score → 冲突（新模板会排名反转）
    """
    embed_client = get_embedding_client()

    kw_text = " ".join(new_template_keywords) if new_template_keywords else ""
    new_text = f"{new_template_name}。{new_template_description}。{kw_text}".strip("。")
    new_vecs = await embed_client.embed_dense([new_text])
    new_vec = new_vecs[0]

    corpus_cases: list[dict] = []

    # 静态语料
    for case in _load_static_corpus():
        corpus_cases.append({
            "intent": case.get("intent", ""),
            "code_type": case.get("code_type", "assertion"),
            "expected_template_id": case.get("expected_template", ""),
            "expected_template_name": case.get("expected_template", ""),
        })

    # 动态语料（DB）
    try:
        from sqlalchemy import select
        from app.models.template_corpus_case import TemplateCorpusCase
        result = await db.execute(
            select(TemplateCorpusCase).where(TemplateCorpusCase.is_active.is_(True))
        )
        for row in result.scalars().all():
            corpus_cases.append({
                "intent": row.intent,
                "code_type": row.code_type,
                "expected_template_id": row.expected_template_id,
                "expected_template_name": row.expected_template_id,
            })
    except Exception as e:
        # 不能静默 —— 表缺失 / 查询失败会让冲突检测只看到静态语料，
        # 管理员可能看到错误的"无冲突"结果。至少要让运维在日志里能看到。
        print(
            f"[WARN] detect_conflicts: failed to load dynamic corpus from DB: "
            f"{type(e).__name__}: {e}",
            flush=True,
        )

    conflicts: list[ConflictDetail] = []

    for case in corpus_cases:
        if not case["intent"]:
            continue
        intent_vecs = await embed_client.embed_dense([case["intent"]])
        intent_vec = intent_vecs[0]
        new_score = _cosine_similarity(new_vec, intent_vec)

        rag_results = await rag_retrieve(case["intent"], db, code_type=case["code_type"])
        current_top1 = rag_results[0] if rag_results else None
        if current_top1 is None:
            continue

        if new_score > current_top1["score"]:
            conflicts.append(ConflictDetail(
                intent=case["intent"],
                code_type=case["code_type"],
                current_template_id=current_top1["template_id"],
                current_template_name=current_top1.get("name", current_top1["template_id"]),
                current_top1_score=current_top1["score"],
                new_template_score=new_score,
            ))

    return conflicts


# ── LLM 冲突分析提示词 ────────────────────────────────────────────────────────

_ANALYSIS_SYSTEM_PROMPT = """\
你是 IC 验证模板库的质量审核助理。你的任务是分析新模板与现有模板之间的语义冲突，
用业务语言（SVA 验证场景语义，不提 RAG/embedding/向量 等技术术语）向管理员解释：
1. 为什么可能产生冲突（根因，1-3 句话）
2. 如何修改新模板的 description 或 keywords 来消除混淆

**输出格式**（必须是合法 JSON，不要 markdown code fence）：
{
  "root_cause": "根因分析（1-3 句话，纯业务语言）",
  "recommendation": {
    "action": "modify_description 或 modify_keywords",
    "apply_to_field": "description 或 keywords",
    "suggested_text": "建议加入目标字段的具体文本（直接可用，不是建议如何写）",
    "confidence": 0.0~1.0
  }
}
"""


async def generate_llm_analysis(
    new_template_name: str,
    new_template_description: str,
    conflicts: list[ConflictDetail],
    llm: LLMClient,
) -> AnalysisResult:
    """LLM 对冲突列表做根因分析，返回业务语言建议（不含分数等技术细节）。"""
    conflicts_block = "\n".join(
        f"- 已有意图：「{c.intent}」\n  原命中模板：{c.current_template_name}"
        for c in conflicts
    )
    prompt = (
        f"新模板：\n  名称: {new_template_name}\n  描述: {new_template_description}\n\n"
        f"可能发生冲突的已有意图（共 {len(conflicts)} 条）：\n{conflicts_block}\n\n"
        "请分析根因并给出修改建议。"
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
        temperature=0.0,
    )

    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        obj = json.loads(text)
        rec = obj.get("recommendation", {})
        return AnalysisResult(
            root_cause=obj.get("root_cause", ""),
            recommendation_field=rec.get("apply_to_field", "description"),
            recommendation_text=rec.get("suggested_text", ""),
            confidence=float(rec.get("confidence", 0.8)),
        )
    except (json.JSONDecodeError, ValueError):
        return AnalysisResult(
            root_cause=raw[:500],
            recommendation_field="description",
            recommendation_text="",
            confidence=0.5,
        )
