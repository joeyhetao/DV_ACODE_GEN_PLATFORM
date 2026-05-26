# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

IC verification assistant code generation platform: structured Excel input → deterministic SVA assertion / UVM functional coverage code. Authoritative spec is `PRD.md` (**v3.0**) and `ARCHITECTURE.md` (v2.19). README and CONTRIBUTING are in Chinese; design docs are the source of truth.

**v3.0 user journey reversal (most important reading before changing pipeline / IntentBuilder / contribution code)**: open-ended NL is no longer salvaged by the pipeline. The 5 gates (off-topic / code_type_mismatch / no_matching_template / under_specified / empty_retrieval) all return 422/503 with a structured `detail`. `detail.redirect_to` is the v3.0 mechanism by which the backend tells the frontend where to route the user — `under_specified` routes to `/intent-builder?prefill=...&template_id=...&missing=...`; `no_matching_template` routes to `/contribute/new?description=...&code_type=...` (skipping IntentBuilder entirely); the other three are `null`. Frontend `handleApiError` checks `redirect_to` **first**, before any Modal — read [GeneratePage.tsx handleApiError](frontend/src/pages/Generate/GeneratePage.tsx) for the exact branching. IntentBuilder ([api/v1/intent_builder.py](backend/app/api/v1/intent_builder.py) + [services/intent/conversation.py](backend/app/services/intent/conversation.py)) is a RAG-grounded multi-turn chat with Redis 24h session ([services/intent/session.py](backend/app/services/intent/session.py))—LLM is forced to align user intent to existing templates and is not allowed to invent scenarios. Contribution wizard ([api/v1/contributions.py](backend/app/api/v1/contributions.py)) now takes 4 user fields; backend LLM reverse-derives parameter_defs / Jinja body / keywords via [services/platform/parameter_extractor.py](backend/app/services/platform/parameter_extractor.py) and validates through 3 gates (param_defs naming, Jinja2 renderability, keywords shape) before queuing for admin review.

## Common commands

### Full stack (Docker, recommended)

```bash
# Build frontend bundle once (frontend image expects dist/)
cd frontend && npm install && npm run build && cd ..

# CPU dev stack with hot reload (backend bind-mounts source, --reload)
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.hotreload.yml up -d

# GPU overlays (pick one)
docker compose -f docker-compose.yml -f docker-compose.gpu-linux.yml up -d
docker compose -f docker-compose.yml -f docker-compose.gpu-windows.yml up -d
```

Entrypoints: frontend `http://localhost/`, API `http://localhost/api/`, OpenAPI `http://localhost/api/docs`.

### Backend (host-native, for IDE debugging)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
docker compose up -d postgres redis qdrant embedding_service   # infra only; embedding_service is a separate container (bge-m3), required for RAG
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Required env (see `.env.example`): `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `EMBEDDING_SERVICE_URL`, `JWT_SECRET_KEY` (≥32 chars), `LLM_KEY_ENCRYPTION_SECRET` (64-hex chars). Both secrets are validated at startup and the app refuses to boot with placeholder values.

### Tests

```bash
# Inside the backend container (mocks LLM/Qdrant/PG, no live infra needed)
docker compose exec backend pytest tests/ -v
docker compose exec backend pytest tests/test_pipeline_preview_render.py::test_name -v

# Or host-native
cd backend && pytest tests/ -v

