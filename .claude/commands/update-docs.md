根据项目当前真实进展，更新 README.md、CHANGELOG.md、CONTRIBUTING.md 三份文档。

## 执行步骤

### 第一步：采集项目真实状态

运行以下命令，收集当前状态：

```bash
git log --oneline -20
git status
```

同时读取以下文件，了解现有内容：
- README.md
- CHANGELOG.md
- CONTRIBUTING.md
- backend/app/ 目录结构（用于校验 CONTRIBUTING 中的目录树）
- frontend/src/ 目录结构

### 第二步：更新 README.md

找到 `## 项目状态` 章节，根据 git 提交历史和实际代码状态，更新勾选项：

判断规则：
- `后端骨架搭建`：backend/app/main.py、router.py 存在 → ✅
- `确定性引擎核心实现`：backend/app/services/core/pipeline.py、renderer.py 存在 → ✅
- `三阶段 RAG 流水线`：stage1_hybrid.py、stage2_colbert.py、stage3_reranker.py 存在 → ✅
- `前端框架搭建`：frontend/src/App.tsx、pages/ 目录存在 → ✅
- `模板库初始化`：backend/template_library/ 下有 .yaml 文件 → ✅
- `批量处理 & Celery`：batch_tasks.py 存在 → ✅
- `LLM 配置管理`：admin_llm.py、llm_config.py 存在 → ✅
- `Docker Compose 完整栈`：docker-compose.yml 存在 → ✅
- `Alpha 测试`：有 tests/ 目录且非空 → ✅，否则 ❌

同时更新技术栈表格中与实际代码不符的条目（例如 README 中写了 pgvector 但实际用 Qdrant，需纠正）。

### 第三步：更新 CHANGELOG.md

在 `## [Unreleased]` 下方新增一个版本条目，格式：

```
## [0.2.0] - YYYY-MM-DD

### Added
- （根据 git log 列出新增功能）

### Fixed
- （根据 git log 列出修复项）

### Changed
- （根据 git log 列出变更项）
```

版本号规则：
- 当前最高版本 +0.1.0（Minor bump）表示首次完整实现
- 日期使用 git log 最新 commit 的日期（`git log -1 --format=%ci`）

只列有实质意义的条目，不要把每个文件都列一遍。按功能模块归纳。

同时更新文件末尾的版本对比链接：
```
[0.2.0]: https://github.com/joeyhetao/DV_ACODE_GEN_PLATFORM/compare/v0.1.0...v0.2.0
```

### 第四步：更新 CONTRIBUTING.md

找到 `## 1. 仓库结构` 章节中的目录树，与实际目录结构对齐：

对比规则：
- 读取 backend/app/ 下实际存在的子目录和关键文件
- 读取 frontend/src/ 下实际存在的子目录
- 补全文档中缺失的目录（如 services/、tasks/、embedding_service/ 等）
- 删除文档中已不存在的路径（如旧的 engine/、llm/ 如果实际路径不同）
- 保持注释风格与原文一致（中文注释）

不要修改 CONTRIBUTING.md 的其他章节（分支策略、提交规范等保持不变）。

### 第五步：提交

完成三个文件的修改后，执行：

```bash
git add README.md CHANGELOG.md CONTRIBUTING.md
git commit -m "docs: sync README/CHANGELOG/CONTRIBUTING with current project state"
```

## 注意事项

- 只修改与实际状态不符的内容，风格和语言（中文）保持不变
- CHANGELOG 条目要有实际意义，不要流水账式列文件名
- 如果用户通过 `$ARGUMENTS` 传入了版本号（如 `/update-docs 0.3.0`），使用该版本号而非自动推断
