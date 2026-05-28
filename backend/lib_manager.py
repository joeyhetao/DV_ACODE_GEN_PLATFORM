#!/usr/bin/env python3
"""
lib_manager.py — 模板库管理 CLI

用法:
  python lib_manager.py import      [--dir DIR] [--force]
  python lib_manager.py validate    [--dir DIR]
  python lib_manager.py rebuild     [--collection NAME]
  python lib_manager.py export      [--dir DIR]
  python lib_manager.py backup
  python lib_manager.py list        [--code-type TYPE]
  python lib_manager.py dedup-check [--threshold T] [--code-type TYPE]
"""
from __future__ import annotations
import asyncio
import sys
import uuid
from pathlib import Path

import click
import yaml


TEMPLATE_LIBRARY_DIR = Path(__file__).parent / "template_library"


# ─── CLI entry ───────────────────────────────────────────────────────────────

@click.group()
def cli():
    pass


# ─── import ──────────────────────────────────────────────────────────────────

@cli.command("import")
@click.option("--dir", "lib_dir", default=str(TEMPLATE_LIBRARY_DIR), help="模板目录")
@click.option("--force", is_flag=True, help="跳过语义查重，强制导入")
def cmd_import(lib_dir: str, force: bool):
    """将 YAML 模板库文件导入数据库并同步 Qdrant"""
    asyncio.run(_import(Path(lib_dir), force))


async def _import(lib_dir: Path, force: bool):
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.models.template import Template
    from app.services.core.dedup import check_name_duplicate, check_semantic_duplicate
    from app.services.core.renderer import validate_template_syntax
    from sqlalchemy import select

    files = list(lib_dir.rglob("*.yaml"))
    click.echo(f"发现 {len(files)} 个模板文件")

    imported = skipped_dup = skipped_name = failed = 0

    async with AsyncSessionLocal() as db:
        for f in files:
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                template_id = data["id"]
                name = data["name"]

                if await check_name_duplicate(db, name):
                    click.echo(f"  [跳过-名称冲突] {name}")
                    skipped_name += 1
                    continue

                validate_template_syntax(data["template_body"])

                if not force:
                    similar = await check_semantic_duplicate(
                        description=data.get("description", ""),
                        name=name,
                        tags=data.get("tags"),
                        keywords=data.get("keywords"),
                    )
                    if similar:
                        click.echo(f"  [跳过-语义重复] {name} → 相似: {similar[0]['template_id']}")
                        skipped_dup += 1
                        continue

                # expr_type lint：检查 parameters 是否声明了 expr_type，未声明的输出 warn
                # （不阻断导入，仅提示团队补全以适配未来加入的新参数名）
                from app.services.core.identifier import IDENTIFIER_PARAMS
                missing_expr_type: list[str] = []
                for p in (data.get("parameters") or []):
                    pname = p.get("name")
                    if not pname or "expr_type" in p:
                        continue
                    fallback = "sv_identifier" if pname in IDENTIFIER_PARAMS else "(无校验)"
                    missing_expr_type.append(f"{pname} → fallback {fallback}")
                if missing_expr_type:
                    click.echo(
                        f"  [WARN] {name}: 参数未声明 expr_type，按 fallback 处理: "
                        + ", ".join(missing_expr_type)
                    )

                # 把 YAML 里的 differentiators / non_use_cases 序列化进 description
                # 末尾——spec §3 Out 明确"不修改数据库 schema"，所以这两个字段必须
                # 借现有 description 列流转到 pipeline.candidate_dicts → LLM prompt。
                # 拼接位置在末尾、用固定标题包裹，方便：
                #   1) reranker（engine.py:90 拼 name + description 作为 encoded text）
                #      也能看到区分信息，对近邻混淆对的客观打分有帮助
                #   2) lib_manager.export 反向写回 YAML 时按标题切分恢复原结构（未实现，
                #      当前 ticket 不做导出回写）
                description = _compose_description(
                    data.get("description", ""),
                    data.get("differentiators") or [],
                    data.get("non_use_cases") or [],
                )

                from datetime import datetime, timezone
                template = Template(
                    id=template_id,
                    version=data.get("version", "1.0.0"),
                    name=name,
                    code_type=data["code_type"],
                    subcategory=data.get("subcategory"),
                    protocol=data.get("protocol"),
                    tags=data.get("tags"),
                    keywords=data.get("keywords"),
                    description=description,
                    parameters=data.get("parameters", []),
                    template_body=data["template_body"],
                    maturity=data.get("maturity", "draft"),
                    related_ids=data.get("related_ids"),
                    created_by=None,
                    sync_status="syncing",
                )
                db.add(template)
                await db.commit()
                await _sync_to_qdrant(db, template)
                click.echo(f"  [导入] {name}")
                imported += 1

            except Exception as e:
                click.echo(f"  [失败] {f.name}: {e}", err=True)
                failed += 1

    click.echo(f"\n完成: 导入={imported} 名称冲突={skipped_name} 语义重复={skipped_dup} 失败={failed}")

    # 批量导入后清 intent_cache：旧的 intent → (template_id, params) 映射可能
    # 指向已不存在 / schema 改了的模板。逐条核对成本高，整体清更稳。
    # gen:* 不清（template_id+params 维度精确，新模板用新 key，不会撞）。
    if imported > 0:
        try:
            from app.services.core.cache import invalidate_all_intent_cache
            n = await invalidate_all_intent_cache()
            click.echo(f"  [清缓存] intent_cache:* 删除 {n} 条")
        except Exception as e:
            click.echo(f"  [WARN] intent_cache 清理失败: {e}", err=True)