# Off-topic regression corpus — mocked (CI default; tests pipeline routing logic only)
docker compose exec backend pytest tests/test_offtopic_corpus_mocked.py -v
# Off-topic regression corpus — real-LLM mode (requires llm_configs default row; tests bge-m3 classification accuracy end-to-end)
docker compose exec backend pytest tests/test_offtopic_corpus_real_llm.py --real-llm -v
```

`tests/data/offtopic_corpus.yaml` is the contract for "what counts as off-topic vs marginal IC". The mocked suite (`test_offtopic_corpus_mocked.py`) is the always-on regression — when you hit a misclassification, add a sample and let it enforce the routing forever. The real-LLM suite is the periodic accuracy probe against the live embedding model. See `CONTRIBUTING.md` §11 for the growth workflow.

### Template library CLI (`backend/lib_manager.py`)

```bash
python lib_manager.py import [--dir DIR] [--force]   # import YAML → PG + Qdrant; --force skips semantic dedup
python lib_manager.py validate [--dir DIR]
python lib_manager.py rebuild  [--collection NAME]   # re-sync rows with sync_status=syncing into Qdrant (also use after embedding model swap)
python lib_manager.py export   [--dir DIR]           # PG → YAML snapshot
python lib_manager.py backup                         # pg_dump → data/backups/
python lib_manager.py list     [--code-type TYPE]
```

Run inside the backend container so it inherits service URLs.

### Frontend

```bash
cd frontend
npm run dev      # Vite dev server on :5173
npm run build    # tsc + vite build → dist/
npm run lint     # ESLint with --max-warnings 0
```

## Architecture: the determinism contract

**The single most important constraint**: the platform must produce identical output for identical input **for in-domain inputs that contain sufficient information**. The LLM is *only* allowed to choose a template ID and map signal names to template parameters — it never generates code. Code comes from Jinja2 rendering. **Contract v2.11 reversal**: when the input is in-domain but missing required parameters (no signal names, no state list, etc.), the platform now **rejects with HTTP 422** rather than fabricating placeholder code. Read `ARCHITECTURE.md` §1.1 before changing anything in `services/core/` or `services/llm/`.

**Five hard gates before code is rendered**, in order at the top of `pipeline_preview`:

1. **Off-topic gate**: `dense_top1_score(original_intent, code_type) < OFFTOPIC_DENSE_THRESHOLD` → `OffTopicIntentError` → HTTP 422. Threshold calibrated empirically against `backend/tests/data/offtopic_corpus.yaml`; rerun `backend/scripts/calibrate_offtopic_threshold.py` after major template-library changes.
2. **Code-type mismatch gate**: For each non-selected code_type, run a dense_top1_score; if `max(other) - selected ≥ CODE_TYPE_MISMATCH_MARGIN` (default 0.10) → `CodeTypeMismatchError` → 422 with `detail.suggested_code_type`. Typical case: user picks "assertion" but writes "统计 ... 覆盖率".
3. **No-matching-template gate** (post-LLM-step1, pre-step2): `confidence_source == "rag_fallback"` (LLM step1 explicitly rejected all candidates by returning `"none"`) → `NoMatchingTemplateError` → HTTP 422 with `detail.redirect_to="/contribute/new?description=...&code_type=..."`. **FIX-9** removed the previous `rag_candidates[0]["score"] < NO_MATCH_SCORE_THRESHOLD` co-condition because cross-encoder reranker can give 1.0 to semantically unrelated templates on lexical overlap (e.g., `req` keyword matching `sva_timing_max_delay_v1`), which would suppress the gate even after LLM correctly returned `none`. `top_score` is still logged for monitoring; `no_match_score_threshold` setting is kept but no longer participates in gate decision. This gate fires **before** under_specified — a clearly unknown scenario goes directly to the contribution page, skipping the 5-round IntentBuilder loop. Toggle: `NO_MATCH_GATE_ENABLED`.
4. **Empty retrieval gate** (post-RAG): three-stage retrieval returned no candidates AND keyword supplement also empty → `EmptyRetrievalError` → **HTTP 503** (infrastructure issue — Qdrant / embedding service / empty template library). Distinct from off-topic; SRE looks at this, not the user.
5. **Under-specified intent gate** ([`_detect_under_specified`](backend/app/services/core/pipeline.py), after `_map_params_with_source`): any required parameter resolved to a low-confidence source → `UnderSpecifiedIntentError` → HTTP 422 with `detail.missing_params=[{name, description, expr_type, role_hint}, ...]`. Low-confidence = `source ∈ {placeholder, semantic_fallback}` OR `source==llm AND value ∈ {"", 0, "0", "null", literal param name}`. The LLM is **not allowed** to fake-fill parameters with stubs.

Each gate has an env switch (`OFFTOPIC_GATE_ENABLED` / `CODE_TYPE_MISMATCH_GATE_ENABLED` / `NO_MATCH_GATE_ENABLED` / `UNDER_SPECIFIED_GATE_ENABLED`) for emergency rollback. All exception classes are caught in [api/v1/generate.py](backend/app/api/v1/generate.py)'s except chain in this exact order — **don't reorder**, don't generalize to `except ValueError` (it'll mask the structured detail).

**v3.0 redirect_to field on error detail**: every gate's `detail` carries `redirect_to: str | None`. `under_specified` routes to `/intent-builder?prefill=...&template_id=...&missing=...`; `no_matching_template` routes to `/contribute/new?description=...&code_type=...`; off_topic / code_type_mismatch / empty_retrieval return `null`. Frontend `handleApiError` reads `redirect_to` first via `'redirect_to' in detail` type guard — if present, `navigate(detail.redirect_to)` without any Modal. Backend constructs the URL inside the exception class `__init__` using `urllib.parse.quote` (Chinese-safe). Don't move the redirect URL construction to the endpoint layer; the exception class owns it.

**v3.0 IntentBuilder (RAG-grounded multi-turn chat)**: `POST /intent-builder/chat` accepts `{session_id, user_message, code_type}`. session_id is mintable (empty → server mints UUID4). Each turn: load Redis session (`intent_builder_session:{user_id}:{session_id}`, TTL 24h) → run RAG retrieval on `accumulated_intent or user_message` → inject top-3 candidates into LLM system prompt → call `llm.chat(messages)` → extract `<<intent>>...<<end>>` segment via regex → save session → respond. The LLM is constrained to ONLY align to existing templates (no inventing scenarios) via [`_build_system_prompt`](backend/app/services/intent/conversation.py). After 5 turns with all top-1 RAG scores < 0.5, response sets `suggest_contribute=true` so frontend shows "Contribute new template" button. Session has no explicit close endpoint — 24h TTL handles cleanup.

**v3.0 simplified contribution submission**: `POST /contributions` requires only 4 fields (`code_type / template_name / description / demo_code`). Backend immediately calls [`derive_parameters_from_demo`](backend/app/services/platform/parameter_extractor.py) which: LLM extracts parameter list + Jinja2-fies the code + suggests keywords/subcategory/protocol → 3-gate validation (param_defs naming, Jinja2 strict-render, keywords shape) → success enqueues `pending_review`, failure returns 422 `contribution_parse_failed` with `stage` and `reason`. Original user code preserved in `contribution.original_row_json["user_demo"]` for admin reference. Admin three-column review UI: left=user submission (RO), middle=LLM-derived Jinja2 body (editable), right=LLM-derived parameter_defs JSON + keywords + subcategory + protocol (editable). PATCH endpoint extended so admins can edit any field at any status (contributors still locked to `pending`/`needs_revision`).

Four-layer determinism guard:

1. **Cache** — Redis `gen:{llm_config_id}:{template_id}:{version}:{sha256(sorted_params)}` short-circuits everything (TTL 90d). intent_cache 同样按 `llm_config_id` 分桶（`intent_cache:{llm_config_id}:{intent_hash}`，TTL 30d），并存 `params_fingerprint` —— 命中时 pipeline 用 `template_params_fingerprint(current_template.parameters)` 与缓存值比对，schema 漂移就 bypass 缓存走完整流水线。空 config_id 用 `"_"` 占位（测试 mock 兼容）。
2. **Retrieval** — `bge-m3` (pinned model) + Qdrant hybrid stage1 (dense+sparse RRF) + stage3 cross-encoder rerank. **Stage2 ColBERT 当前实际 bypass**：[main.py `_init_qdrant_collection`](backend/app/main.py) 只 provisions `dense` + `sparse` 两个命名向量，[stage1_hybrid.py:62](backend/app/services/rag/stage1_hybrid.py#L62) 读 `r.vector.get("colbert")` 永远为 None，[stage2_colbert.py:25-27](backend/app/services/rag/stage2_colbert.py#L25-L27) 见 None 时透传 RRF 分数。代码和 embedding service 都还在生产 colbert 向量，重启 ColBERT 只需补齐 Qdrant collection schema + reindex（成本高，故未做）。改 RAG 逻辑前务必看 stage1 → stage2 → stage3 三个文件的实际行为，不要假设 ColBERT 在 work。
3. **Parsing** — `temperature=0` + tool-calling / 2-step text + Pydantic schema.
4. **Rendering** — Jinja2 `StrictUndefined`; missing params raise, never silently render `''`.

Consequence: **never call an LLM from `app/services/core/`**. LLM calls live in `services/llm/` and are invoked by the pipeline orchestrator, not by core/render/cache.

## The generation pipeline

`app/services/core/pipeline.py` is the *only* entry point for generation. Both the `/generate` HTTP endpoint and the Celery batch worker call the same `pipeline_preview` / `pipeline_render` (or the legacy one-shot `run_pipeline` wrapper). When adding a step, edit this file — do not bypass it from endpoints.

Two-step flow (UI plan 3, see ARCHITECTURE §3.15–3.16):

- `pipeline_preview(PipelineInput) → PreviewResult` does **off-topic gate** → **code-type mismatch gate** → normalize → intent-cache → RAG → keyword-supplement → LLM step1 (pick id) → LLM step2 (fill params) → multi-source param mapping → **under-specified gate**. Returns each parameter tagged with one of 6 `source`s: `llm` / `regex` / `signal_list` / `default` / `semantic_fallback` / `placeholder`. Frontend `ConfirmationPanel` + `ParametersForm` render these with colored badges.
- `pipeline_render(RenderInput) → (code, cache_hit)` renders the user-confirmed params with Jinja2, writes generation cache, saves intent history.
- `quick_render=True` on a preview means intent-cache hit; the frontend skips the confirmation panel.

**Recovery chain** (intra-pipeline — applies *before* the under-specified gate decides whether to reject):
RAG empty → keyword supplement (DB scan over `template.keywords`) → LLM picks none/invalid → take RAG top-1 (and rewrite confidence to RAG score with `confidence_source="rag_fallback"`) → LLM step2 returns nothing → regex `_extract_params_from_intent` → role-hint signal-list mapping → template `default` field → semantic fallback (`group_name`/`signal`/`state_list`/`bins_expr`). After all this, any required param still landing on `placeholder` or `semantic_fallback` (or LLM-with-trivial-value) **trips the under-specified gate** — system does NOT silently render with placeholders.

Param source taxonomy (`_map_params_with_source`):

| Source | What it means | High-confidence? |
|---|---|---|
| `llm` | LLM step2 extracted from user intent text | Yes, unless value is `""` / `0` / `"0"` / `"null"` / literal param name |
| `regex` | `_extract_params_from_intent` matched explicit pattern in original text | Yes |
| `signal_list` | Role-hint / position match against user-provided `PipelineInput.signals` | Yes |
| `default` | Either `PipelineInput.{clk,rst,rst_polarity}` (form input) or template YAML's `default` field | Yes |
| `semantic_fallback` | System-fabricated guess (`state_list="IDLE, ACTIVE, DONE"`, etc.) | **No** — trips gate |
| `placeholder` | Step 6 last-ditch: param name as literal value | **No** — trips gate |

Precedence within `_map_params_with_source`: **llm > regex > signal_list > default > semantic_fallback > placeholder**. Don't merge `semantic_fallback` back into `default` — they have to be distinct labels for the under-specified gate to work.

**Last-line defense — `expr_type` sanitize/validate** (pipeline.py step 7, after the precedence resolution):
Each `template.parameters[i].expr_type` drives a final pass over the resolved value, regardless of which source produced it:

- `sv_identifier` / `sv_identifier_list` → `sanitize_sv_identifier` from `services/core/identifier.py` rewrites the value to a legal SV ident; flags `sanitized=True` on the param meta.
- `sv_boolean_expr` / `sv_bins_expr` → validators in `services/core/expr_validator.py` (`EXPR_TYPE_DISPATCH`) check format; failures attach `validation_error` (value untouched).
- `integer` / `free_text` / unset → skipped (Pydantic and the frontend handle these).

Legacy templates without `expr_type` fall back to the `IDENTIFIER_PARAMS` whitelist (by parameter name) for back-compat. When adding a new template parameter, declare `expr_type` explicitly — don't rely on the name-based fallback.

## Code-type registry (no-Python-code extension)

`app/services/registry.py` (`CodeTypeRegistry`) loads `backend/data/code_types/*.yaml` at startup. Each YAML defines: Excel sheet name, schema file path, signal roles, normalization sentence pattern, scenario templates file, subcategories. **Adding a new code type = 3 YAML files (code_types + schemas + scenarios), zero Python changes**:

- `excel_parser.py` reads column layout from `data/schemas/*.yaml` per code type.
- `intent/normalizer.py` injects sentence patterns from registry into the LLM system prompt at runtime.
- `intent/builder.py` loads scenario sentence templates from registry.
- `templates.code_type` ENUM and Qdrant payload `code_type` must match a registered id.

Don't hardcode `if code_type == "assertion"` branches — go through the registry.

## LLM client abstraction

`app/services/llm/factory.py` reads `llm_configs` table (rows are seeded via Admin UI; `is_default=true` row wins) and instantiates either `AnthropicClient` or `OpenAICompatClient`. Anthropic uses native tool calling; OpenAI-compatible uses the **two-step plain-text** path (`_step1_select_id` + `_step2_fill_params`) to survive thinking-model `reasoning_tokens` consumption (GLM-4.7, DeepSeek-R1). The schema field `output_mode` is reserved for future routing — do not assume it gates behavior today.

**Thinking-disable contract for GLM-4.7-class endpoints** (Zhipu OpenAI-compatible): the three LLM calls are tuned per-call. `normalize_intent` and `_step1_select_id` are hardcoded to disable thinking; `_step2_fill_params` is **runtime-configurable via `llm_configs.step2_disable_thinking`** (Admin UI Switch).

| Call | `extra_body` | `max_tokens` | Rationale |
|---|---|---|---|
| `normalize_intent` | `{"thinking":{"type":"disabled"}}` (hardcoded) | 512 | Pure sentence rewriting per fixed rules — zero reasoning value |
| `_step1_select_id` | `{"thinking":{"type":"disabled"}}` (hardcoded) | 64 | Pick-from-list classifier — discriminators already in system prompt; RAG fallback in `pipeline.py` is the safety net for any misclassification |
| `_step2_fill_params` | conditional: `{"thinking":{"type":"disabled"}}` if `step2_disable_thinking=true` (default), else not set | 2048 (off) / 1024 (on) | **Default off**: empirical p50 ~3s. **On (legacy)**: 12-249s variance, occasional `finish=length`. Toggle off when FSM `state_list` / `bins_expr` accuracy needs to be validated against thinking baseline. |

`extra_body={"thinking":{"type":"disabled"}}` is the Zhipu native parameter (the OpenAI SDK passes it through). DeepSeek-style `chat_template_kwargs.enable_thinking=false` only works on self-hosted vLLM and is NOT used here. When swapping in a non-thinking model, the `extra_body` is silently ignored — no behavior change needed.

Every LLM call emits `[Timing] llm=<name> ms=<n> reasoning_tokens=<n> thinking=<on/off>` so you can verify at runtime whether thinking actually disabled (`reasoning_tokens=0` = confirmed off). Use this to debug if a model variant silently ignores the `extra_body`.

API keys are AES-256-GCM encrypted with `LLM_KEY_ENCRYPTION_SECRET`. GET only returns a hint; PUT with empty `api_key` keeps the existing ciphertext.

Switching / 创建 / 删除 / 修改 default 配置的 LLM 都会**主动 flush 两层缓存** (`gen:*` + `intent_cache:*`) —— 实现在 [admin_llm.py](backend/app/api/v1/admin_llm.py) 的 set_default / create_config / update_config / delete_config 端点 commit 后调用 [`invalidate_all_llm_caches()`](backend/app/services/core/cache.py)。即便不同 LLM 的缓存通过 `llm_config_id` 维度天然分桶，flush 仍然必要：保证切换后新写入的缓存不会与旧条目并存 30/90 天。`llm_configs.is_default` 有 partial unique index（migration 004）兜底，防止多行同时 True 把 `factory.get_default_llm_client` 打成 500。

## Data layout

- **PostgreSQL** = source of truth (templates, users, generation history, batch jobs, llm_configs, contributions, audit logs). `templates.qdrant_point_id` links to Qdrant; `sync_status ∈ {ok, syncing, sync_error}` flags cross-store drift — `lib_manager.py rebuild` re-pushes any row in `syncing` state to Qdrant and flips it back to `ok`.
- **Qdrant** = derived (rebuildable from PG). Single collection `templates` with named vectors `dense` (1024-d cosine) + `sparse` (RRF). The architecture doc mentions `colbert` as a multi-vector field; the actual `_init_qdrant_collection` in `app/main.py` provisions only `dense` + `sparse` — verify before assuming colbert is live in PG-side init.
- **Redis** = caches only. `intent_cache:*` (semantic) and `cache:*` (template+params hash) are both LRU-evictable; `maxmemory 2gb / allkeys-lru` set in compose.

Template Qdrant point IDs are **deterministic UUIDs** (`uuid.uuid5(NAMESPACE_DNS, template.id)`) — never use `uuid4()`, or `lib_manager.py rebuild` will accumulate duplicate points and pollute retrieval.

## Backend layout

```
backend/app/
├── api/v1/        # endpoints flat (no endpoints/ subdir): auth, generate, batch,
│                  # templates, admin, admin_llm, contributions, notifications,
│                  # intent_builder; router.py mounts all under /api/v1
├── core/          # config, database, security (JWT), vector_store (qdrant client)
├── models/        # SQLAlchemy ORM
├── schemas/       # Pydantic request/response (TemplateSelectionOutput etc.)
├── services/
│   ├── core/      # pipeline.py, renderer.py, cache.py, dedup.py, identifier.py,
│   │              # expr_validator.py — DETERMINISTIC ZONE, NO LLM
│   ├── rag/       # engine.py, stage1_hybrid, stage2_colbert, stage3_reranker
│   ├── llm/       # base, anthropic_client, openai_compat_client, factory
│   ├── intent/    # normalizer, builder, preflight, history (4 layers per ARCHITECTURE §3.11)
│   ├── parser/    # Excel parser (schema-driven from data/schemas/)
│   ├── platform/  # audit_service, backup_service, contribution_service
│   ├── embedding_client.py
│   └── registry.py
├── tasks/         # Celery: celery_app, batch_tasks
└── data/          # YAML configs: code_types/, schemas/, scenarios/
```

Frontend pages mirror the backend domains (Generate, Batch, Library, IntentBuilder, MyContributions, Admin, Login). Vite proxies `/api` to the backend during `npm run dev`.

## House rules

- **Conventional Commits** (`feat(engine):`, `fix(llm):`, `docs(template):` …). Scopes used: `engine`, `llm`, `template`, `api`, `frontend`, `db`, `deploy`, `auth`. Branch off `develop`, not `main`. Squash-merge `feature/*` → `develop`, merge-commit `release/*` → `main`. See CONTRIBUTING.md §4–§7.
- **Any change in `services/core/` requires a unit test.** Mocks for LLM/Qdrant/PG are fine — see `tests/test_pipeline_preview_render.py` for the mocking style.
- **Template changes** must update both YAML in `backend/template_library/` and DB (run `lib_manager.py import`); the YAML is the version-controlled source.
- Don't put backend secrets in `.env` commits. `JWT_SECRET_KEY` and `LLM_KEY_ENCRYPTION_SECRET` are validated; weak values prevent boot.
- After editing the migration tree: `alembic upgrade head`. Initial schema is consolidated in `migrations/versions/001_initial_schema.py`.

## 4-agent 工作流触发规则

**在动手实现之前**，先判断此次改动是否满足以下任一条件。如果满足，立刻停下并提醒用户先运行 `/plan-ticket`，不要直接在 `develop` 上写代码。

| 改动类型 | 判断依据 |
|---|---|
| 新增或修改 pipeline 闸（gate）逻辑 | 涉及 `services/core/pipeline.py` 的异常类或闸判断块 |
| 新增 API 端点或修改现有端点的错误响应结构 | `api/v1/` 下新增路由，或改 `detail.type` / `redirect_to` 字段 |
| 改变用户跳转路径 | `GeneratePage.tsx` / `IntentBuilderPage.tsx` 等前端路由逻辑 |
| 涉及核心契约（ARCHITECTURE.md §1.1） | 确定性引擎、闸顺序、参数源优先级、缓存 key 结构等 |
| 改动预期影响 test-manual §2/§4/§5 至少一个小节 | 新测试场景、新错误类型、新跳转路径 |

**触发后的标准话术**（在回复里明确说，不要直接开始写代码）：

> 这个改动涉及 [具体触发条件]，属于需要走 4-agent 完整流程的规模：
> 1. `/plan-ticket <ID> <意图>` — 生成 spec，明确 `docs_targets`
> 2. `scripts/worktree-init.sh <ID>` — 创建 feature + docs 双 worktree
> 3. feature session 实现 → `/commit`（自动派生 Handoff JSON）
> 4. docs session `/update-docs` — 同步 PRD / ARCHITECTURE / test-manual
>
> 是否现在运行 `/plan-ticket`？

**例外（不触发，可直接实现）**：纯 bug fix（不改闸逻辑）、前端 UI 样式/文案调整、补单测（不新增被测逻辑）、文档专项任务（已在 docs/ 分支）。
