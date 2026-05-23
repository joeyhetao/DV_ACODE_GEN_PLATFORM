"""v3.0 IntentBuilder RAG-grounded 多轮对话引擎。

设计原则（PRD §3.8.1）：
- LLM 不被允许凭空想象任何场景，每轮必须先看库内候选
- 每轮自动跑一次 RAG 检索，把 top-3 模板的 (name, description, parameters) 注入 system prompt
- LLM 引导用户往已存在模板靠拢，逐个补足必填参数
- 累计标准化意图通过 LLM 在回复末尾输出 `<<intent>>...<<end>>` 段抽取
- 5 轮内 top-1 RAG score 始终 < 0.5 → suggest_contribute=True，前端展示贡献入口

关键风险：LLM 不遵守输出格式约定 → accumulated_intent 抽取失败 →
缓解：system prompt 强调输出格式 + regex 兜底
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.intent.session import IntentBuilderSession
from app.services.llm.base import LLMClient
from app.services.rag.engine import rag_retrieve


_TOP_K_PER_TURN = 3                         # 每轮注入 prompt 的 RAG 候选数
_RAG_GROUNDING_THRESHOLD = 0.5              # < 此分数视为"库里没匹配"
_SUGGEST_CONTRIBUTE_AFTER_TURNS = 5         # 连续 N 轮 RAG 都低，触发贡献提示
_INTENT_TAG_RE = re.compile(
    r"<<intent>>(.*?)<<end>>", re.DOTALL,
)
# P1-8：LLM 一次输出多对 tag 时取**最后一对**（最新累计）。findall 保序，所以 [-1] 是最后一对。


@dataclass
class TurnResult:
    """每轮对话产出。"""
    assistant_message: str                  # LLM 引导文本（已剥离 <<intent>>...<<end>>）
    accumulated_intent: str                 # 抽取的标准化意图
    rag_candidates: list[dict]              # [{template_id, name, description, score}]
    suggest_contribute: bool                # 是否建议贡献新模板
    turn_count: int                         # 本轮后的累计轮数


def _build_system_prompt(
    code_type: str,
    rag_candidates: list[dict],
    accumulated_intent: str = "",
) -> str:
    """注入 RAG 候选 + 已累计意图的 system prompt。规则尽量明确，让 LLM 输出格式稳定。

    P1-11 配套：history 里 assistant 段已剥离 <<intent>>...<<end>>，LLM 看不到自己上轮的累计
    意图。因此在 system prompt 显式注入"上轮已累计到 X"，让 LLM 在新一轮可以叠加，而不是
    每轮从头猜。
    """
    if rag_candidates:
        candidates_block = "\n\n".join(
            f"候选 {i+1}（相似度 {c['score']:.2f}）：{c['template_id']} — {c['name']}\n"
            f"  描述：{c['description']}\n"
            f"  必填参数：{_format_params(c.get('template'))}"
            for i, c in enumerate(rag_candidates)
        )
    else:
        candidates_block = "（暂无候选——库里可能没有对应模板）"

    accumulated_block = (
        f"### 上轮累计意图（来自上轮 <<intent>>...<<end>> 段）\n{accumulated_intent}\n\n"
        if accumulated_intent else ""
    )

    return (
        "你是 IC 验证助手，正在帮工程师把模糊的验证需求标准化为可由模板库渲染的明确意图。\n"
        f"代码类型：{code_type}\n\n"
        "### 严格规则\n"
        "1. **只能从下面给出的候选模板里选一个引导用户对齐**，不要发明新场景\n"
        "2. 如果候选都不像，明确告诉用户「我们的库里似乎没有匹配的模板」，并问是否要贡献新模板\n"
        "3. 一次只问一个最关键的缺失参数（信号名 / 状态列表 / 位宽等），不要一口气问 5 个\n"
        "4. 不要替用户编造他没说过的信号名或状态名——所有具体名字必须来自用户输入\n\n"
        "### 输出格式（必须严格遵守）\n"
        "你的每次回复**末尾**必须包含一段：\n"
        "<<intent>>累计到目前的标准化意图<<end>>\n"
        "如果用户信息还不够，<<intent>>...<<end>> 段就放当前最准确的近似（可以包含 ?? 表示缺失字段）。\n"
        "前端会解析这一段做「试运行」按钮的 prefill。\n\n"
        f"{accumulated_block}"
        "### 当前可对齐候选\n"
        f"{candidates_block}\n"
    )


def _format_params(template) -> str:
    """从 Template ORM 对象抽取必填参数列表的可读描述。"""
    if not template or not hasattr(template, "parameters"):
        return "(无参数)"
    params = template.parameters or []
    required = [p for p in params if p.get("required")]
    if not required:
        return "(无必填参数)"
    return "、".join(
        f"{p.get('name')}（{p.get('description', '')}）" if p.get("description")
        else p.get("name", "")
        for p in required
    )


def _extract_intent(assistant_reply: str) -> tuple[str, str]:
    """从 LLM 回复抽 <<intent>>...<<end>> 段。返回 (人话部分, 累计意图)。

    P1-8：多对 tag 时取**最后一对**（最新累计），并把所有 tag 段从 human_part 剥离干净。
    LLM 不遵守格式时兜底：返回 (原文, "")。
    """
    matches = list(_INTENT_TAG_RE.finditer(assistant_reply))
    if not matches:
        return assistant_reply.strip(), ""
    # 取最后一对作为最新累计意图
    intent = matches[-1].group(1).strip()
    # 剥离所有 tag 段——避免多对 tag 残留污染 human_part
    human_part = _INTENT_TAG_RE.sub("", assistant_reply).strip()
    return human_part, intent


async def run_one_turn(
    session: IntentBuilderSession,
    user_message: str,
    db: AsyncSession,
    llm: LLMClient,
) -> TurnResult:
    """单轮对话：(a) 加 user msg → (b) 检索 RAG → (c) 注入 prompt → (d) 调 LLM → (e) 抽 intent → (f) 计算 suggest_contribute。

    所有 session 状态在内存里修改；调用方负责持久化（save_session）。

    P1-7：异常时 user_message 不丢——LLM 失败抛出前先回滚 messages 列表上刚 append 的 user
    项，让调用方持久化能拿到"未经污染"的 session 状态。前端 retry 时重发 user_message 即可，
    并且 session 状态与磁盘一致，不会出现"前端以为发出去了但 server 没记录"的不一致。
    """
    # P1-7：在改 session 前 snapshot 所有可变字段，异常时恢复——比逐字段 pop 稳。
    _snapshot = {
        "messages_len": len(session.messages),
        "rag_score_history_len": len(session.rag_score_history),
        "rag_candidates_empty_count": session.rag_candidates_empty_count,
        "accumulated_intent": session.accumulated_intent,
        "turn_count": session.turn_count,
    }

    # (a) user message 加入 history
    session.messages.append({"role": "user", "content": user_message})

    try:
        # (b) 跑 RAG——用最新累计 intent 做 query，没有的话用本轮 user_message
        query_text = session.accumulated_intent or user_message
        rag_candidates_raw = await rag_retrieve(query_text, db, code_type=session.code_type)
        rag_candidates = rag_candidates_raw[:_TOP_K_PER_TURN]
        # P2-21：区分"RAG 完全没返"(empty_count++) 与"返了但分低"(score < 0.5)。
        # 库空/Qdrant 异常时 rag_candidates 是空 list；语义低匹配时是非空 list 但 score 低。
        if not rag_candidates:
            session.rag_candidates_empty_count += 1
            top1_score = 0.0
        else:
            session.rag_candidates_empty_count = 0  # 一旦有候选就清零累计
            top1_score = rag_candidates[0]["score"]
        session.rag_score_history.append(top1_score)

        # (c) 构建 system prompt（每轮都重新构）；带上轮 accumulated_intent，因为 P1-11 已经
        # 把 history 里的 <<intent>>...<<end>> 剥掉，LLM 自身看不到上轮累计
        system_prompt = _build_system_prompt(
            session.code_type, rag_candidates, session.accumulated_intent,
        )
        # messages 给 LLM 时，system 总放最前面（之前的 system 会被这条覆盖）
        messages_for_llm = [{"role": "system", "content": system_prompt}] + [
            m for m in session.messages if m.get("role") != "system"
        ]

        # (d) 调 LLM
        assistant_raw = await llm.chat(messages_for_llm, max_tokens=1024)
    except Exception:
        # P1-7：从 snapshot 恢复所有 session 状态——异常路径下 session 内存版与持久化版对齐
        del session.messages[_snapshot["messages_len"]:]
        del session.rag_score_history[_snapshot["rag_score_history_len"]:]
        session.rag_candidates_empty_count = _snapshot["rag_candidates_empty_count"]
        session.accumulated_intent = _snapshot["accumulated_intent"]
        session.turn_count = _snapshot["turn_count"]
        raise

    # (e) 抽 intent 段
    human_part, intent = _extract_intent(assistant_raw)
    if intent:
        session.accumulated_intent = intent

    # P1-11：history 只存 human_part（剥去 <<intent>>...<<end>> 段），防 self-poisoning ——
    # 否则下轮 LLM 看到自己上轮的标签格式，会循环复制 / 改写累计意图导致语义漂移。
    # accumulated_intent 单独维护，下轮在 system prompt 里以"当前累计意图"形式重新注入。
    session.messages.append({"role": "assistant", "content": human_part})
    # P2-18：turn_count 持久化字段，每轮 +1
    session.turn_count += 1

    # (f) suggest_contribute：触发条件二选一（P2-21 区分空 vs 低）：
    #  - 连续 N 轮 RAG 都返空（库空 / 基础设施异常 / 真的没匹配）
    #  - OR 连续 N 轮 top-1 都 < threshold（库非空但语义低匹配）
    # 两种情况都需要引导用户贡献新模板。
    suggest_contribute = (
        session.rag_candidates_empty_count >= _SUGGEST_CONTRIBUTE_AFTER_TURNS
        or (
            len(session.rag_score_history) >= _SUGGEST_CONTRIBUTE_AFTER_TURNS
            and all(
                s < _RAG_GROUNDING_THRESHOLD
                for s in session.rag_score_history[-_SUGGEST_CONTRIBUTE_AFTER_TURNS:]
            )
        )
    )

    return TurnResult(
        assistant_message=human_part,
        accumulated_intent=session.accumulated_intent,
        rag_candidates=[
            {
                "template_id": c["template_id"],
                "name": c["name"],
                "description": c["description"],
                "score": c["score"],
            }
            for c in rag_candidates
        ],
        suggest_contribute=suggest_contribute,
        turn_count=session.turn_count,
    )
