# Changelog

All notable changes to DV_ACODE_GEN_PLATFORM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **正则参数提取扩展**（pipeline.py `_extract_params_from_intent`）：从只覆盖 5 个 coverage 字段扩展到额外覆盖 11 个 assertion 参数（module_name / max_cycles / max_delay / init_value / enable / data / valid / ready / target / start_event / end_event / state_sig），让"模块名为 X，使能信号为 Y"这类半结构化句式不再依赖 LLM Step2 语义映射
- **首份单元测试** `backend/tests/test_extract_params.py`：22 个测试覆盖既有 coverage 提取（回归保护）+ 新增 assertion 提取 + 反例（避免误提取）+ §1.1/§1.4/§1.6 完整集成场景。容器内跑 `docker compose exec backend pytest tests/test_extract_params.py -v`
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
- `docs/deployment.md` 由 680 行重写为 ~50 行索引文档，仅承载场景对比表与跳转
- README.md 文档索引表新增 4 条文档链接（3 份 deployment + test-manual）

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

[Unreleased]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/releases/tag/v0.1.0
