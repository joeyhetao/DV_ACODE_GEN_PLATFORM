"""v3.0 IntentBuilder 多轮对话单测。

锁定：
- 首轮无 session_id → 后端 mint 新 id；续轮 session_id 续 history
- RAG top-3 candidates 注入 system prompt
- LLM 回复里 <<intent>>...<<end>> 段被正确抽取，剥离后才作为 assistant_message
- LLM 不输出 <<intent>>...<<end>> 时 accumulated_intent 保持原值
- suggest_contribute 在 5 轮 top-1 < 0.5 时触发
- code_type 锁定（session 一旦创建不允许切）

跑法：docker compose exec backend pytest tests/test_intent_builder_chat.py -v
"""
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import ExitStack

import pytest

from app.services.intent.conversation import (
    _build_system_prompt,
    _extract_intent,
    run_one_turn,
    _SUGGEST_CONTRIBUTE_AFTER_TURNS,
)
from app.services.intent.session import (
    IntentBuilderSession,
    mint_session_id,
)


# ── _extract_intent 纯函数单测 ────────────────────────────────────────────

def test_extract_intent_with_tag():
    """LLM 守规矩输出 <<intent>>...<<end>> → 抽出来。"""
    reply = "请告诉我状态信号名。<<intent>>对 FSM 做转换覆盖率（信号名 ??）<<end>>"
    human, intent = _extract_intent(reply)
    assert human == "请告诉我状态信号名。"
    assert intent == "对 FSM 做转换覆盖率（信号名 ??）"


def test_extract_intent_without_tag_returns_empty_intent():
    """LLM 没守规矩 → accumulated_intent 留空，原文当 human 部分。"""
    reply = "请告诉我状态信号名。"
    human, intent = _extract_intent(reply)
    assert human == "请告诉我状态信号名。"
    assert intent == ""


def test_extract_intent_multiline():
    """<<intent>>...<<end>> 跨行也要能抽。"""
    reply = "好的，下面是标准化意图：\n\n<<intent>>\n对 FSM 做转换覆盖率\n<<end>>\n\n（继续等用户输入）"
    human, intent = _extract_intent(reply)
    assert intent == "对 FSM 做转换覆盖率"
    assert "<<intent>>" not in human
    assert "<<end>>" not in human


# ── _build_system_prompt 单测 ─────────────────────────────────────────────

def test_build_system_prompt_includes_rag_candidates():
    """RAG top-3 候选必须出现在 prompt 里。"""
    candidates = [
        {
            "template_id": "cov_x",
            "name": "覆盖率组 X",
            "description": "测试用",
            "score": 0.85,
            "template": MagicMock(parameters=[
                {"name": "signal", "required": True, "description": "信号名"},
            ]),
        },
    ]
    prompt = _build_system_prompt("coverage", candidates)
    assert "cov_x" in prompt
    assert "覆盖率组 X" in prompt
    assert "signal" in prompt
    assert "coverage" in prompt
    # 规则段也存在
    assert "不要发明新场景" in prompt
    assert "<<intent>>" in prompt


def test_build_system_prompt_no_candidates_says_empty():
    """RAG 空时 prompt 明示"暂无候选"。"""
    prompt = _build_system_prompt("assertion", [])
    assert "暂无候选" in prompt or "没有" in prompt or "库里可能没有" in prompt


# ── run_one_turn 集成单测 ────────────────────────────────────────────────

def _make_fake_template(template_id, name, params):
    tmpl = MagicMock()
    tmpl.id = template_id
    tmpl.name = name
    tmpl.parameters = params
    return tmpl


