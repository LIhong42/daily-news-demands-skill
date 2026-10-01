---
name: daily-news
description: |
  每日热点新闻抓取 + 需求挖掘 skill。**当用户提到"今天的热点""每日资讯""热点需求""AI/科技新闻日报""从新闻挖需求""看热榜""trending news""demand mining""新闻报告""今日有哪些值得关注的需求"或希望 Claude 拉取多源新闻、挖掘可执行的产品需求、生成 Markdown/HTML 报告/导出 CSV/JSON 时，必须使用本 skill**。即便用户只说"帮我看看今天发生了什么""给我个需求清单""拉一下科技热点"，只要是涉及多源新闻聚合或需求挖掘，也应触发本 skill。**不要**在用户只是询问单个工具（如"什么是 feedparser"）、要求修复 bug、撰写诗歌/文案等无关需求时触发。
---

# Daily News Skill

## 设计哲学

**脚本只做机械的、可重复的工作（抓数据、去重、入库、渲染 HTML），所有"判断 / 写作 / 挖掘"全部由 Claude 在对话中承担。**

本 skill 不调用任何 LLM API、不引入 LangChain 等其他智能体框架。所有"智能"环节都在 Claude 的对话上下文中进行。

---

## 何时触发

- 用户希望拉取今日热点（"今天的热点""每日资讯""拉一下新闻"）
- 用户希望从新闻中挖掘产品机会（"挖需求""看新闻能做什么""有哪些 idea"）
- 用户希望生成 / 查看历史报告（"今天的报告""昨天的需求清单""导出 CSV"）
- 用户希望查询 / 统计已有数据（"近 7 天 AI 类需求""统计有多少新闻"）

**不触发**：bug 修复、通用 Python 教学、纯文案写作、单个工具用法。

---

## 工作流（Claude 按以下顺序执行）

### 标准流程：fetch → query → 挖 → 报告 → 渲染

#### 步骤 1：初始化（首次使用）

```bash
python scripts/cli.py init
```

若 DB 已建好会跳过。这步会创建 `data/daily_news.db`。

#### 步骤 2：抓取新闻

```bash
python scripts/cli.py fetch --hours 24
```

可选参数：
- `--source <name>`：只抓单个源（如 `hackernews`）
- `--category <cat>`：按类别（`tech` / `finance` / `social` 等）
- `--limit <N>`：每源上限
- `--hours <N>`：保留窗口（默认 24）

输出：`✓ ... 已抓取 N 条 / 入库 N 条` + 各源状态。

> **每日缓存机制**：每个数据源**每天最多远程抓一次**。当天反复调 `fetch` 会直接读 SQLite 不发请求；如果某源今天还没数据，源类 `fetch()` 内部会自动调用 NewsNow API（默认 base = `https://newsnow.busiyi.world/api/s`，`?id={newsnow_id}&latest`）。需要强制重抓时用 `refresh` 子命令。

#### 步骤 3：查询新闻

```bash
python scripts/cli.py query news --hours 24 --limit 100
```

或 JSON 格式（便于 Read 后分析）：

```bash
python scripts/cli.py query news --hours 24 --limit 100 --json
```

#### 步骤 4：挖掘需求（Claude 在对话中执行）

阅读 [prompts/mining_brief.md](prompts/mining_brief.md)，按 **"分桶 → 挖 → 去重"** 三步法：

1. **分桶**：先过滤噪声源
   ```bash
   # 矿脉桶（默认挖这里）
   python scripts/cli.py query news --category tech --hours 24
   python scripts/cli.py query news --category finance --hours 24
   # 或一行多源
   python scripts/cli.py query news --source github_trending,hackernews,cls_hot,wallstreetcn_hot --hours 24
   ```
2. **挖**：仅在矿脉桶 + 灰度桶挖，产出 N+3 条候选
4. **去重**：3 维去重（品类 / 用户画像 / 方案相似度），最终 ≥ 5 条、覆盖 ≥ 3 个品类
3. 喂给 CLI 入库：

```bash
python scripts/cli.py save-needs --json - << 'EOF'
[
  {"title": "...", "demand_scenario": "...", "feasibility": "高", "priority_score": 8.5, ...},
  ...
]
EOF
```

> **保底数量**：矿脉桶 ≥30 条新闻时至少输出 5 条需求，详情见 mining_brief.md「硬约束」一节。

#### 步骤 5：撰写报告（Claude 在对话中执行）

阅读 [prompts/report_brief.md](prompts/report_brief.md)，按指引产出两份 Markdown ：

```bash
python scripts/cli.py save-news-report --markdown - --date today << 'EOF'
# 每日热点简报 · 2025-XX-XX
...
EOF

python scripts/cli.py save-demand-report --markdown - --date today << 'EOF'
# 今日需求清单 · 2025-XX-XX
...
EOF
```

#### 步骤 6：渲染 HTML 报告

```bash
python scripts/cli.py report --format html --date today
```

输出：`reports/<date>/report.html`，自包含单文件（无后端），用浏览器打开可见：
- 📊 Dashboard（Mermaid 图表：来源饼图、可行性饼图）
- 📰 新闻（搜索框 + 来源过滤 + 卡片网格）
- 💡 需求（高/中/低 3 列 Kanban 看板）
- 🏷️ 标签云

