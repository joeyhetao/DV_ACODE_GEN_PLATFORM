根据项目当前真实进展，更新 README.md、CHANGELOG.md、CONTRIBUTING.md 三份文档。

## 第零步：preflight（docs 分支必须先 rebase）

如果当前分支匹配 `docs/*`，**先运行以下检查**，未通过则立即终止，不要进入第一步：

```bash
BRANCH=$(git symbolic-ref --short HEAD)
case "$BRANCH" in
  docs/*)
    git fetch origin develop --quiet
    if ! git merge-base --is-ancestor origin/develop HEAD; then
      echo "ABORT: '$BRANCH' is not based on latest origin/develop."
      echo "Run: git rebase origin/develop"
      echo "Then retry /update-docs. (Without rebase, git log will not"
      echo "show upstream feature commits and CHANGELOG diff will be stale.)"
      exit 1
    fi
    ;;
esac
```

若 abort，向用户输出上述错误信息并停止，不要继续执行后续步骤。

非 `docs/*` 分支跳过此检查。

## 第零点五步：spec + handoff JSON 摄入（v3 multi-agent workflow）

如果当前 ticket 是 multi-agent workflow 走过来的，spec.md 的 §8 Machine block 和对面 feat worktree 的 Handoff JSON 已经告诉了我们：

- `docs_targets` 是否包含 `README` / `CHANGELOG` / `CONTRIBUTING`？
- `changelog.{type, scope}` 是什么？（直接 seed CHANGELOG 条目 header）
- `affected_paths` 改动了哪些目录？（CONTRIBUTING 目录树是否要更新）

读取逻辑：

```bash
BRANCH=$(git symbolic-ref --short HEAD)
TICKET=$(echo "$BRANCH" | sed -E 's|^(feature|fix|docs|hotfix|spec)/||')
SPEC_PATH=".claude/plans/$TICKET.spec.md"
REPO_NAME=$(basename "$(git rev-parse --show-toplevel)" | sed -E 's|-(feat|docs)-.+$||')
FEAT_WT="../${REPO_NAME}-feat-${TICKET}"
HANDOFF_PATH="$FEAT_WT/.claude/state/$TICKET.code.md"
```

1. **若 `$SPEC_PATH` 存在**：用 Read 提取 §6 Docs Impact 段 + §8 fenced JSON。
2. **若 `$HANDOFF_PATH` 存在**：用 Read 提取 `## Handoff JSON` 下的 fenced JSON。冲突时 handoff 胜。
3. 合并 `docs_targets`：限定本步只更新被点名的文件子集。
   - 若 `docs_targets=["CHANGELOG"]` → 跳过 README + CONTRIBUTING 的更新
   - 若 `docs_targets=[]` → 直接告诉用户"spec 标记本 ticket 不需要 docs 更新"并退出
4. 用 `changelog.type` + `changelog.scope` 预填 CHANGELOG 新条目 header（仍需第三步根据 git log 校对 subject 措辞）。

**若两份文件都不存在**：fall through 到下面的第一步（按 git log 推断变更），保持 v2 行为。

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

### 第四点五步（条件）：更新 docs/test-manual.md

**仅当 `docs_targets` 包含 `"test-manual"` 时执行**，否则跳过。

操作方式：
1. 读取 handoff JSON 中的 `affected_paths`，判断涉及的功能范围（admin UI / 生成流程 / 新端点 / 新闸逻辑）
2. 分段读取 `docs/test-manual.md`（先读目录结构，再读受影响章节，避免 token 爆炸）
3. 在最相关的章节末尾（或新建子章节）追加新功能的测试步骤，格式与现有章节一致：
   - 步骤编号（1. 2. 3. …）
   - 每步写明操作 + **预期结果**
   - 附日志验证命令（`docker compose logs -f backend | grep ...`）
   - 附 DB 验证 SQL（如涉及新表）
4. 如新增了 API 端点，在"附录 B：错误响应结构对照"补充新端点的响应格式
5. 不要修改其他章节的内容和格式

### 第五步：提交

完成修改后，执行（按实际修改的文件调整 git add 列表）：

```bash
# 必选（至少有一项有变动）
git add CHANGELOG.md

# 按需追加
# git add README.md
# git add CONTRIBUTING.md
# git add docs/test-manual.md

git commit -m "docs: sync README/CHANGELOG/CONTRIBUTING/test-manual with current project state"
```

## 注意事项

- 只修改与实际状态不符的内容，风格和语言（中文）保持不变
- CHANGELOG 条目要有实际意义，不要流水账式列文件名
- 如果用户通过 `$ARGUMENTS` 传入了版本号（如 `/update-docs 0.3.0`），使用该版本号而非自动推断
