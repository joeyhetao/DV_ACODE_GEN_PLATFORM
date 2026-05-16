"""v3.0 IntentBuilder Redis session 存储。

设计：
- Key: `intent_builder_session:{user_id}:{session_id}`，按用户隔离，未登录禁用
- Value: JSON 序列化的 IntentBuilderSession dataclass（messages + metadata）
- TTL: 24 小时（PRD §3.8.2 决策）——多轮对话本质 ephemeral，超时即删
- session_id 由客户端生成（uuid4），后端只 ownership-check 不分配；首轮空字符串触发后端 mint

不写 PG：会话本质短期，PG 会污染表。若未来产品需要"恢复 N 天前的会话"再补 PG。
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from app.core.cache import get_redis


_TTL_SECONDS = 24 * 60 * 60
_KEY_PREFIX = "intent_builder_session"

# P2-19：session schema 演化版本。每次 dataclass 字段加减都 bump 这个数字。
# load_session 读到不匹配版本时丢弃旧 session 让前端 mint 新 id 重开。
SESSION_SCHEMA_VERSION = 1


@dataclass
class IntentBuilderSession:
    """多轮对话会话状态。messages 与 OpenAI / Anthropic SDK 格式兼容。"""
    session_id: str
    user_id: str
    code_type: str                              # 会话锁定的 code_type（不允许中途切）
    messages: list[dict] = field(default_factory=list)
    # messages[i] = {"role": "system"|"user"|"assistant", "content": "..."}
    # 不写 RAG snapshot 到 message 本体（避免膨胀 LLM context；保存到 metadata 调试用）
    accumulated_intent: str = ""                # 从 assistant 回复 <<intent>>...<<end>> 抽出
    rag_score_history: list[float] = field(default_factory=list)
    # 每轮 RAG top-1 score——用于判定 suggest_contribute（5 轮都 <0.5 → True）
    rag_candidates_empty_count: int = 0
    # P2-21：连续 N 轮 RAG 返**空列表**的计数，区分"库被 flush"vs"top1 低分"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # P2-18：turn_count 持久化字段——每轮 LLM 调用后 +1，比动态 sum() 更稳（防 history
    # 被剥过 assistant 段后计数错位）
    turn_count: int = 0
    schema_version: int = SESSION_SCHEMA_VERSION


def _key(user_id: str, session_id: str) -> str:
    return f"{_KEY_PREFIX}:{user_id}:{session_id}"


def mint_session_id() -> str:
    """后端 mint 新 session_id（首轮 user 传空时用）。客户端续轮自带 id 时不调。"""
    return str(uuid.uuid4())


async def load_session(user_id: str, session_id: str) -> IntentBuilderSession | None:
    """读 session，找不到返 None（前端会判 None 然后让后端 mint 新 id）。

    ownership check 由 key 命名空间天然隔离——别人的 session_id 拼不出本人的 key。

    P1-9：JSON 解析失败 / KeyError 时打 WARN 日志，便于 SRE 排查"用户报告对话历史丢失"。
    """
    if not session_id:
        return None
    redis = get_redis()
    raw = await redis.get(_key(user_id, session_id))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        # P2-19：schema_version 不匹配 → 丢弃旧 session（不写复杂迁移逻辑，让前端 mint 新 id）
        stored_version = data.get("schema_version", 0)
        if stored_version != SESSION_SCHEMA_VERSION:
            print(
                f"[WARN] intent_builder session schema_version mismatch "
                f"(stored={stored_version}, current={SESSION_SCHEMA_VERSION}); discarding",
                flush=True,
            )
            return None
        return IntentBuilderSession(
            session_id=data["session_id"],
            user_id=data["user_id"],
            code_type=data["code_type"],
            messages=data.get("messages", []),
            accumulated_intent=data.get("accumulated_intent", ""),
            rag_score_history=data.get("rag_score_history", []),
            rag_candidates_empty_count=data.get("rag_candidates_empty_count", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            turn_count=data.get("turn_count", 0),
            schema_version=stored_version,
        )
    except (json.JSONDecodeError, KeyError) as e:
        print(
            f"[WARN] intent_builder session corrupt: user_id={user_id} "
            f"session_id={session_id} err={type(e).__name__}: {e}",
            flush=True,
        )
        return None


async def save_session(session: IntentBuilderSession) -> None:
    """写 session，刷新 TTL 24h。每轮对话都调。"""
    session.updated_at = time.time()
    redis = get_redis()
    await redis.set(
        _key(session.user_id, session.session_id),
        json.dumps(asdict(session), ensure_ascii=False),
        ex=_TTL_SECONDS,
    )


async def delete_session(user_id: str, session_id: str) -> None:
    """手动删除 session（用户点"关闭对话"按钮时可调；常规情况靠 24h TTL）。"""
    redis = get_redis()
    await redis.delete(_key(user_id, session_id))


def to_chat_response_messages(session: IntentBuilderSession) -> list[dict[str, Any]]:
    """提取用于 chat response 的 messages 视图（不含 system，前端只渲染 user/assistant 气泡）。"""
    return [m for m in session.messages if m.get("role") in ("user", "assistant")]
