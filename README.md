# 喵仔仔 AI 日报

每天北京时间 10:00 自动抓取近 24 小时全球 AI 重要资讯，筛选、评分、生成中文精华版 HTML 日报，支持本地查看和可选邮件推送。核心价值：**用最少时间掌握最新 AI 行业动态**。

> 本项目的开发/维护由 Claude Code 技能 `miao-ai-daily-builder` 驱动。改任何逻辑前，对应的产品规格、信息源、评分规则、页面设计都在该技能的 `references/` 里。

## 技术栈

- Python（抓取/处理/渲染）
- RSS 抓取（feedparser），无 RSS 的源后续用网页抓取补
- AI 引擎：Claude Code 无头模式 `claude -p`（评分/摘要/标签/PM 启发）
- Jinja2 模板 → 单文件 HTML
- 定时：外部触发器（cron-job.org）每天北京 10:00 准时触发，GitHub Actions cron 兜底

## 数据管道

```
fetch(RSS) → normalize/去重 → prefilter(24h+关键词) → llm(claude -p 评分摘要标签)
  → rank(Top10/Top3/关键词/四指标) → render(HTML) → 归档 reports/ + index.html → 可选邮件
        ↳ 同时落盘 reports/data/YYYY-MM-DD.json（每周总结的数据源）
        ↳ 每周日：聚合最近 7 天 data → 周报页 reports/weekly-*.html + 周报邮件
```

## 本地运行

```bash
cd ~/projects/miao-ai-daily
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m src.main --dry-run    # 只抓取+粗筛+打印，验证抓取（不调 LLM、不写文件）
python -m src.main              # 生成今天的日报（需本地已登录 Claude Code）
python -m src.main --force      # 忽略"今天已生成"的幂等跳过，强制重跑
python -m src.main --weekly     # 只生成本周总结（聚合最近 7 天已存的 data）
```

生成后打开 `index.html` 或 `reports/YYYY-MM-DD.html` 查看。

## 环境变量（复制 `.env.example` 为 `.env`）

| 变量 | 用途 | 必需 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | CI 里 `claude -p` 鉴权（复用订阅，推荐） | CI 必需 |
| `ANTHROPIC_API_KEY` | 备选鉴权（按量计费），与上面二选一 | 可选 |
| `SMTP_HOST/PORT/USER/PASS`、`MAIL_TO` | 邮件推送 | 可选 |

本地已登录 Claude Code 时，`claude -p` 直接可用，无需 token。

## 部署与定时

### 1. 鉴权（CI 跑 `claude -p` 用）

1. 把项目推到 GitHub 仓库。
2. 本地执行 `claude setup-token` 生成长期 OAuth Token（需 Claude Pro/Max）。
3. 仓库 Settings → Secrets and variables → Actions，新增 `CLAUDE_CODE_OAUTH_TOKEN`。
4. 邮件推送可选：再加 `SMTP_HOST/PORT/USER/PASS`、`MAIL_TO` 五个 Secret，不配则自动跳过。

### 2. 定时为什么是两层（准时 + 兜底）

GitHub Actions 的 `schedule` 不保证准时：整点高峰排队，常延迟数小时（本项目实测被拖到下午一两点）。所以拆成两层：

```
北京 10:00  外部触发器(cron-job.org) 准时调 workflow_dispatch ─► 生成+发邮件+提交回仓库
北京 11:11  GitHub cron 兜底(cron "11 3 * * *") ─► 外部已成功则幂等跳过，否则补位
```

- **主力**：外部触发器准时，误差 1 分钟内。
- **兜底**：外部触发器挂掉那天，GitHub cron 补位。
- **幂等**：`main.py` 开头检查 `reports/data/今天.json` 是否已存在，存在即跳过，保证每天只发一封；`--force` 可绕过。

### 3. 配外部触发器（cron-job.org，免费）

1. 建 GitHub fine-grained token，只授权本仓库的 **Actions: Read and write**。
2. cron-job.org 建任务，每天 10:00（时区 Asia/Shanghai），`POST` 到：
   `https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily.yml/dispatches`
   - Header：`Authorization: Bearer <TOKEN>`、`Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28`
   - Body：`{"ref":"main"}`

查看产物：`git pull` 后打开 `index.html`，或开启 GitHub Pages 用 URL 查看（见 workflow 注释）。

## 配置信息源

编辑 `config/sources.yaml`。每个源：`name / category(A|B|C) / type(rss|web) / url / enabled`。MVP 只启用有可靠 RSS 的源；无 RSS 的标 `type: web, enabled: false`，待网页抓取功能完成再开。

## 目录结构

```
config/sources.yaml      信息源注册表 + 评分权重 + 受控标签词表
src/fetch.py             RSS 抓取
src/normalize.py         标准化 + 去重 + 时间转北京时区
src/prefilter.py         24h 硬过滤 + 关键词粗筛
src/llm.py               claude -p 评分/摘要/标签/PM启发
src/rank.py              排序 Top10/Top3 + 关键词聚合 + 来源生态
src/render.py            Jinja2 渲染 + 写归档 + 每日数据落盘 + 历史/周报入口
src/weekly.py            每周总结：聚合最近 7 天 data + LLM 综述 → 周报
src/main.py              管道编排入口（日报 / --weekly / --force，周日自动出周报）
templates/report.html.jinja        10 段卡片式页面 + 最近 7 天历史入口
templates/email.html.jinja         日报邮件（按钮指向当天归档页，不再跳到今天）
templates/weekly.html.jinja        周报页
templates/weekly_email.html.jinja  周报邮件
reports/                 每日产物归档（YYYY-MM-DD.html）
reports/data/            每日结构化数据 JSON（每周总结的数据源）
reports/weekly-*.html    每周总结归档
.github/workflows/daily.yml   定时（cron 兜底；准时靠外部触发器）
```

## 当前状态（MVP 骨架）

- ✅ 完整管道编排、RSS 抓取、标准化去重、24h 粗筛、排序聚合、HTML 模板、CI workflow
- ✅ `claude -p` 调用封装（评分/摘要/标签/PM 启发）
- ⏳ 待补：无 RSS 源的网页抓取、邮件推送实现、GitHub Pages 发布、各 RSS 地址实际可用性校验

## 验收清单

见技能 `miao-ai-daily-builder/references/architecture.md` 末尾的完整验收清单。
