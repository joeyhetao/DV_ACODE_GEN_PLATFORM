from __future__ import annotations
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, Date

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.user import User
from app.models.audit_log import AdminAuditLog
from app.models.generation_record import GenerationRecord
from app.schemas.user import UserOut, UserRoleUpdate
from app.services.platform.backup_service import create_pg_backup
from app.core.config import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    stmt = select(User).order_by(User.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.role not in ("user", "lib_admin", "super_admin"):
        raise HTTPException(status_code=400, detail="无效的角色")
    user.role = payload.role
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}/activate")
async def set_user_active(
    user_id: str,
    active: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.is_active = active
    await db.commit()
    return {"user_id": user_id, "is_active": active}


@router.get("/audit-logs")
async def list_audit_logs(
    action: str | None = None,
    operator_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    stmt = select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    if operator_id:
        stmt = stmt.where(AdminAuditLog.operator_id == operator_id)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "operator_id": log.operator_id,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    total_generations = (await db.execute(select(func.count(GenerationRecord.id)))).scalar()
    cache_hits = (
        await db.execute(
            select(func.count(GenerationRecord.id)).where(GenerationRecord.cache_hit == True)
        )
    ).scalar()
    return {
        "total_users": total_users,
        "total_generations": total_generations,
        "cache_hit_rate": round(cache_hits / total_generations, 4) if total_generations else 0.0,
    }


@router.post("/backup")
async def trigger_backup(
    current_user: User = Depends(require_role("super_admin")),
):
    settings = get_settings()
    out_file = await create_pg_backup(settings.database_url)
    return {"status": "ok", "file": str(out_file)}


# ── L4 analytics ──────────────────────────────────────────────────────
# 4 个端点全部要求 lib_admin / super_admin；时间窗 days 默认 7、上限 90，
# 防止 admin 误传巨大窗口扫全表。数据源约定见 spec §2/§4。

def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


_ALLOWED_GENERATION_MODES = {"rag", "llm_direct"}


def _validate_generation_mode_filter(generation_mode: str | None) -> str | None:
    """Query 参数 generation_mode 校验。None / 空串 → 不过滤；其他值校验白名单。

    detail 用结构化 dict（与项目其他错误响应风格一致），让前端能按 detail.type
    精准识别这类参数错误。
    """
    if generation_mode is None or generation_mode == "":
        return None
    if generation_mode not in _ALLOWED_GENERATION_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_generation_mode",
                "message": (
                    f"无效的 generation_mode '{generation_mode}'，"
                    "合法值：rag / llm_direct"
                ),
            },
        )
    return generation_mode