# ─── validate ────────────────────────────────────────────────────────────────

@cli.command("validate")
@click.option("--dir", "lib_dir", default=str(TEMPLATE_LIBRARY_DIR))
def cmd_validate(lib_dir: str):
    """验证 YAML 模板文件语法 + description 完整性 + differentiators/non_use_cases 字段形态。

    校验类别：
      ERROR — 必填字段缺失 / template_body Jinja2 语法错 / differentiators / non_use_cases
              若声明则必须是非空 list（出现这两个键且为空 list 或非 list → 视为意图缺失，按 ERROR 拦）。
      WARN  — description 缺失 或 < 30 字节（A10 引入：要求 description 覆盖
              "做什么 / 典型场景 / 边界"三要素，60 字以下大概率没说全）。
    """
    from app.services.core.renderer import validate_template_syntax

    files = list(Path(lib_dir).rglob("*.yaml"))
    errors = 0
    warnings = 0
    for f in files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            required_keys = ["id", "name", "code_type", "template_body"]
            for key in required_keys:
                if key not in data:
                    raise ValueError(f"缺少必填字段: {key}")
            validate_template_syntax(data["template_body"])

            # A10：description 长度 < 30 字节 WARN（鼓励补全"做什么/典型场景/边界"三要素）
            desc = (data.get("description") or "").strip()
            if not desc or len(desc.encode("utf-8")) < 30:
                click.echo(
                    f"  [WARN] {f.name}: description 缺失或过短"
                    f"（{len(desc.encode('utf-8'))} bytes < 30），"
                    "应覆盖「做什么 / 典型场景 / 边界（请勿用于 X 请用 Y）」三要素"
                )
                warnings += 1

            # A10：声明了 differentiators / non_use_cases 就必须是非空 list
            for opt_key in ("differentiators", "non_use_cases"):
                if opt_key in data:
                    val = data[opt_key]
                    if not isinstance(val, list) or len(val) == 0:
                        raise ValueError(
                            f"{opt_key} 字段存在但不是非空 list（type={type(val).__name__}，"
                            f"len={len(val) if isinstance(val, list) else 'n/a'}）"
                        )

            click.echo(f"  [OK] {f.name}")
        except Exception as e:
            click.echo(f"  [ERROR] {f.name}: {e}", err=True)
            errors += 1

    if errors:
        click.echo(f"\n{errors} 个文件验证失败（warnings={warnings}）", err=True)
        sys.exit(1)
    else:
        click.echo(f"\n全部 {len(files)} 个文件验证通过（warnings={warnings}）")


# ─── rebuild ─────────────────────────────────────────────────────────────────

@cli.command("rebuild")
@click.option("--collection", default=None, help="Qdrant collection 名称")
def cmd_rebuild(collection: str | None):
    """重建 Qdrant 向量索引（同步所有 sync_status=syncing 的模板）"""
    asyncio.run(_rebuild(collection))


