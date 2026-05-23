from __future__ import annotations
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.cache import get_redis
from app.models.user import User
from app.models.contribution import TemplateContribution
from app.schemas.contribution import (
    ContributionCreate,
    ContributionUpdate,
    ContributionOut,
    ContributionListOut,
    ContributionReviewAction,
    ConflictItem,
    PreApproveAnalysisResult,
)
from app.services.llm.factory import get_default_llm_client
from app.services.platform.contribution_service import (
    approve_contribution,
    reject_contribution,
    request_revision,
)
from app.services.core.dedup import check_name_duplicate, check_semantic_duplicate
from app.services.platform.parameter_extractor import (
    ContributionParseError,
    derive_parameters_from_demo,
    _validate_jinja_rendering,
    _validate_parameter_defs,
)
from app.services.platform.corpus_service import (
    generate_corpus_cases,
    detect_conflicts,
    generate_llm_analysis,
)

_PRE_ANALYSIS_TTL = 60 * 60  # 1h — admin must approve within an hour of running pre-check

router = APIRouter(prefix="/contributions", tags=["contributions"])


@router.post("", response_model=ContributionOut, status_code=201)
async def submit_contribution(
    payload: ContributionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """v3.0：用户只填 4 必填字段（code_type / template_name / description / demo_code），
    后端 LLM 反推 parameter_defs / jinja body / keywords / subcategory / protocol。

    LLM 反推失败 → 422 `contribution_parse_failed`，前端弹"请简化代码示例"提示。
    成功 → status=pending_review 入库，进入审核队列。

    P1-6 dedup：
    - **提交时**：name 精确重名直接 422（用户必须先改名）；语义查重把 top-3 塞 original_row_json
      让审核员看到，不拦提交（审核员有权拍板"是变体还是重复"）。
    - approve 端点：信任审核员已经基于 dedup 信息做了决策，不再重复 dedup。

    P2-14 db session 占用：LLM 反推耗时 5-15s，期间 db connection 被这个请求占。当前实现
    在 LLM 调用之后才 db.add + commit，已经把 PG 持有时间压到最低。**若并发提交频繁**，可
    在 docker-compose 里调大 PG `max_connections` 或 SQLAlchemy `pool_size`。
    """
    # P1-6：name 精确查重——同名 template 已存在则拒
    if await check_name_duplicate(db, payload.template_name):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "contribution_name_duplicate",
                "name": payload.template_name,
                "message": f"模板名「{payload.template_name}」已存在，请换个名字。",
            },
        )

    # v2 兼容：若 caller 显式传了 parameter_defs（如批量导入），跳过 LLM 反推
    if payload.parameter_defs:
        derived_param_defs = payload.parameter_defs
        derived_jinja_body = payload.demo_code
        derived_keywords = payload.keywords or []
        derived_subcategory = payload.subcategory
        derived_protocol = payload.protocol
    else:
        # v3.0 主路径：LLM 反推
        llm = await get_default_llm_client(db)
        try:
            extracted = await derive_parameters_from_demo(
                demo_code=payload.demo_code,
                description=payload.description,
                code_type=payload.code_type,
                llm=llm,
            )
        except ContributionParseError as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "type": "contribution_parse_failed",
                    "stage": e.stage,
                    "reason": e.reason,
                    "message": (
                        "AI 解析代码示例失败，请简化代码示例 / 完善场景描述后重新提交。"
                        f"（失败阶段：{e.stage}）"
                    ),
                },
            )
        derived_param_defs = extracted.parameter_defs
        derived_jinja_body = extracted.jinja_body
        derived_keywords = extracted.keywords
        derived_subcategory = extracted.subcategory or payload.subcategory
        derived_protocol = extracted.protocol or payload.protocol

    contribution = TemplateContribution(
        contributor_id=current_user.id,
        code_type=payload.code_type,
        original_intent=payload.original_intent or payload.description,
        original_row_json=payload.original_row_json,
        template_name=payload.template_name,
        subcategory=derived_subcategory,
        protocol=derived_protocol,
        # demo_code 字段存 LLM 反推后的 Jinja2 化模板（审核员可在三栏面板里改）
        # 用户原始代码可以从 description 字段或单独字段保留——v3.0 暂存进 original_row_json["user_demo"]
        demo_code=derived_jinja_body,
        description=payload.description,
        keywords=derived_keywords,
        parameter_defs=derived_param_defs,
        # Model Enum 是 (pending_review, under_review, needs_revision, approved, rejected)；
        # **必须**写 "pending_review"，不能写 "pending"（PG 22023 invalid_input_value）。
        status="pending_review",
    )
    # 留个 user_demo 副本在 original_row_json 里——审核员对比用
    if not contribution.original_row_json:
        contribution.original_row_json = {}
    contribution.original_row_json["user_demo"] = payload.demo_code

    # P1-6：语义查重——把 top-3 相似已入库模板塞 original_row_json["similar_templates"]，
    # 让审核员在三栏面板看到，不拦提交（审核员有最终判断权）。
    # check_semantic_duplicate 失败（如 Qdrant 暂时不可达）时不阻塞提交，仅日志告警。
    try:
        similar = await check_semantic_duplicate(
            description=payload.description,
            name=payload.template_name,
            tags=None,
            keywords=derived_keywords,
            top_k=3,
        )
        if similar:
            contribution.original_row_json["similar_templates"] = similar
    except Exception as e:
        print(f"[WARN] dedup check skipped due to {type(e).__name__}: {e}", flush=True)

    db.add(contribution)
    await db.commit()
    await db.refresh(contribution)
    return contribution


