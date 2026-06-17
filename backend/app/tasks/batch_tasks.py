from __future__ import annotations
import asyncio
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.tasks.celery_app import celery_app

UPLOAD_DIR = Path("/app/uploads")
RESULT_DIR = Path("/app/results")

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="batch_tasks.run_batch_job", max_retries=3)
def run_batch_job(self, job_id: str) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_batch_job_async(job_id))
    finally:
        loop.close()


async def _run_batch_job_async(job_id: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.core.config import get_settings
    from app.models.batch_job import BatchJob
    from app.services.parser.excel_parser import (
        MULTISHEET_CODE_TYPE_SENTINEL,
        parse_excel,
        parse_excel_multisheet,
    )
    from app.services.core.pipeline import (
        PipelineInput,
        run_pipeline,
        UnderSpecifiedIntentError,
        OffTopicIntentError,
        CodeTypeMismatchError,
    )

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        job = await db.get(BatchJob, job_id)
        if not job:
            return

        input_file = _find_input_file(job_id)
        if not input_file:
            job.status = "failed"
            job.error_message = "找不到上传文件"
            await db.commit()
            return

        job.status = "running"
        await db.commit()

        try:
            if job.code_type == MULTISHEET_CODE_TYPE_SENTINEL:
                rows = parse_excel_multisheet(input_file)
            else:
                rows = parse_excel(input_file, job.code_type)
            RESULT_DIR.mkdir(parents=True, exist_ok=True)
            results = []

            for i, row in enumerate(rows):
                intent_text = row.intent if hasattr(row, "intent") and row.intent else row.extra.get("intent", "")
                if not intent_text:
                    results.append({
                        "row_id": row.row_id,
                        "status": "skipped",
                        "reason": "空意图",
                    })
                    job.completed_rows = i + 1
                    await db.commit()
                    continue

                inp = PipelineInput(
                    original_intent=intent_text,
                    code_type=row.code_type,
                    protocol=row.protocol,
                    clk=row.clk or "clk",
                    rst=row.rst or "rst_n",
                    rst_polarity=row.rst_polarity or "低有效",
                    signals=[
                        {"name": s.name, "width": s.width, "role": s.role}
                        for s in row.signals
                    ],
                )

                try:
                    result = await run_pipeline(inp, db)
                    results.append({
                        "row_id": row.row_id,
                        "status": "success",
                        "template_id": result.template_id,
                        "confidence": result.confidence,
                        "code": result.code,
                    })
                except UnderSpecifiedIntentError as e:
                    # v3.0 P0-4：under_specified 是"用户问题"——把缺失参数清单回传，
                    # 前端批量结果表可让用户对单行修改意图后重跑，不要整批失败。
                    logger.info(
                        "row %s under_specified: template=%s missing=%s",
                        row.row_id, e.template_id, [m["name"] for m in e.missing_params],
                    )
                    results.append({
                        "row_id": row.row_id,
                        "status": "under_specified",
                        "template_id": e.template_id,
                        "template_name": e.template_name,
                        "missing_params": e.missing_params,
                        "reason": (
                            f"已识别推荐模板「{e.template_name}」，但描述里缺少这些必填参数："
                            + "、".join(m["name"] for m in e.missing_params)
                            + "。请修改该行意图后单独重跑。"
                        ),
                    })
                except OffTopicIntentError as e:
                    # off-topic 也是用户问题——回传结构化原因
                    logger.info("row %s off_topic top1=%.4f", row.row_id, e.top_dense_score)
                    results.append({
                        "row_id": row.row_id,
                        "status": "off_topic",
                        "top_dense_score": e.top_dense_score,
                        "threshold": e.threshold,
                        "reason": "输入似乎与 IC 验证需求无关，请重写意图。",
                    })
                except CodeTypeMismatchError as e:
                    # FEAT-18: 批量场景下用户不再"选 code_type"，是"在哪个 sheet 填行"。
                    # gate 2 触发说明用户把行写在了不匹配 sheet——文案改成"挪到对应
                    # sheet 后重跑"。具体文案构造在 _build_code_type_mismatch_reason
                    # helper 中（便于单测覆盖"sheet"关键词）。
                    logger.info(
                        "row %s code_type_mismatch selected=%s suggested=%s",
                        row.row_id, e.selected_code_type, e.suggested_code_type,
                    )
                    results.append({
                        "row_id": row.row_id,
                        "status": "code_type_mismatch",
                        "selected_code_type": e.selected_code_type,
                        "suggested_code_type": e.suggested_code_type,
                        "reason": _build_code_type_mismatch_reason(
                            e.selected_code_type,
                            e.suggested_code_type,
                        ),
                    })
                except Exception as e:
                    logger.warning("pipeline failed for row %s: %s", row.row_id, e, exc_info=True)
                    results.append({
                        "row_id": row.row_id,
                        "status": "failed",
                        "reason": "代码生成失败，请检查意图描述或联系管理员",
                    })

                job.completed_rows = i + 1
                if (i + 1) % 5 == 0:
                    await db.commit()

            result_zip = RESULT_DIR / f"{job_id}.zip"
            _write_result_zip(result_zip, results)

            job.status = "done"
            job.result_url = str(result_zip)
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            logger.error("batch job %s failed: %s", job_id, e, exc_info=True)
            job.status = "failed"
            job.error_message = "批量任务处理失败，请联系管理员"
            await db.commit()
        finally:
            await engine.dispose()


def _build_code_type_mismatch_reason(
    selected_code_type: str,
    suggested_code_type: str,
) -> str:
    """FEAT-18: 把 gate 2 在批量场景下的 reason 文案抽成独立 helper，便于单测验证
    "sheet" 关键词覆盖生效。运行时由 _run_batch_job_async 的 CodeTypeMismatchError
    分支调用；registry 反查在 helper 内完成，registry 故障时退化为 code_type id 字面量。
    """
    from app.services.registry import get_registry

    try:
        sheet_name = get_registry().get(selected_code_type).excel_sheet_name
    except ValueError:
        sheet_name = selected_code_type
    return (
        f"您在「{sheet_name}」sheet 中写了更像「{suggested_code_type}」"
        f"的描述。请将该行挪到对应 sheet 后重跑该行（提示：编辑 Excel "
        f"时把该行 cut 到正确 sheet）"
    )


def _find_input_file(job_id: str) -> Path | None:
    for suffix in (".xlsx", ".xls"):
        p = UPLOAD_DIR / f"{job_id}{suffix}"
        if p.exists():
            return p
    return None


def _write_result_zip(zip_path: Path, results: list[dict]) -> None:
    json_path = zip_path.with_suffix(".json")
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sv_dir = zip_path.parent / f"{zip_path.stem}_sv"
    sv_dir.mkdir(exist_ok=True)

    for item in results:
        if item.get("status") == "success" and item.get("code"):
            sv_file = sv_dir / f"{item['row_id']}.sv"
            sv_file.write_text(item["code"], encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, "results.json")
        for sv_file in sv_dir.glob("*.sv"):
            zf.write(sv_file, f"sv/{sv_file.name}")

    json_path.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(sv_dir, ignore_errors=True)