async def _rebuild(collection: str | None):
    from app.core.database import AsyncSessionLocal
    from app.models.template import Template
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Template).where(Template.is_active == True, Template.sync_status == "syncing")
        )
        templates = result.scalars().all()
        click.echo(f"待同步模板: {len(templates)}")

        for tmpl in templates:
            try:
                await _sync_to_qdrant(db, tmpl, collection)
                click.echo(f"  [同步] {tmpl.name}")
            except Exception as e:
                click.echo(f"  [失败] {tmpl.name}: {e}", err=True)

    click.echo("重建完成")


# ─── export ──────────────────────────────────────────────────────────────────

@cli.command("export")
@click.option("--dir", "out_dir", default="./export")
def cmd_export(out_dir: str):
    """将数据库模板导出为 YAML 文件"""
    asyncio.run(_export(Path(out_dir)))


async def _export(out_dir: Path):
    from app.core.database import AsyncSessionLocal
    from app.models.template import Template
    from sqlalchemy import select

    out_dir.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Template).where(Template.is_active == True))
        templates = result.scalars().all()

        for tmpl in templates:
            data = {
                "id": tmpl.id,
                "version": tmpl.version,
                "name": tmpl.name,
                "code_type": tmpl.code_type,
                "subcategory": tmpl.subcategory,
                "protocol": tmpl.protocol or [],
                "tags": tmpl.tags or [],
                "keywords": tmpl.keywords or [],
                "description": tmpl.description,
                "parameters": tmpl.parameters or [],
                "template_body": tmpl.template_body,
                "maturity": tmpl.maturity,
                "related_ids": tmpl.related_ids or [],
            }
            sub = out_dir / tmpl.code_type
            sub.mkdir(exist_ok=True)
            out_file = sub / f"{tmpl.id}.yaml"
            out_file.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            click.echo(f"  [导出] {tmpl.name}")

    click.echo(f"导出完成: {out_dir}")


# ─── backup ──────────────────────────────────────────────────────────────────

@cli.command("backup")
def cmd_backup():
    """触发 PostgreSQL pg_dump 备份"""
    asyncio.run(_backup())


async def _backup():
    from app.core.config import get_settings
    from app.services.platform.backup_service import create_pg_backup

    settings = get_settings()
    out_file = await create_pg_backup(settings.database_url)
    click.echo(f"备份完成: {out_file}")


# ─── list ─────────────────────────────────────────────────────────────────────

@cli.command("list")
@click.option("--code-type", default=None)
def cmd_list(code_type: str | None):
    """列出数据库中的模板"""
    asyncio.run(_list(code_type))


async def _list(code_type: str | None):
    from app.core.database import AsyncSessionLocal
    from app.models.template import Template
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        stmt = select(Template).where(Template.is_active == True)
        if code_type:
            stmt = stmt.where(Template.code_type == code_type)
        result = await db.execute(stmt.order_by(Template.code_type, Template.name))
        templates = result.scalars().all()

        click.echo(f"{'ID':<32} {'CODE_TYPE':<12} {'MATURITY':<10} NAME")
        click.echo("-" * 80)
        for tmpl in templates:
            click.echo(f"{tmpl.id:<32} {tmpl.code_type:<12} {tmpl.maturity:<10} {tmpl.name}")
        click.echo(f"\n共 {len(templates)} 个模板")


# ─── dedup-check ─────────────────────────────────────────────────────────────

@cli.command("dedup-check")
@click.option("--threshold", type=float, default=None,
              help="覆盖 settings.template_dedup_threshold（默认 0.90）")
@click.option("--code-type", default=None, help="只检查指定 code_type")
def cmd_dedup_check(threshold: float | None, code_type: str | None):
    """按当前 dedup 阈值扫一遍历史模板，列出潜在重复。

    阈值变更后用：dedup 在 import 时只对"新模板 vs 历史"判定一次，阈值改了不会
    回溯历史样本。本命令对每条 active 模板调一次 check_semantic_duplicate，列出
    每条命中阈值的同义对（自反命中除外）。仅打印，**不**删除任何模板。
    """
    asyncio.run(_dedup_check(threshold, code_type))