@router.get("/analytics/feedback-summary")
async def analytics_feedback_summary(
    days: int = Query(7, ge=1, le=90),
    generation_mode: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    """KPI：总生成数、反馈率、差评率、NoMatchingTemplate 率。

    无数据时各率返 0.0，不报 500。`bad_rate` 分母用 total_feedbacks，
    避免没人评分时把差评率写成 0/0 → NaN。

    FEAT-11 Stage 2：generation_mode 可选 'rag' / 'llm_direct'，omit = 全部。
    no_match_count 仅对 'rag' 路径有意义（llm_direct 不经过 5 道闸），过滤
    'llm_direct' 时本字段恒 0；分子分母都在同一 mode 内统计，比率仍有意义。
    """
    since = _since(days)
    mode_filter = _validate_generation_mode_filter(generation_mode)

    def _apply_mode(stmt):
        if mode_filter is not None:
            return stmt.where(GenerationRecord.generation_mode == mode_filter)
        return stmt

    total_generations = (await db.execute(
        _apply_mode(
            select(func.count(GenerationRecord.id)).where(GenerationRecord.created_at >= since)
        )
    )).scalar() or 0
    total_feedbacks = (await db.execute(
        _apply_mode(
            select(func.count(GenerationRecord.id)).where(
                GenerationRecord.created_at >= since,
                GenerationRecord.feedback_rating.isnot(None),
            )
        )
    )).scalar() or 0
    bad_feedbacks = (await db.execute(
        _apply_mode(
            select(func.count(GenerationRecord.id)).where(
                GenerationRecord.created_at >= since,
                GenerationRecord.feedback_rating == 3,
            )
        )
    )).scalar() or 0
    no_match_count = (await db.execute(
        _apply_mode(
            select(func.count(GenerationRecord.id)).where(
                GenerationRecord.created_at >= since,
                GenerationRecord.gate_error_type == "no_matching_template",
            )
        )
    )).scalar() or 0
    return {
        "days": days,
        "generation_mode": mode_filter,
        "total_generations": total_generations,
        "total_feedbacks": total_feedbacks,
        "feedback_rate": round(total_feedbacks / total_generations, 4) if total_generations else 0.0,
        "bad_rate": round(bad_feedbacks / total_feedbacks, 4) if total_feedbacks else 0.0,
        "no_match_rate": round(no_match_count / total_generations, 4) if total_generations else 0.0,
    }


@router.get("/analytics/template-issues")
async def analytics_template_issues(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=100),
    generation_mode: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    """差评 template top-N：每行 {template_id, bad_count, total_count, bad_rate}。

    数据源：window 内有反馈的记录；按 bad_rate 降序，tie-break by bad_count 降序。
    空数据返 []。

    FEAT-11 Stage 2：generation_mode 可选 'rag' / 'llm_direct'，omit = 全部。
    - 'rag'：template_id 必非 NULL，按 template_id 分组（保持原行为）。
    - 'llm_direct'：template_id 必为 NULL（freeform 不走模板）→ 聚合为单行
      template_id="__llm_direct__"，让前端能显示差评量；
      不再要求 IS NOT NULL 否则永远返空。
    - 不过滤（默认）：合并两路；NULL 行同样归入 "__llm_direct__"，让 admin
      一眼看出哪些差评来自 freeform。
    """
    since = _since(days)
    mode_filter = _validate_generation_mode_filter(generation_mode)

    where_clauses = [
        GenerationRecord.created_at >= since,
        GenerationRecord.feedback_rating.isnot(None),
    ]
    if mode_filter == "rag":
        where_clauses.append(GenerationRecord.template_id.isnot(None))
    if mode_filter is not None:
        where_clauses.append(GenerationRecord.generation_mode == mode_filter)

    stmt = (
        select(
            GenerationRecord.template_id.label("template_id"),
            func.count(GenerationRecord.id).label("total_count"),
            func.sum(
                case((GenerationRecord.feedback_rating == 3, 1), else_=0)
            ).label("bad_count"),
        )
        .where(*where_clauses)
        .group_by(GenerationRecord.template_id)
    )
    rows = (await db.execute(stmt)).all()
    items = []
    for r in rows:
        total = int(r.total_count or 0)
        bad = int(r.bad_count or 0)
        # template_id IS NULL → llm_direct 记录；放统一桶 "__llm_direct__"
        tid = r.template_id if r.template_id is not None else "__llm_direct__"
        items.append({
            "template_id": tid,
            "total_count": total,
            "bad_count": bad,
            "bad_rate": round(bad / total, 4) if total else 0.0,
        })
    items.sort(key=lambda x: (x["bad_rate"], x["bad_count"]), reverse=True)
    return items[:limit]


@router.get("/analytics/intent-confusion")
async def analytics_intent_confusion(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    """意图-模板混淆样本：差评 + LLM 选错的聚合。

    数据源：feedback_rating=3 且 template_id != rag_top3[0].template_id；
    expected_template = rag_top3[0].template_id（视 RAG top-1 为期望），
    actual_template = template_id；按 count 降序。
    聚合 key 用 (expected, actual) 二元组——同一对模板间的所有混淆样本归为一类，
    避免拿用户原文当 dict key（脱敏 + 基数爆炸防护）。`intent` 字段仅返代表性
    截断样本（200 字符，最早出现的一条）供 admin 快速识别这是什么验证场景。
    `code_type` 字段从 templates 表 join 出 actual_template 的 code_type，
    让前端"复制为 corpus 条目"能直接拿到正确值，无需 admin 二次核对。
    """
    from app.models.template import Template

    since = _since(days)
    # JSONB 路径访问：rag_top3->0->>'template_id'。SQLite 测试环境用 mock 兜底。
    stmt = (
        select(GenerationRecord.original_intent, GenerationRecord.template_id, GenerationRecord.rag_top3)
        .where(
            GenerationRecord.created_at >= since,
            GenerationRecord.feedback_rating == 3,
            GenerationRecord.template_id.isnot(None),
            GenerationRecord.rag_top3.isnot(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    # Python 侧聚合，避免方言差异。规模 = 7 天差评数，量级小（< 1000）。
    bucket: dict[tuple[str, str], dict] = {}
    for r in rows:
        rag = r.rag_top3 or []
        if not isinstance(rag, list) or not rag:
            continue
        top1 = rag[0]
        if not isinstance(top1, dict):
            continue
        expected = top1.get("template_id")
        if not expected or expected == r.template_id:
            continue
        key = (expected, r.template_id)
        sample_intent = (r.original_intent or "")[:200]
        if key not in bucket:
            bucket[key] = {
                "intent": sample_intent,
                "expected_template": expected,
                "actual_template": r.template_id,
                "code_type": None,
                "count": 0,
            }
        bucket[key]["count"] += 1
    items = sorted(bucket.values(), key=lambda x: x["count"], reverse=True)[:limit]
    # 单次反查 templates 拿 code_type，避免 N+1：只查桶内出现的 template_id 集合。
    if items:
        wanted = {x["actual_template"] for x in items} | {x["expected_template"] for x in items}
        type_map_rows = (await db.execute(
            select(Template.id, Template.code_type).where(Template.id.in_(wanted))
        )).all()
        type_map = {tid: ct for tid, ct in type_map_rows}
        for x in items:
            # 优先用 actual_template 的 code_type；若 actual 已被删除则回落 expected
            x["code_type"] = type_map.get(x["actual_template"]) or type_map.get(x["expected_template"])
    return items


@router.get("/analytics/no-match-rate")
async def analytics_no_match_rate(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    """按天聚合的 no_matching_template 命中率。

    返回 `{date, total, no_match_count, no_match_rate}` 数组；
    不足 days 天时返回实际有数据的天数，不补零行。
    """
    since = _since(days)
    # 用列上的 .cast(Date)（=显式 CAST 表达式），不用 sqlalchemy.cast()。
    # tz-aware DateTime → Date 走 PG 默认 UTC，分桶在 UTC 日界，时区漂移由前端展示决定。
    # 若想按本地时区分桶，应改为 func.date_trunc('day', col AT TIME ZONE 'UTC')。
    day = GenerationRecord.created_at.cast(Date).label("date")
    stmt = (
        select(
            day,
            func.count(GenerationRecord.id).label("total"),
            func.sum(
                case(
                    (GenerationRecord.gate_error_type == "no_matching_template", 1),
                    else_=0,
                )
            ).label("no_match_count"),
        )
        .where(GenerationRecord.created_at >= since)
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).all()
    out = []
    for r in rows:
        total = int(r.total or 0)
        no_match = int(r.no_match_count or 0)
        out.append({
            "date": r.date.isoformat() if hasattr(r.date, "isoformat") else str(r.date),
            "total": total,
            "no_match_count": no_match,
            "no_match_rate": round(no_match / total, 4) if total else 0.0,
        })
    return out
