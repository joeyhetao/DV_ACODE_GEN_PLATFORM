# Changelog

All notable changes to DV_ACODE_GEN_PLATFORM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.4.0] - 2026-05-07

### Added
- **方案 3 两步式 UI 确认面板**（核心 UX 重构）：
  - 后端：`run_pipeline` 拆为 `pipeline_preview` + `pipeline_render` 两段；新增 `/api/v1/generate/preview` 端点（返回模板推荐 + 参数预填充含来源标识）；增强 `/api/v1/generate/render` 端点（用户确认参数后渲染 + 写 GenerationRecord + 写缓存）
  - `_map_params_with_source` 替代 `_map_params`，每参数标 5 类源（`signal_list` / `regex` / `llm` / `default` / `placeholder`）
  - 新增 `confidence_source` 字段（`llm_step1` / `rag_fallback` / `intent_cache`），解决附录 B.4 的 confidence 显示陷阱
  - 前端：新增 `ConfirmationPanel` + `ParametersForm` + `SourceBadge` 组件，意图缓存命中（`quick_render=true`）时自动跳过确认面板；红色占位符徽标禁用「生成代码」按钮强制用户填值；切换 RAG 候选模板自动重映射参数
  - 既有 `/generate` 端点保留兼容（内部调 preview+render），batch_tasks 零变更
  - 新增 4 个 pipeline_render 集成测试 + 8 个 `_map_params_with_source` 单测，共 12 测全过
- **LLM thinking-model 支持**：OpenAI 兼容客户端拆为"选模板 + 填参数"两步纯文本调用（`_step1_select_id` + `_step2_fill_params`，`max_tokens=4096`），规避 GLM-4.7 / DeepSeek-R1 reasoning_tokens 截断问题；切换默认模型时自动清空 `intent_cache:*` 与 `cache:*`
- **Pipeline 兜底链**：RAG 召回不足时基于 `template.keywords` 与意图原文做小写子串匹配补充召回；LLM 选不出模板时退化为 RAG 第一候选（`confidence_source=rag_fallback`）；LLM 填不出参数时退化为正则提取 + signal-list role-hint + 模板 default + 参数名占位
- **正则参数提取扩展**（pipeline.py `_extract_params_from_intent`）：从只覆盖 5 个 coverage 字段扩展到额外覆盖 11 个 assertion 参数（module_name / max_cycles / max_delay / init_value / enable / data / valid / ready / target / start_event / end_event / state_sig），让"模块名为 X，使能信号为 Y"这类半结构化句式不再依赖 LLM Step2 语义映射
- **首份单元测试** `backend/tests/test_extract_params.py` + `tests/test_pipeline_preview_render.py`：22 + 12 个测试覆盖既有 coverage 提取（回归保护）+ 新增 assertion 提取 + 反例（避免误提取）+ §1.1/§1.4/§1.6 完整集成场景。容器内跑 `docker compose exec backend pytest tests/ -v`
- **用户自助注册**：登录页注册标签页 + 公开 `POST /api/v1/auth/register` 端点（默认 role=普通用户），库管理员/平台管理员仍由超管在用户管理页升级
- **CLAUDE.md 项目级 Claude Code 指南**：确定性契约、生成管线两步流、code-type 注册机制、LLM 客户端抽象、PG/Qdrant/Redis 数据分工、house rules（Conventional Commits + scope 列表 + core 单测要求）
- **WSL2 启动手册** `docs/startup-wsl.md`：VS Code Remote-WSL 工作流、`gh auth login` / 手动 PAT 两种凭据方案、Windows Terminal `-w 0` 新标签命令与 profile 固化、9P 协议性能与 dubious ownership 注意事项
- 部署文档拆分为两份独立分册：
  - `docs/deployment-dev-windows.md`：Win11 本机开发部署（含 .wslconfig 优化、hot reload、bind mount、Docker daemon 崩溃处置、HF 模型 VHDX 路径等）
  - `docs/deployment-prod-linux.md`：Linux 公司内网生产部署（含受限外网 mirror 配置、模型预下载与 bind mount、备份与恢复演练、安全加固清单 11 项）
- 平台功能测试手册 `docs/test-manual.md`（11 章 + 2 附录）：
  - 10 个模板逐一的高置信度命中用例（含输入文本 / 期望模板 / 期望代码片段 / 后端验证）
  - 4 对易混淆模板对照测试（握手 stable vs timeout、断言 vs 覆盖率等）
  - 6 个低置信度兜底场景（无关意图 / 极简输入 / 英文 / code_type 不匹配 / 必填参数缺失 / RAG 召回 0）
  - 缓存层 3 个用例 + 模板贡献 3 个完整流程 + 批量生成 + 意图构建器 + 用户/LLM/通知管理
  - **附录 B：5 项已知功能-UI gap 清单**（贡献无去重、切换 LLM 不清缓存、删默认 LLM 无防呆、后端不强制 confidence_threshold、ColBERT Stage2 实质退化）