@router.get("/my", response_model=list[ContributionListOut])
async def my_contributions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(TemplateContribution)
        .where(TemplateContribution.contributor_id == current_user.id)
        .order_by(TemplateContribution.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# Admin routes must be registered before /{contribution_id} to avoid path shadowing
@router.get("/admin/all", response_model=list[ContributionListOut])
async def admin_list_contributions(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    stmt = select(TemplateContribution).order_by(TemplateContribution.created_at.desc())
    if status:
        stmt = stmt.where(TemplateContribution.status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{contribution_id}", response_model=ContributionOut)
async def get_contribution(
    contribution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if (
        contribution.contributor_id != current_user.id
        and current_user.role not in ("lib_admin", "super_admin")
    ):
        raise HTTPException(status_code=403, detail="无权访问")
    return contribution


@router.patch("/{contribution_id}", response_model=ContributionOut)
async def update_contribution(
    contribution_id: str,
    payload: ContributionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """v3.0：贡献人 / 审核员都可改，权限按身份分。

    - 贡献人：仅 status ∈ {pending_review, needs_revision} 可改；改后状态归 pending_review 重新走审核
    - 审核员（lib_admin/super_admin）：任意 status 都可改（三栏编辑场景），改后**不**重置 status
      （让审核员可以"先编辑再批准"或"先编辑再请求修改"）
    """
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")

    is_admin = current_user.role in ("lib_admin", "super_admin")
    is_owner = contribution.contributor_id == current_user.id
    if not (is_admin or is_owner):
        raise HTTPException(status_code=403, detail="无权修改此贡献")
    if is_owner and not is_admin:
        if contribution.status not in ("pending_review", "needs_revision"):
            raise HTTPException(status_code=400, detail="该状态下不允许修改")

    update_dict = payload.model_dump(exclude_none=True)
    for field, value in update_dict.items():
        setattr(contribution, field, value)

    # P0-3：若 demo_code 或 parameter_defs 被改，commit 前必须二次跑校验——防审核员
    # 手改后引用了不存在的参数、或推入 SSTI payload 静默入库。
    # 用 post-update 后的 contribution.demo_code / parameter_defs 跑校验。
    touched_jinja_critical = "demo_code" in update_dict or "parameter_defs" in update_dict
    if touched_jinja_critical:
        try:
            _validate_parameter_defs(contribution.parameter_defs or [])
            _validate_jinja_rendering(
                contribution.demo_code or "",
                contribution.parameter_defs or [],
            )
        except ContributionParseError as e:
            await db.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "type": "contribution_parse_failed",
                    "stage": e.stage,
                    "reason": e.reason,
                    "message": f"编辑后的模板未通过校验（{e.stage}），请修正后重试。",
                },
            )

    from datetime import datetime, timezone
    contribution.updated_at = datetime.now(timezone.utc)
    if not is_admin:
        # 贡献人自己改完重新进队列待审；审核员改完不重置状态（保持当前流程）
        contribution.status = "pending_review"
    await db.commit()
    await db.refresh(contribution)
    return contribution


@router.post("/{contribution_id}/pre-approve-analysis", response_model=PreApproveAnalysisResult)
async def pre_approve_analysis(
    contribution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    """FEAT-4 Layer 3b：管理员点"批准"时先跑此端点做冲突预检。

    步骤：
    1. 检测新模板是否会抢走现有语料的正确命中（embedding 余弦 + RAG top-1 比较）
    2. LLM 生成新语料用例（3 条命中新模板 + 最近邻各 1 条）
    3. 若有冲突，LLM 用业务语言分析根因并给出修改建议
    4. 所有数据存入 Redis（TTL 1h），approve 端点读取并写 DB

    此端点是非破坏性的（不修改 contribution 状态）。
    """
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")

    llm = await get_default_llm_client(db)

    # 步骤 1：冲突检测
    conflicts_raw = await detect_conflicts(
        new_template_name=contribution.template_name,
        new_template_description=contribution.description,
        new_template_keywords=contribution.keywords,
        db=db,
    )

    # 步骤 2：LLM 生成语料（复用 endpoint 的 db，不在 service 内开新 session）
    generated = await generate_corpus_cases(
        contribution_id=contribution.id,
        contribution_name=contribution.template_name,
        contribution_description=contribution.description,
        contribution_code_type=contribution.code_type,
        keywords=contribution.keywords,
        tags=None,
        db=db,
        llm=llm,
    )

    # 步骤 3：有冲突时 LLM 分析
    analysis = None
    if conflicts_raw:
        analysis = await generate_llm_analysis(
            new_template_name=contribution.template_name,
            new_template_description=contribution.description,
            conflicts=conflicts_raw,
            llm=llm,
        )

    # 步骤 4：存入 Redis（供 approve 端点读取，TTL 1h）
    analysis_id = str(uuid.uuid4())
    redis = get_redis()
    payload = {
        "contribution_id": contribution_id,
        "corpus_cases": [
            {
                "intent": c.intent,
                "code_type": c.code_type,
                "expected_template_id": c.expected_template_id,
                "note": c.note,
                "source": c.source,
            }
            for c in generated.all_cases
        ],
    }
    await redis.set(f"pre_analysis:{analysis_id}", json.dumps(payload), ex=_PRE_ANALYSIS_TTL)

    # 构造响应（管理员视图：不暴露分数，只暴露业务描述）
    conflict_items = [
        ConflictItem(
            intent=c.intent,
            current_template_name=c.current_template_name,
            explanation=(
                f"此意图当前命中「{c.current_template_name}」，"
                "新模板的语义与该意图高度相似，可能导致选择反转。"
            ),
        )
        for c in conflicts_raw
    ]

    return PreApproveAnalysisResult(
        has_conflicts=bool(conflicts_raw),
        conflicts=conflict_items,
        new_corpus_preview=[c.intent for c in generated.for_new_template],
        llm_analysis=analysis.root_cause if analysis else None,
        recommendation_field=analysis.recommendation_field if analysis else None,
        recommendation_text=analysis.recommendation_text if analysis else None,
        confidence=analysis.confidence if analysis else None,
        analysis_id=analysis_id,
    )


@router.post("/{contribution_id}/approve")
async def admin_approve(
    contribution_id: str,
    analysis_id: str | None = Query(None, description="pre-approve-analysis 返回的 analysis_id，有则写入语料"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.status != "pending_review":
        raise HTTPException(status_code=400, detail="只能审批 pending_review 状态的贡献")

    from app.api.v1.templates import _create_template_from_contribution

    promoted_id = await approve_contribution(
        contribution=contribution,
        reviewer_id=current_user.id,
        db=db,
        template_create_fn=_create_template_from_contribution,
    )
    await db.commit()

    # FEAT-4：将预生成的语料写入 DB（analysis_id 有且 Redis 仍有效）
    # promoted_id 为 None 时（理论上 approve_contribution 已抛错，但兜底防御）
    # 跳过语料写入，避免 FK 违反静默被吞。
    if analysis_id and promoted_id:
        try:
            redis = get_redis()
            raw = await redis.get(f"pre_analysis:{analysis_id}")
            if raw:
                pre_data = json.loads(raw)
                if pre_data.get("contribution_id") == contribution_id:
                    from app.models.template_corpus_case import TemplateCorpusCase
                    from app.core.database import AsyncSessionLocal
                    from datetime import datetime, timezone
                    # 用独立 session + 显式 begin()——
                    # 1) 不复用 endpoint 的 db（上面已 commit，begin_nested 在已 commit 的 session
                    #    上是隐式开新 transaction，语义模糊且 FK 错误会被 except 吞掉）
                    # 2) AsyncSessionLocal.begin() 失败时会自动 rollback，语料失败不影响
                    #    contribution 已完成的 approve 主事务。
                    async with AsyncSessionLocal() as corpus_db:
                        async with corpus_db.begin():
                            for case in pre_data.get("corpus_cases", []):
                                tid = case.get("expected_template_id", "")
                                if tid.startswith("pending_"):
                                    # 用新 promote 的 template id 替换占位符
                                    tid = promoted_id
                                corpus_db.add(TemplateCorpusCase(
                                    intent=case["intent"],
                                    code_type=case["code_type"],
                                    expected_template_id=tid,
                                    source=case.get("source", "auto_generated"),
                                    auto_generated_from=contribution_id,
                                    note=case.get("note"),
                                    is_active=True,
                                    created_at=datetime.now(timezone.utc),
                                ))
                await redis.delete(f"pre_analysis:{analysis_id}")
        except Exception as e:
            print(f"[WARN] corpus case persist failed: {type(e).__name__}: {e}", flush=True)

    return {"status": "approved", "promoted_template_id": promoted_id}


@router.post("/{contribution_id}/reject")
async def admin_reject(
    contribution_id: str,
    payload: ContributionReviewAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.status not in ("pending_review", "needs_revision"):
        raise HTTPException(status_code=400, detail="该状态不可拒绝")

    await reject_contribution(
        contribution=contribution,
        reviewer_id=current_user.id,
        comment=payload.comment or "",
        db=db,
    )
    await db.commit()
    return {"status": "rejected"}


@router.post("/{contribution_id}/request-revision")
async def admin_request_revision(
    contribution_id: str,
    payload: ContributionReviewAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.status != "pending_review":
        raise HTTPException(status_code=400, detail="只能对 pending_review 状态请求修改")

    await request_revision(
        contribution=contribution,
        reviewer_id=current_user.id,
        comment=payload.comment or "",
        db=db,
    )
    await db.commit()
    return {"status": "needs_revision"}