async def _dedup_check(threshold: float | None, code_type: str | None):
    from app.core.database import AsyncSessionLocal
    from app.core.config import get_settings
    from app.models.template import Template
    from app.services.core.dedup import check_semantic_duplicate
    from sqlalchemy import select

    settings = get_settings()
    effective = threshold if threshold is not None else settings.template_dedup_threshold
    click.echo(f"使用阈值 {effective:.4f}（settings 默认 {settings.template_dedup_threshold:.4f}）")

    # 临时覆盖 settings 让 check_semantic_duplicate 用我们的阈值
    original = settings.template_dedup_threshold
    settings.template_dedup_threshold = effective
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(Template).where(Template.is_active == True)
            if code_type:
                stmt = stmt.where(Template.code_type == code_type)
            templates = (await db.execute(stmt.order_by(Template.name))).scalars().all()
            click.echo(f"扫描 {len(templates)} 条模板……\n")

            findings = 0
            for tmpl in templates:
                similar = await check_semantic_duplicate(
                    description=tmpl.description or "",
                    name=tmpl.name,
                    tags=tmpl.tags,
                    keywords=tmpl.keywords,
                    top_k=3,
                )
                # 滤掉自反命中
                similar = [s for s in similar if s["template_id"] != tmpl.id]
                if similar:
                    findings += 1
                    click.echo(f"[潜在重复] {tmpl.id}  {tmpl.name}")
                    for s in similar:
                        click.echo(f"    ~ {s['template_id']}  score={s['score']}")

            click.echo(
                f"\n完成：{findings} 条模板存在阈值内 (≥{effective}) 的相似项。"
                f"不会自动删除——请人工评审后用 Admin UI / API 处理。"
            )
    finally:
        settings.template_dedup_threshold = original


# ─── helpers ─────────────────────────────────────────────────────────────────

# 拼接 description 时使用的固定标题——_render_step1_candidate / verify_step1_selection
# 端的 description[:N] 截断阈值要足够容纳 base + 两段。当前 description ≈ 200–300 char，
# 区别要点 ≈ 200 char、不适用场景 ≈ 200 char，实测合成最长 812 char
# （protocol_handshake_coverage）。LLM 候选渲染截断设为 1000 留余量，
# 避免 non_use_cases 末项被切（review NEW-1）。
_DESC_DIFF_HEADER = "\n\n区别要点：\n"
_DESC_NON_HEADER = "\n\n不适用场景：\n"


def _compose_description(base: str, differentiators: list[str], non_use_cases: list[str]) -> str:
    """把 base description + differentiators + non_use_cases 拼成一个 description 字符串。

    spec §3 Out 禁了改 DB schema，所以这两个字段必须搭 description 字段的便车送进
    DB → Qdrant payload → pipeline.candidate_dicts → LLM step1 / verify prompt。
    """
    out = (base or "").rstrip()
    if differentiators:
        out += _DESC_DIFF_HEADER + "\n".join(f"- {d}" for d in differentiators)
    if non_use_cases:
        out += _DESC_NON_HEADER + "\n".join(f"- {n}" for n in non_use_cases)
    return out




async def _sync_to_qdrant(db, template, collection: str | None = None):
    from app.core.config import get_settings
    from app.core.vector_store import get_qdrant
    from app.services.embedding_client import get_embedding_client
    from qdrant_client.models import PointStruct, SparseVector

    settings = get_settings()
    collection = collection or settings.qdrant_collection
    qdrant = get_qdrant()
    embed_client = get_embedding_client()

    parts = [template.name, template.description]
    if template.keywords:
        parts.append(" ".join(template.keywords))
    encode_text = "。".join(parts)

    result = await embed_client.embed([encode_text], modes=["dense", "sparse"])
    dense_vec = result["dense"][0]
    sparse_vec = result["sparse"][0]

    # 用模板 ID 派生确定性 UUID，保证 upsert 真正覆盖旧 point
    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, template.id))
    await qdrant.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vec,
                    "sparse": SparseVector(
                        indices=[int(k) for k in sparse_vec.keys()],
                        values=list(sparse_vec.values()),
                    ),
                },
                payload={
                    "template_id": template.id,
                    "name": template.name,
                    "code_type": template.code_type,
                },
            )
        ],
    )

    template.qdrant_point_id = point_id
    template.sync_status = "ok"
    await db.commit()


if __name__ == "__main__":
    cli()
