"""共享 pytest 配置：

- `--real-llm` CLI flag 控制是否跑标记 `@pytest.mark.real_llm` 的回归测试
- `corpus_samples` fixture 提供 off-topic 语料 YAML 的解析结果
"""
from __future__ import annotations
from pathlib import Path
import pytest
import yaml


_CORPUS_PATH = Path(__file__).parent / "data" / "offtopic_corpus.yaml"


def pytest_addoption(parser):
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help="enable real-LLM regression tests (calls live LLM via configured llm_configs default)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_llm: marks tests requiring a live LLM (skipped unless --real-llm passed)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--real-llm"):
        return
    skip = pytest.mark.skip(reason="real-LLM tests disabled; pass --real-llm to enable")
    for item in items:
        if "real_llm" in item.keywords:
            item.add_marker(skip)


def _load_corpus() -> dict:
    with _CORPUS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_corpus_samples(segment: str) -> list[dict]:
    """展开 YAML 语料为参数化 input 列表。

    - off_topic 段：每条 sample 会按 code_types 列表展开为 N 个独立 case
    - marginal_ic 段：每条 sample 直接当作一个 case
    """
    raw = _load_corpus().get(segment, []) or []
    if segment == "off_topic":
        expanded: list[dict] = []
        for s in raw:
            code_types = s.get("code_types") or [s.get("code_type", "assertion")]
            for ct in code_types:
                expanded.append({**s, "code_type": ct, "_pid": f"{s['id']}__{ct}"})
        return expanded
    return [{**s, "_pid": s["id"]} for s in raw]