@pytest.mark.asyncio
async def test_run_one_turn_appends_user_and_assistant_to_history():
    """run_one_turn 把 user msg 加入 history 后再调 LLM，最后 assistant raw 也写回。"""
    session = IntentBuilderSession(
        session_id="s1", user_id="u1", code_type="coverage",
    )
    fake_rag = [
        {
            "template_id": "cov_x",
            "name": "X",
            "description": "x desc",
            "score": 0.8,
            "template": _make_fake_template("cov_x", "X", [{"name": "signal", "required": True}]),
        },
    ]
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="我需要信号名。\n<<intent>>对 X 做覆盖率<<end>>")
    with patch("app.services.intent.conversation.rag_retrieve", new=AsyncMock(return_value=fake_rag)):
        result = await run_one_turn(session, "做覆盖率", db=MagicMock(), llm=fake_llm)

    # history 含 user + assistant 两条
    assert len(session.messages) == 2
    assert session.messages[0] == {"role": "user", "content": "做覆盖率"}
    assert session.messages[1]["role"] == "assistant"
    # accumulated_intent 抽出
    assert session.accumulated_intent == "对 X 做覆盖率"
    # rag_score_history 加了 1 条
    assert session.rag_score_history == [0.8]
    # response 数据正确
    assert result.assistant_message == "我需要信号名。"
    assert result.accumulated_intent == "对 X 做覆盖率"
    assert len(result.rag_candidates) == 1
    assert result.rag_candidates[0]["template_id"] == "cov_x"
    assert result.suggest_contribute is False
    assert result.turn_count == 1


@pytest.mark.asyncio
async def test_run_one_turn_keeps_accumulated_intent_when_llm_skips_tag():
    """LLM 第二轮没输出 <<intent>>...<<end>> 段时，accumulated_intent 沿用上轮值不被清空。"""
    session = IntentBuilderSession(
        session_id="s2", user_id="u1", code_type="coverage",
        accumulated_intent="保留上轮的意图",
    )
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="（没输出 intent 段的回复）")
    with patch("app.services.intent.conversation.rag_retrieve", new=AsyncMock(return_value=[])):
        result = await run_one_turn(session, "继续", db=MagicMock(), llm=fake_llm)
    assert session.accumulated_intent == "保留上轮的意图"
    assert result.accumulated_intent == "保留上轮的意图"


@pytest.mark.asyncio
async def test_run_one_turn_suggest_contribute_after_5_low_rag_turns():
    """连续 N 轮 RAG top-1 < 0.5 → suggest_contribute=True。"""
    session = IntentBuilderSession(
        session_id="s3", user_id="u1", code_type="coverage",
        rag_score_history=[0.3, 0.4, 0.45, 0.2],  # 已有 4 轮低分
    )
    fake_rag = [
        {
            "template_id": "cov_low",
            "name": "Low",
            "description": "",
            "score": 0.3,
            "template": _make_fake_template("cov_low", "Low", []),
        },
    ]
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="<<intent>>x<<end>>")
    with patch("app.services.intent.conversation.rag_retrieve", new=AsyncMock(return_value=fake_rag)):
        result = await run_one_turn(session, "x", db=MagicMock(), llm=fake_llm)
    # 第 5 轮加上去后所有 5 轮都 <0.5 → 触发
    assert result.suggest_contribute is True


@pytest.mark.asyncio
async def test_run_one_turn_passes_rag_candidates_into_system_prompt():
    """验证 LLM.chat 被调用时，messages 里 system content 含 RAG candidate 信息。"""
    session = IntentBuilderSession(
        session_id="s4", user_id="u1", code_type="assertion",
    )
    fake_rag = [
        {
            "template_id": "sva_handshake_timeout_v1",
            "name": "握手超时",
            "description": "valid-ready 超时检测",
            "score": 0.85,
            "template": _make_fake_template(
                "sva_handshake_timeout_v1", "握手超时",
                [{"name": "valid", "required": True, "description": "valid 信号"}],
            ),
        },
    ]
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="<<intent>>x<<end>>")
    with patch("app.services.intent.conversation.rag_retrieve", new=AsyncMock(return_value=fake_rag)):
        await run_one_turn(session, "握手", db=MagicMock(), llm=fake_llm)

    call_args = fake_llm.chat.call_args
    messages = call_args[0][0] if call_args[0] else call_args.kwargs["messages"]
    system = next(m for m in messages if m["role"] == "system")
    assert "sva_handshake_timeout_v1" in system["content"]
    assert "握手超时" in system["content"]
    assert "valid" in system["content"]


# ── session 工具单测 ──────────────────────────────────────────────────────