### Changed
- ARCHITECTURE v2.13→v2.14、PRD v2.8→v2.9：补齐 §3.15 拆 `pipeline_preview` / `pipeline_render`、新增 §3.15.5 expr_type 校验/规范化层占位与 §3.16 两步式确认面板、§5.1 端点表对齐 `/preview` `/auth/register` `/auth/me` `/health`；PRD §3.6 新增自助注册说明、§6.1 主流程改为统一两步式（preview → 确认面板 → render，含 quick_render 短路）
- 项目工作目录从 `D:\dev\DV_ACODE_GEN_PLATFORM` 迁移到 WSL2 内部 `/home/Administrator/DV_ACODE_GEN_PLATFORM/`，`docs/deployment-dev-windows.md` 与 `docs/startup-wsl.md` 同步路径
- `docs/deployment.md` 由 680 行重写为 ~50 行索引文档，仅承载场景对比表与跳转
- README.md 文档索引表新增 4 条文档链接（3 份 deployment + test-manual）
- docker-compose.yml：9 个服务启用 `restart: unless-stopped`；qdrant healthcheck 改为 TCP 探测；hotreload override 增加 `frontend/dist` bind mount 让前端改动免重建容器即时生效
- nginx 入口启用 Docker 内置 resolver `127.0.0.11 valid=10s` + 变量化 `proxy_pass`，解决 backend 容器重启后 nginx 缓存旧 IP 导致 502；前端容器对 `index.html` 强制 `no-cache` 响应头，确保 hash 化 bundle 升级后浏览器立即拉新
- 前端 axios 超时延长至 thinking-model 容许范围（避免请求被前端提前 abort）
- FastAPI docs/redoc/openapi.json 与 health 端点统一挂到 `/api/` 前缀（与反代路径一致）

### Fixed
- RAG Stage3 graceful degradation：reranker 异常时回落到 Stage2 排序，不再让整条流水线 502；同时兼容 qdrant-client 1.12 的 `query_points` API 变更
- `lib_manager rebuild` 用 `uuid.uuid5(NAMESPACE_DNS, template.id)` 派生确定性 Qdrant point ID，修复重复 rebuild 累积重复 point 污染检索的 bug

---

## [0.3.0] - 2026-04-27

### Added
- 部署手册 `docs/deployment.md`，覆盖 Docker Compose 完整栈启动、环境变量配置、嵌入服务 GPU/CPU 选择、首次初始化流程
- `/update-docs` 与 `/update-specs` 两个 slash command 工具骨架，支持按真实项目状态自动同步 README/CHANGELOG/CONTRIBUTING 与 PRD/ARCHITECTURE

### Changed
- ARCHITECTURE.md 与首版平台实现对齐：补全 Qdrant 三阶段 RAG、独立嵌入服务、LLM 多模型工厂、Celery 任务队列等模块
- CONTRIBUTING.md 中的 docker-compose 路径修正为根目录形式（取消废弃的 `deploy/` 路径）
- README/CHANGELOG/CONTRIBUTING 整体与项目当前实现状态同步

---

## [0.2.0] - 2026-04-26

### Added
- 完整后端实现：FastAPI 路由层（auth / generate / templates / batch / admin / intent_builder / notifications / contributions）
- 三阶段 RAG 检索流水线：混合检索（stage1_hybrid）→ ColBERT 精排（stage2_colbert）→ Cross-Encoder 重排（stage3_reranker）
- 确定性代码生成引擎：Redis 缓存命中 → 算法匹配（pipeline）→ Jinja2 渲染（renderer），含去重（dedup）
- 结构化意图提取服务：normalizer / preflight / builder / history
- LLM 多模型适配层：Anthropic Claude 原生客户端 + OpenAI 兼容接口，工厂模式统一管理
- 批量生成任务系统：Celery + Redis 任务队列，支持 Excel 批量导入
- 模板库初始化（SVA 断言 5 个模板：data_integrity / fsm_state_transition / handshake_stable / handshake_timeout / reset_behavior）
- 前端完整界面：生成页、意图构建器、模板库、批量处理、我的贡献、管理控制台（用户/模板/贡献审核/LLM 配置）
- Excel 需求表解析服务（excel_parser）
- 平台管理服务：审计日志、备份、贡献审核
- Docker Compose 完整栈配置

### Changed
- 向量数据库由 pgvector 调整为 Qdrant（独立服务，更优的 ANN 检索性能）
- LLM 层设计从单一 Anthropic 扩展为可插拔多模型工厂

---

## [0.1.0] - 2026-04-22

### Added
- 初始仓库建立
- PRD v2.7：确认双表格结构化输入、三层确定性架构、三级权限体系
- ARCHITECTURE.md：完整系统架构设计文档

---

[Unreleased]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/releases/tag/v0.1.0
