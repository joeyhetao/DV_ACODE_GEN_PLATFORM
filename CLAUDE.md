# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

IC verification assistant code generation platform: structured Excel input → deterministic SVA assertion / UVM functional coverage code. Authoritative spec is `PRD.md` (v2.9) and `ARCHITECTURE.md` (v2.14). README and CONTRIBUTING are in Chinese; design docs are the source of truth.

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
docker compose up -d postgres redis qdrant          # infra only
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

# Off-topic regression corpus — real-LLM mode (requires llm_configs default row)
docker compose exec backend pytest tests/test_offtopic_corpus_real_llm.py --real-llm -v
```

`tests/data/offtopic_corpus.yaml` is the contract for "what counts as off-topic vs marginal IC". When you hit a misclassification, add a sample and let the mock suite enforce it forever. See `CONTRIBUTING.md` §11 for the growth workflow.

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

**The single most important constraint**: the platform must produce identical output for identical input **for in-domain inputs**. The LLM is *only* allowed to choose a template ID and map signal names to template parameters — it never generates code. Code comes from Jinja2 rendering. Read `ARCHITECTURE.md` §1.1 before changing anything in `services/core/` or `services/llm/`.

**Off-topic inputs are explicitly rejected with HTTP 422**, not silently fall back to placeholder code. The gate lives at the top of `pipeline_preview`: `dense_top1_score(original_intent, code_type) < offtopic_dense_threshold` → `OffTopicIntentError`. Threshold is calibrated empirically against `backend/tests/data/offtopic_corpus.yaml`; rerun `backend/scripts/calibrate_offtopic_threshold.py` after major template-library changes.

Four-layer determinism guard:

1. **Cache** — Redis `cache:{sha256(template_id|version|sorted_params)}` short-circuits everything (TTL 90d).
2. **Retrieval** — `bge-m3` (pinned model) + Qdrant 3-stage RRF/ColBERT/cross-encoder.
3. **Parsing** — `temperature=0` + tool-calling / 2-step text + Pydantic schema.
4. **Rendering** — Jinja2 `StrictUndefined`; missing params raise, never silently render `''`.

Consequence: **never call an LLM from `app/services/core/`**. LLM calls live in `services/llm/` and are invoked by the pipeline orchestrator, not by core/render/cache.

## The generation pipeline

`app/services/core/pipeline.py` is the *only* entry point for generation. Both the `/generate` HTTP endpoint and the Celery batch worker call the same `pipeline_preview` / `pipeline_render` (or the legacy one-shot `run_pipeline` wrapper). When adding a step, edit this file — do not bypass it from endpoints.

Two-step flow (UI plan 3, see ARCHITECTURE §3.15–3.16):

- `pipeline_preview(PipelineInput) → PreviewResult` does **off-topic dense gate** → normalize → intent-cache → RAG → keyword-supplement → LLM step1 (pick id) → LLM step2 (fill params) → multi-source param mapping. Returns each parameter tagged with one of 5 `source`s: `llm` / `regex` / `signal_list` / `default` / `placeholder`. Frontend `ConfirmationPanel` + `ParametersForm` render these with colored badges.
- `pipeline_render(RenderInput) → (code, cache_hit)` renders the user-confirmed params with Jinja2, writes generation cache, saves intent history.
- `quick_render=True` on a preview means intent-cache hit; the frontend skips the confirmation panel.

**Fallback chain** (every step has one — the system is contractually obliged to always produce code):
RAG empty → keyword supplement (DB scan over `template.keywords`) → LLM picks none/invalid → take RAG top-1 (and rewrite confidence to RAG score with `confidence_source="rag_fallback"`) → LLM step2 returns nothing → regex `_extract_params_from_intent` → role-hint signal-list mapping → template `default` → semantic fallback (`group_name`/`signal`/`state_list`/`bins_expr`) → required-param placeholder = parameter name itself.

Param precedence (mirrored in `_map_params_with_source`): **llm > regex > signal_list > default > placeholder**.

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

Switching the default model **flushes both `intent_cache:*` and `cache:*`** because new models can return different `(template_id, params)` for the same input — this is intentional for determinism.

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