def test_mint_session_id_returns_uuid_string():
    """mint_session_id 应返合法 uuid4 字符串。"""
    sid = mint_session_id()
    assert isinstance(sid, str)
    assert len(sid) == 36  # standard uuid4 dashed form


def test_session_turn_count_persisted_field():
    """P2-18：turn_count 是持久化字段，run_one_turn 每轮 +1，不再动态从 messages 计算。"""
    s = IntentBuilderSession(session_id="x", user_id="u", code_type="coverage")
    assert s.turn_count == 0
    s.turn_count = 5
    assert s.turn_count == 5


# ── P1-7 / P1-8 / P1-11 回归 ─────────────────────────────────────────────

def test_extract_intent_multiple_tags_takes_last():
    """P1-8：LLM 输出多对 <<intent>>...<<end>> 时取**最后一对**（最新累计）。"""
    reply = (
        "第一轮思考：<<intent>>对 FSM 做覆盖率<<end>> "
        "再追加：<<intent>>对 FSM 做转换覆盖率，状态 IDLE,RUN,DONE<<end>>"
    )
    human, intent = _extract_intent(reply)
    assert intent == "对 FSM 做转换覆盖率，状态 IDLE,RUN,DONE"
    # 所有 tag 段都被剥离
    assert "<<intent>>" not in human
    assert "<<end>>" not in human


@pytest.mark.asyncio
async def test_run_one_turn_strips_intent_tag_from_assistant_history():
    """P1-11：assistant 写入 history 时只存 human_part，剥去 <<intent>>...<<end>> 段。
    防 self-poisoning：LLM 下轮看不到自己上轮的 tag 格式。"""
    session = IntentBuilderSession(session_id="s11", user_id="u1", code_type="coverage")
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(return_value="请补充状态名。\n<<intent>>对 FSM 做覆盖率<<end>>")
    with patch("app.services.intent.conversation.rag_retrieve", new=AsyncMock(return_value=[])):
        await run_one_turn(session, "FSM 覆盖率", db=MagicMock(), llm=fake_llm)
    # accumulated_intent 抽出
    assert session.accumulated_intent == "对 FSM 做覆盖率"
    # history 里的 assistant message **不含** <<intent>>...<<end>> 段
    assistant_msg = next(m for m in session.messages if m["role"] == "assistant")
    assert "<<intent>>" not in assistant_msg["content"]
    assert "<<end>>" not in assistant_msg["content"]
    assert "请补充状态名" in assistant_msg["content"]


@pytest.mark.asyncio
async def test_run_one_turn_rollback_on_llm_failure():
    """P1-7：LLM 调用失败时，session.messages 与 rag_score_history 应回滚干净。

    场景：用户发 user_message，RAG 跑了，LLM 抛异常 → session 内存版应该等于 RAG 跑之前
    （rolled back），否则 save_session 持久化的版本含半成品，下次 load 会污染。
    """
    session = IntentBuilderSession(session_id="s7", user_id="u1", code_type="coverage")
    before_messages_count = len(session.messages)
    before_rag_history = list(session.rag_score_history)

    fake_rag = [{"template_id": "x", "name": "X", "description": "", "score": 0.5,
                 "template": MagicMock(parameters=[])}]
    fake_llm = MagicMock()
    fake_llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
    with patch("app.services.intent.conversation.rag_retrieve", new=AsyncMock(return_value=fake_rag)):
        with pytest.raises(RuntimeError):
            await run_one_turn(session, "test msg", db=MagicMock(), llm=fake_llm)

    # 回滚：messages 与 rag_score_history 都应回到调用前
    assert len(session.messages) == before_messages_count
    assert session.rag_score_history == before_rag_history


def test_build_system_prompt_injects_accumulated_intent():
    """P1-11 配套：assistant history 剥了 <<intent>> 段后，system prompt 必须把
    accumulated_intent 显式注入，让 LLM 下轮能继续累加而非从头猜。"""
    prompt = _build_system_prompt(
        "coverage",
        [],
        accumulated_intent="对 FSM 做转换覆盖率（signal=??）",
    )
    assert "对 FSM 做转换覆盖率（signal=??）" in prompt
    assert "上轮累计意图" in prompt or "accumulated" in prompt.lower()
