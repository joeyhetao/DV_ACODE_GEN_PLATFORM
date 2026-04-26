from __future__ import annotations
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.batch_job import BatchJob
from app.schemas.generate import BatchUploadResponse, BatchStatusResponse, PreflightResponse, PreflightRowResult
from app.services.registry import get_registry
from app.services.intent.preflight import preflight_row
from app.services.parser.excel_parser import parse_excel

UPLOAD_DIR = Path("/app/uploads")
RESULT_DIR = Path("/app/results")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_SUFFIXES = {".xlsx", ".xls"}

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
    code_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    registry = get_registry()
    if code_type not in [ct.id for ct in registry.all()]:
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

    rows = parse_excel(save_path, code_type)
    total_rows = len(rows)

    job = BatchJob(
        id=job_id,
        user_id=current_user.id,
        code_type=code_type,
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
        code_type=code_type,
        status="pending",
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
    code_type: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    registry = get_registry()
    if code_type not in [ct.id for ct in registry.all()]:
        raise HTTPException(status_code=400, detail=f"未知的代码类型: {code_type}")

    suffix = Path(file.filename or "upload.xlsx").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="只允许上传 .xlsx 或 .xls 文件")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 10MB 限制")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = UPLOAD_DIR / f"preflight_{uuid.uuid4()}.xlsx"
    tmp_path.write_bytes(content)

    try:
        rows = parse_excel(tmp_path, code_type)
        results = []
        for row in rows:
            intent_text = row.intent or row.extra.get("intent", "")
            pr = await preflight_row(row_id=row.row_id, intent_text=intent_text)
            results.append(PreflightRowResult(
                row_id=pr["row_id"],
                estimated_confidence=pr["estimated_confidence"],
                top_match=pr.get("top_match"),
            ))
    finally:
        tmp_path.unlink(missing_ok=True)

    return PreflightResponse(results=results)
