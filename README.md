# 喵仔仔 AI 日报

每天北京时间 10:00 自动抓取近 24 小时全球 AI 重要资讯，筛选、评分、生成中文精华版 HTML 日报，支持本地查看和可选邮件推送。核心价值：**用最少时间掌握最新 AI 行业动态**。

> 本项目的开发/维护由 Claude Code 技能 `miao-ai-daily-builder` 驱动。改任何逻辑前，对应的产品规格、信息源、评分规则、页面设计都在该技能的 `references/` 里。

## 技术栈

- Python（抓取/处理/渲染）
- RSS 抓取（feedparser），无 RSS 的源后续用网页抓取补
- AI 引擎：Claude Code 无头模式 `claude -p`（评分/摘要/标签/PM 启发）
- Jinja2 模板 → 单文件 HTML
- 定时：GitHub Actions（cron `0 2 * * *` = 北京 10:00）

## 数据管道

```
fetch(RSS) → normalize/去重 → prefilter(24h+关键词) → llm(claude -p 评分摘要标签)
  → rank(Top10/Top3/关键词/四指标) → render(HTML) → 归档 reports/ + index.html → 可选邮件
```

## 本地运行

```bash
cd ~/projects/miao-ai-daily
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m src.main --dry-run    # 只抓取+粗筛+打印，验证抓取（不调 LLM、不写文件）
python -m src.main              # 生成今天的日报（需本地已登录 Claude Code）
```

生成后打开 `index.html` 或 `reports/YYYY-MM-DD.html` 查看。

## 环境变量（复制 `.env.example` 为 `.env`）

| 变量 | 用途 | 必需 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | CI 里 `claude -p` 鉴权（复用订阅，推荐） | CI 必需 |
| `ANTHROPIC_API_KEY` | 备选鉴权（按量计费），与上面二选一 | 可选 |
| `SMTP_HOST/PORT/USER/PASS`、`MAIL_TO` | 邮件推送 | 可选 |

本地已登录 Claude Code 时，`claude -p` 直接可用，无需 token。

## 部署定时（GitHub Actions）

1. 把项目推到 GitHub 仓库。
2. 本地执行 `claude setup-token` 生成长期 OAuth Token（需 Claude Pro/Max）。
3. 仓库 Settings → Secrets and variables → Actions，新增 `CLAUDE_CODE_OAUTH_TOKEN`。
4. workflow 已配好（`.github/workflows/daily.yml`），每天北京 10:00 自动跑，并把生成的 HTML 提交回仓库。
5. 本地查看：`git pull` 后打开 `index.html`；或开启 GitHub Pages 用 URL 查看（见 workflow 注释）。

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
src/render.py            Jinja2 渲染 + 写归档
src/main.py              管道编排入口
templates/report.html.jinja   10 段卡片式页面
reports/                 每日产物归档
.github/workflows/daily.yml   每日定时
```

## 当前状态（MVP 骨架）

- ✅ 完整管道编排、RSS 抓取、标准化去重、24h 粗筛、排序聚合、HTML 模板、CI workflow
- ✅ `claude -p` 调用封装（评分/摘要/标签/PM 启发）
- ⏳ 待补：无 RSS 源的网页抓取、邮件推送实现、GitHub Pages 发布、各 RSS 地址实际可用性校验

## 验收清单

见技能 `miao-ai-daily-builder/references/architecture.md` 末尾的完整验收清单。
