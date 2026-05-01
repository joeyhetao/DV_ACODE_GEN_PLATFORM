# Changelog

All notable changes to DV_ACODE_GEN_PLATFORM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
