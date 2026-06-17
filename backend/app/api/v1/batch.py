from __future__ import annotations
import io
import uuid
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.batch_job import BatchJob
from app.schemas.generate import BatchUploadResponse, BatchStatusResponse, PreflightResponse, PreflightRowResult
from app.services.registry import get_registry
from app.services.intent.preflight import preflight_row
from app.services.parser.excel_parser import (
    MULTISHEET_CODE_TYPE_SENTINEL,
    parse_excel,
    parse_excel_multisheet,
)
from app.services.parser.template_writer import build_template_workbook

UPLOAD_DIR = Path("/app/uploads")
RESULT_DIR = Path("/app/results")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_SUFFIXES = {".xlsx", ".xls"}

# `no_valid_rows` 错误 detail 与 7 闸 detail 风格一致——结构化 type + message，便于
# 前端 handleApiError 走与 generate 端点一致的展示逻辑。
_NO_VALID_ROWS_DETAIL = {
    "type": "no_valid_rows",
    "message": (
        "未检测到任何有效数据行；请确认 SVA 需求 / Coverage 需求 sheet 中"
        "至少一个 row A 列填了编号"
    ),
}


def _parse_upload(file_path: Path, code_type: str | None) -> tuple[list, str]:
    """统一两个端点的 Excel 解析入口：
    - `code_type is None` → multisheet 路径，DB 写 sentinel
    - 否则 → 单 sheet 路径，DB 写原 code_type

    异常翻译：`parse_excel_multisheet` 抛 `ValueError("no_valid_rows")` → 400
    结构化 detail；其他 ValueError（registry 未知 code_type / schema 损坏）→
    400 文案；openpyxl 解码失败等 IO 异常 → 400 通用文案（不外泄内部异常）。
    """
    try:
        if code_type is None:
            rows = parse_excel_multisheet(file_path)
            return rows, MULTISHEET_CODE_TYPE_SENTINEL
        rows = parse_excel(file_path, code_type)
        return rows, code_type
    except ValueError as e:
        if str(e) == "no_valid_rows":
            raise HTTPException(status_code=400, detail=_NO_VALID_ROWS_DETAIL)
        raise HTTPException(status_code=400, detail=f"Excel 解析失败: {e}")
    except Exception:
        # openpyxl 对损坏 .xls / 加密 / 格式不匹配会抛各种异常族；统一翻 400 而
        # 不泄漏内部异常 message，避免暴露内部路径或栈。
        raise HTTPException(
            status_code=400,
            detail="无法读取 Excel 文件，请检查文件格式是否完好",
        )

router = APIRouter(prefix="/batch", tags=["batch"])


def _safe_result_path(result_url: str) -> Path:
    resolved = Path(result_url).resolve()
    result_dir = RESULT_DIR.resolve()
    if not str(resolved).startswith(str(result_dir)):
        raise HTTPException(status_code=400, detail="非法的结果文件路径")
    return resolved


@router.post("/upload", response_model=BatchUploadResponse)
async def upload_batch(
    file: UploadFile = File(...),
    code_type: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    registry = get_registry()
    if code_type is not None and code_type not in [ct.id for ct in registry.all()]:
        raise HTTPException(status_code=400, detail=f"未知的代码类型: {code_type}")

    suffix = Path(file.filename or "upload.xlsx").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="只允许上传 .xlsx 或 .xls 文件")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 10MB 限制")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{job_id}{suffix}"
    save_path.write_bytes(content)

    rows, stored_code_type = _parse_upload(save_path, code_type)
    total_rows = len(rows)

    job = BatchJob(
        id=job_id,
        user_id=current_user.id,
        code_type=stored_code_type,
        status="pending",
        total_rows=total_rows,
        completed_rows=0,
    )
    db.add(job)
    await db.commit()

    from app.tasks.batch_tasks import run_batch_job
    run_batch_job.delay(job_id)

    return BatchUploadResponse(
        job_id=job_id,
        total_rows=total_rows,
        code_type=stored_code_type,
        status="pending",
    )


# 路由顺序关键：`GET /template` 必须注册在所有 `GET /{job_id}/...` 之前，否则 FastAPI
# 会把 "template" 当作 job_id 路径参数命中 status / download 路由。
@router.get("/template", response_class=StreamingResponse)
async def download_template(current_user: User = Depends(get_current_user)):
    buffer = io.BytesIO()
    wb = build_template_workbook(get_registry())
    wb.save(buffer)
    buffer.seek(0)
    filename = f"batch_template_{date.today().strftime('%Y%m%d')}.xlsx"
    # filename 用 RFC 6266 推荐的 quoted-string 形式，避免日后 filename 含特殊字符
    # 或来自外部输入时被 header injection。当前 filename 是固定 ASCII 模式，不会
    # 触发 quoting 边角情况。
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}/status", response_model=BatchStatusResponse)
async def get_batch_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.get(BatchJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.user_id != current_user.id and current_user.role not in ("lib_admin", "super_admin"):
        raise HTTPException(status_code=403, detail="无权访问该任务")

    progress = (job.completed_rows / job.total_rows) if job.total_rows > 0 else 0.0
    return BatchStatusResponse(
        job_id=job.id,
        status=job.status,
        total_rows=job.total_rows,
        completed_rows=job.completed_rows,
        progress=round(progress, 4),
        result_url=job.result_url,
    )


@router.get("/{job_id}/download")
async def download_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.get(BatchJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.user_id != current_user.id and current_user.role not in ("lib_admin", "super_admin"):
        raise HTTPException(status_code=403, detail="无权访问该任务")
    if job.status != "done" or not job.result_url:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    result_path = _safe_result_path(job.result_url)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")

    return FileResponse(path=str(result_path), filename=result_path.name, media_type="application/zip")


@router.post("/preflight", response_model=PreflightResponse)
async def preflight(
    file: UploadFile = File(...),
    code_type: str | None = Form(None),
    current_user: User = Depends(get_current_user),
):
    registry = get_registry()
    if code_type is not None and code_type not in [ct.id for ct in registry.all()]:
        raise HTTPException(status_code=400, detail=f"未知的代码类型: {code_type}")

    suffix = Path(file.filename or "upload.xlsx").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="只允许上传 .xlsx 或 .xls 文件")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 10MB 限制")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # W1: 用真实后缀，不要硬编码 .xlsx——`.xls` 上传时 openpyxl 会按文件后缀
    # 选解析路径，写错后缀可能静默读出错误数据。
    tmp_path = UPLOAD_DIR / f"preflight_{uuid.uuid4()}{suffix}"
    tmp_path.write_bytes(content)

    try:
        rows, _ = _parse_upload(tmp_path, code_type)
        results = []
        for row in rows:
            intent_text = row.intent or row.extra.get("intent", "")
            pr = await preflight_row(row_id=row.row_id, intent_text=intent_text)
            results.append(PreflightRowResult(
                row_id=pr["row_id"],
                estimated_confidence=pr["estimated_confidence"],
                top_match=pr.get("top_match"),
                code_type=row.code_type,
            ))
    finally:
        tmp_path.unlink(missing_ok=True)

    return PreflightResponse(results=results)
