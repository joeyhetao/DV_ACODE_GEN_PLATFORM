"""共享 pytest 配置：

- `--real-llm` CLI flag 控制是否跑标记 `@pytest.mark.real_llm` 的回归测试
- `--real-embedding` CLI flag 控制是否跑标记 `@pytest.mark.real_embedding` 的回归测试
- `corpus_samples` fixture 提供 off-topic 语料 YAML 的解析结果
- `load_template_corpus_cases` 提供模板选择语料 YAML 的解析结果
"""
from __future__ import annotations
from pathlib import Path
import pytest
import yaml


_CORPUS_PATH = Path(__file__).parent / "data" / "offtopic_corpus.yaml"
_TEMPLATE_CORPUS_PATH = Path(__file__).parent / "data" / "template_selection_corpus.yaml"
_CONFUSION_CORPUS_PATH = Path(__file__).parent / "data" / "template_confusion_corpus.yaml"


def pytest_addoption(parser):
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help="enable real-LLM regression tests (calls live LLM via configured llm_configs default)",
    )
    parser.addoption(
        "--real-embedding",
        action="store_true",
        default=False,
        help="enable real-embedding regression tests (calls live Qdrant/embedding_service)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_llm: marks tests requiring a live LLM (skipped unless --real-llm passed)",
    )
    config.addinivalue_line(
        "markers",
        "real_embedding: marks tests requiring live Qdrant + embedding_service (skipped unless --real-embedding passed)",
    )


def pytest_collection_modifyitems(config, items):
    skip_llm = pytest.mark.skip(reason="real-LLM tests disabled; pass --real-llm to enable")
    skip_emb = pytest.mark.skip(reason="real-embedding tests disabled; pass --real-embedding to enable")
    for item in items:
        if "real_llm" in item.keywords and not config.getoption("--real-llm"):
            item.add_marker(skip_llm)
        if "real_embedding" in item.keywords and not config.getoption("--real-embedding"):
            item.add_marker(skip_emb)


def _load_corpus() -> dict:
    with _CORPUS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_template_corpus() -> dict:
    with _TEMPLATE_CORPUS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_template_corpus_cases(segment: str = "correct_mapping") -> list[dict]:
    """展开模板选择语料 YAML 为参数化 input 列表。每条 case 直接映射为一个测试用例。"""
    raw = _load_template_corpus().get(segment, []) or []
    return [{**s, "_pid": s["id"]} for s in raw]


def _load_confusion_corpus() -> dict:
    with _CONFUSION_CORPUS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_confusion_corpus_cases(segment: str = "confusion_pairs") -> list[dict]:
    """展开混淆对语料 YAML 为参数化 input 列表。每条 case 含 correct_template +
    confusion_template，给 mock / real-llm 套件复用。"""
    raw = _load_confusion_corpus().get(segment, []) or []
    return [{**s, "_pid": s["id"]} for s in raw]


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
