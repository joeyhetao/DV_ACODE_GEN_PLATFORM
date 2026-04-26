from __future__ import annotations
import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse


BACKUP_DIR = Path("/app/backups")


async def create_pg_backup(db_url: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = BACKUP_DIR / f"dv_platform_{ts}.dump"

    parsed = urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    user = parsed.username or ""
    password = parsed.password or ""
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    dbname = parsed.path.lstrip("/")

    if not dbname:
        raise ValueError("无法从 DATABASE_URL 解析数据库名称")

    proc = await asyncio.create_subprocess_exec(
        "pg_dump",
        "-h", host, "-p", port, "-U", user, "-d", dbname,
        "-F", "c", "-f", str(out_file),
        env={**os.environ, "PGPASSWORD": password},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump 失败: {stderr.decode()}")

    return out_file
