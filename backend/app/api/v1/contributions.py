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
    ContributionPreviewRequest,
    ContributionPreviewResponse,
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
    generate_from_intent,
    _validate_jinja_rendering,
    _validate_parameter_defs,
    _validate_template_name,
)
from app.services.platform.corpus_service import (
    generate_corpus_cases,
    detect_conflicts,
    generate_llm_analysis,
)

_PRE_ANALYSIS_TTL = 60 * 60  # 1h — admin must approve within an hour of running pre-check

router = APIRouter(prefix="/contributions", tags=["contributions"])


def _parse_failed_422(e: ContributionParseError) -> HTTPException:
    """统一 contribution_parse_failed 422 响应构造。"""
    return HTTPException(
        status_code=422,
        detail={
            "type": "contribution_parse_failed",
            "stage": e.stage,
            "reason": e.reason,
            "message": (
                f"AI 解析失败（阶段：{e.stage}），请完善场景描述 / 代码示例后重试。"
            ),
        },
    )


@router.post("/preview", response_model=ContributionPreviewResponse)
async def preview_contribution(
    payload: ContributionPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """FEAT-10：仅基于 original_intent + code_type 让 LLM 生成完整模板预览（不入库）。

    成功 → 返回 LLM 生成的 5 字段 + name_conflict 标记；失败 → 422 contribution_parse_failed。
    name_conflict 非阻塞——前端展示警告，让用户改名后再提交。
    """
    llm = await get_default_llm_client(db)
    try:
        extracted = await generate_from_intent(
            original_intent=payload.original_intent,
            code_type=payload.code_type,
            llm=llm,
        )
    except ContributionParseError as e:
        raise _parse_failed_422(e)

    name_conflict = await check_name_duplicate(db, extracted.template_name)
    # demo_code 回传 LLM 产出的**原始 SystemVerilog 代码**（含真实信号名 / 字面量），
    # 前端用它作为"立即使用"的可复制代码块；jinja_body 不暴露给前端——它在用户编辑后
    # 由 submit 端点（branch 3）通过 derive_parameters_from_demo 重新生成。
    return ContributionPreviewResponse(
        template_name=extracted.template_name,
        description=extracted.description,
        demo_code=extracted.demo_code,
        parameter_defs=extracted.parameter_defs,
        keywords=extracted.keywords,
        name_conflict=name_conflict,
    )


@router.post("", response_model=ContributionOut, status_code=201)
async def submit_contribution(
    payload: ContributionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """FEAT-10：提交贡献，支持 3 条分支并存。

    分支选择（按顺序判断）：
    1. **intent-only 生成**：缺 template_name 或 demo_code → 调 generate_from_intent 让 LLM 同时
       产出 template_name + description + demo_code + parameter_defs + keywords。
    2. **显式 parameter_defs**：caller 显式传了 parameter_defs（如 v2 批量导入） → 直接入库，
       不跑 LLM。
    3. **v3.0 demo 反推**：4 字段齐全（template_name + description + demo_code）→ 跑
       derive_parameters_from_demo 把 demo_code 反推为 Jinja2 模板。

    P1-6 dedup：name 精确重名 422；语义查重 top-3 塞 original_row_json 不阻塞。
    """
    # 分支 1：缺关键字段则触发 intent-only 生成
    need_llm_generate = not (payload.template_name and payload.demo_code)

    if need_llm_generate:
        llm = await get_default_llm_client(db)
        try:
            generated = await generate_from_intent(
                original_intent=payload.original_intent,
                code_type=payload.code_type,
                llm=llm,
            )
        except ContributionParseError as e:
            raise _parse_failed_422(e)
        final_template_name = payload.template_name or generated.template_name
        final_description = payload.description or generated.description
        # user_demo（保留进 original_row_json["user_demo"]）始终是**原始 SV 代码**，
        # 不是 Jinja2 模板体——审核员对比时看的是用户/LLM 视角的"能跑的代码"。
        final_user_demo = payload.demo_code or generated.demo_code
        derived_param_defs = generated.parameter_defs
        derived_jinja_body = generated.jinja_body
        derived_keywords = generated.keywords
        derived_subcategory = generated.subcategory or payload.subcategory
        derived_protocol = generated.protocol or payload.protocol
    else:
        final_template_name = payload.template_name
        final_description = payload.description or ""
        final_user_demo = payload.demo_code

        # 分支 2：v2 兼容——显式传了 parameter_defs，跳过 LLM
        if payload.parameter_defs:
            derived_param_defs = payload.parameter_defs
            derived_jinja_body = payload.demo_code
            derived_keywords = payload.keywords or []
            derived_subcategory = payload.subcategory
            derived_protocol = payload.protocol
        else:
            # 分支 3：v3.0 4 字段路径——LLM 反推 demo_code → Jinja2
            llm = await get_default_llm_client(db)
            try:
                extracted = await derive_parameters_from_demo(
                    demo_code=payload.demo_code,
                    description=final_description,
                    code_type=payload.code_type,
                    llm=llm,
                )
            except ContributionParseError as e:
                raise _parse_failed_422(e)
            derived_param_defs = extracted.parameter_defs
            derived_jinja_body = extracted.jinja_body
            derived_keywords = extracted.keywords
            derived_subcategory = extracted.subcategory or payload.subcategory
            derived_protocol = extracted.protocol or payload.protocol

    # FEAT-10 C1：用户传入的 template_name 也必须过命名规范校验（LLM 路径下 generate_from_intent
    # 内部已校验，但分支 2/3 + 分支 1 的 payload.template_name 覆盖路径不会自动跑校验）
    try:
        _validate_template_name(final_template_name)
    except ContributionParseError as e:
        raise _parse_failed_422(e)

    # P1-6：name 精确查重——LLM 生成后再查（intent-only 路径下 template_name 可能由 LLM 产出）
    if await check_name_duplicate(db, final_template_name):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "contribution_name_duplicate",
                "name": final_template_name,
                "message": f"模板名「{final_template_name}」已存在，请换个名字。",
            },
        )

    contribution = TemplateContribution(
        contributor_id=current_user.id,
        code_type=payload.code_type,
        original_intent=payload.original_intent,
        original_row_json=payload.original_row_json,
        template_name=final_template_name,
        subcategory=derived_subcategory,
        protocol=derived_protocol,
        # demo_code 字段存 Jinja2 化模板（审核员可在三栏面板里改）
        demo_code=derived_jinja_body,
        description=final_description,
        keywords=derived_keywords,
        parameter_defs=derived_param_defs,
        status="pending_review",
    )
    # 留个 user_demo 副本在 original_row_json 里——审核员对比用
    if not contribution.original_row_json:
        contribution.original_row_json = {}
    contribution.original_row_json["user_demo"] = final_user_demo

    # P1-6：语义查重——top-3 塞 original_row_json["similar_templates"]，不阻塞提交
    try:
        similar = await check_semantic_duplicate(
            description=final_description,
            name=final_template_name,
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
