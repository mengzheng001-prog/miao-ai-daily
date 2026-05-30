# 喵仔仔 AI 日报 — 项目记忆

## 定位
每天北京时间 10:00 自动生成「全球 AI 重要资讯」中文精华日报（HTML），可选邮件推送；每周日额外生成一份本周总结。核心价值：用最少时间掌握 AI 行业动态。
开发/维护由 Claude Code 技能 `miao-ai-daily-builder` 驱动，产品规格/信息源/评分规则在该技能的 `references/` 下。

仓库：`mengzheng001-prog/miao-ai-daily`，默认分支 `main`。站点公开地址用环境变量 `PAGES_URL` 覆盖，默认 `https://mengzheng001-prog.github.io/miao-ai-daily/`。

## 关键架构决策（2026-05-31 确立）

### 定时：外部触发器 + GitHub cron 兜底 + 幂等
- 背景：GitHub Actions `schedule` 不保证准时，整点高峰排队，实测被拖到下午一两点。
- 现状（三层配合）：
  - **主力** = 外部触发器（cron-job.org）每天北京 10:00 准时 `POST` workflow_dispatch。
  - **兜底** = GitHub cron `11 3 * * *`（北京 11:11），错开整点、晚于外部触发。
  - **幂等** = `main.py` 开头检查 `reports/data/今天.json` 是否已存在，存在即跳过，避免两层重复发两封邮件；`--force` 可绕过。
- 外部触发器靠 GitHub fine-grained token（仅本仓库 **Actions: Read and write**）调 dispatch 端点 `…/actions/workflows/daily.yml/dispatches`，body `{"ref":"main"}`。

### 邮件链接：指向当天归档页，不指 index
- 历史 bug：邮件按钮原指向 `pages_url`(=index.html)，而 index 每天被覆盖 → 昨天的邮件点开是今天内容、没有历史。
- 修复：`build_context` 生成 `report_url = pages_url + reports/今天.html`，邮件两个 CTA 都用 `report_url`，每份邮件锁死发出当天的内容。

### 历史回看 + 每周总结
- 每天 `render.write_daily_data` 把结构化数据落盘 `reports/data/YYYY-MM-DD.json`（周报的唯一数据源）。
- 日报页底部「最近 7 天」入口：`render._recent_reports` 扫 `reports/*.html` 生成。
- 周报（`src/weekly.py`）：聚合最近 7 天 data（按 url 去重保留最高分）→ `claude -p` 写本周综述+重点 → `reports/weekly-YYYY-MM-DD.html` + 周报邮件。周日 `main` 自动触发，或 `--weekly` 手动。
- **注意**：周报只能聚合「启用新代码（2026-05-31）后」跑过的天数；更早的归档没有对应 JSON，不进周报聚合（但仍出现在「最近 7 天」链接里）。

## 关键约定
- 产物 HTML 与 `reports/data` JSON 都提交回仓库（`reports/` 不进 gitignore）；CI commit 步骤 `git add reports/ index.html` 已覆盖。
- LLM 走 `claude -p`，CI 靠 `CLAUDE_CODE_OAUTH_TOKEN`；session 限额/超时导致当天 0 条入选时，`main` 跳过渲染/提交/邮件，保留上一份好报告（不覆盖成空壳）。
- bot 每天把日报 commit 回 `main`，本地 push 前常需先 `git fetch` + `git rebase origin/main`（两边改的文件通常不重叠，rebase 干净）。

## 待办 / 风险
- 外部触发器（cron-job.org）需手动配一次才真正准时：建 token → curl 验证 → 网页填表。配完前仍只有 GitHub cron 兜底（11:11 且可能延迟）。