#### 步骤 7：向用户总结

用 Read 工具打开 `reports/<date>/report.html` 和 `news.md` / `needs.md`，向用户做要点总结：
- 今日抓了多少新闻、哪些来源
- 挖了多少需求、最高优先级、高可行性几条
- 1-2 条最值得动手的需求（带 MVP 方案）
- 报告文件的绝对路径

---

## 常见场景命令速查

| 用户意图 | 执行的命令序列 |
|---|---|
| "拉今天的热点" | `fetch` + `query news` |
| "挖今天的 AI 需求" | `fetch` + `query news --category tech` + Claude 按 mining_brief 三步法挖 + `save-needs` |
| "只看矿脉源" | `query news --source github_trending,hackernews,cls_hot,wallstreetcn_hot --hours 24` |
| "按品类聚合" | `query news --category tech --category finance` |
| "生成今天的报告" | `save-news-report` + `save-demand-report` + `report --format html` |
| "查近 7 天的需求" | `query demands --hours 168` |
| "随机看几条新闻/需求" | `query random --kind news --count 5`（可选 `--source`、`--hours`；demands 可选 `--feasibility`、`--min-score`；`--exclude-uuid` 可多次传避免重复） |
| "导出需求为 CSV" | `export demands --format csv --output needs.csv` |
| "关闭微博源" | `sources disable weibo` |
| "查看统计" | `query stats` |
| "清理 60 天前的数据" | `clean --days 60 --yes` |
| "强制重抓今天的新闻" | `refresh --yes`（先清空当天 DB，再走 NewsNow） |

---

## 数据模型

### 新闻（news 表）
- `title / url / source / summary / content / hot_reason / score / fetched_at`
- 唯一性：`url_hash = sha256(url)`
- 去重：INSERT OR IGNORE

### 需求（demands 表）
- `title / demand_scenario / user_profile / description / value / proposed_solution`
- `feasibility: 高|中|低` / `priority_score: 0-10`
- `derived_from_news_uuids` (JSON 数组) / `tags` (JSON) / `evidence` (JSON)

### 报告（news_report / demands_report）
- `report_markdown` 字段存 Markdown 全文
- 自动写入 `reports/<date>/news.md` 和 `needs.md`

---

## 数据源（13 个）

| 源名 | 类别 | 类型 | 默认 limit |
|---|---|---|---|
| hackernews | tech | RSS | 25 |
| ifeng | news | RSS | 30 |
| thepaper | news | RSS | 30 |
| github | tech | trending (BS4) | 15 |
| weibo | social | hot_list (NewsNow + 兜底) | 20 |
| zhihu | qa | hot_list | 20 |
| bilibili-hot | video | hot_list | 20 |
| douyin | video | hot_list (NewsNow) | 20 |
| toutiao | news | hot_list | 20 |
| tieba | community | hot_list | 20 |
| wallstreetcn-hot | finance | hot_list + RSS | 20 |
| cls-hot | finance | hot_list | 20 |
| baidu | search | hot_list | 20 |

热榜类源默认通过 NewsNow 抓取（参考 TrendSearch-main）。如需启用：
```bash
# 在 .env 中配置 NEWSNOW_BASE_URL=https://your-newsnow-instance.com
```

---

## 常见错误与处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `fetch` 全失败 | 网络不通或 NEWSNOW_BASE_URL 不可用 | 检查网络；或单独跑 `hackernews` 验证 RSS |
| `save-needs` 报 JSON 错 | 缺字段或语法错 | 重新生成 JSON；最少要有 `title` |
| `report --format html` 报模板错 | Jinja2 版本/模板路径 | 检查 `templates/report.html.j2` |
| DB 锁死 | 多个进程并发写 | 等几秒重试；或重启 CLI |
| 微博/抖音完全抓不到 | 反爬严，需自建 NewsNow | 配置 `NEWSNOW_BASE_URL` 或忽略 |

---

## 文件位置速查

- 数据库：`data/daily_news.db`
- 报告：`reports/<YYYY-MM-DD>/{news.md, needs.md, report.html}`
- 配置：`config/sources.json`、`config/user_preferences.json`
- Prompt 指令：`prompts/mining_brief.md`、`prompts/report_brief.md`
- 环境变量：`.env`（从 `.env.example` 复制）

---

## 设计取舍说明（why）

- **不调 LLM API**：所有 AI 推理由 Claude 在对话中完成。脚本层职责单一 = 易测试、易复用。
- **不引入 LangChain**：那是另一套智能体框架，与 Claude 智能体职责重叠。直接 anthropic SDK 调用反而引入新依赖。
- **保留 SQLite**：原项目验证过的高性能存储，复用 `INSERT OR IGNORE` + `executemany` 模式。
- **HTML 单文件**：无后端，便于分享和浏览器直接打开；前端用原生 JS + Mermaid CDN。
- **挖需求不写脚本**：脚本里的"挖"永远比不上 Claude 对上下文的理解。脚本只负责"机械入库"。