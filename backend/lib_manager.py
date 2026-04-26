#!/usr/bin/env python3
"""
lib_manager.py — 模板库管理 CLI

用法:
  python lib_manager.py import    [--dir DIR] [--force]
  python lib_manager.py validate  [--dir DIR]
  python lib_manager.py rebuild   [--collection NAME]
  python lib_manager.py export    [--dir DIR]
  python lib_manager.py backup
  python lib_manager.py list
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
                    description=data.get("description", ""),
                    parameters=data.get("parameters", []),
                    template_body=data["template_body"],
                    maturity=data.get("maturity", "draft"),
                    related_ids=data.get("related_ids"),
                    created_by="lib_manager",
                    sync_status="pending",
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


# ─── validate ────────────────────────────────────────────────────────────────

@cli.command("validate")
@click.option("--dir", "lib_dir", default=str(TEMPLATE_LIBRARY_DIR))
def cmd_validate(lib_dir: str):
    """验证 YAML 模板文件语法"""
    from app.services.core.renderer import validate_template_syntax

    files = list(Path(lib_dir).rglob("*.yaml"))
    errors = 0
    for f in files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            required_keys = ["id", "name", "code_type", "template_body"]
            for key in required_keys:
                if key not in data:
                    raise ValueError(f"缺少必填字段: {key}")
            validate_template_syntax(data["template_body"])
            click.echo(f"  [OK] {f.name}")
        except Exception as e:
            click.echo(f"  [ERROR] {f.name}: {e}", err=True)
            errors += 1

    if errors:
        click.echo(f"\n{errors} 个文件验证失败", err=True)
        sys.exit(1)
    else:
        click.echo(f"\n全部 {len(files)} 个文件验证通过")


# ─── rebuild ─────────────────────────────────────────────────────────────────

@cli.command("rebuild")
@click.option("--collection", default=None, help="Qdrant collection 名称")
def cmd_rebuild(collection: str | None):
    """重建 Qdrant 向量索引（同步所有 sync_status=pending 的模板）"""
    asyncio.run(_rebuild(collection))


async def _rebuild(collection: str | None):
    from app.core.database import AsyncSessionLocal
    from app.models.template import Template
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Template).where(Template.is_active == True, Template.sync_status == "pending")
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


# ─── helpers ─────────────────────────────────────────────────────────────────

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

    point_id = str(uuid.uuid4())
    await qdrant.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=point_id,
                vector={
                    "dense": dense_vec,
                    "sparse": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"],
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
    template.sync_status = "synced"
    await db.commit()


if __name__ == "__main__":
    cli()
