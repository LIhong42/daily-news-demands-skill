# Daily News Skill

> Claude Code 本地技能：每日多源热点新闻抓取 + 产品需求挖掘。所有"思考"由 Claude 智能体在对话中完成，脚本只负责机械操作（抓数据、入库、渲染）。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境（可选）
cp .env.example .env
# 编辑 .env：填入 NEWSNOW_BASE_URL（如有自建）、TAVILY_API_KEY（如有）

# 3. 初始化数据库
python scripts/cli.py init

# 4. 抓取新闻
python scripts/cli.py fetch --hours 24

# 5. 查询新闻
python scripts/cli.py query news --hours 24 --limit 20

# 6. 让 Claude 在对话中挖需求 → save-needs
python scripts/cli.py save-needs --json needs.json

# 7. 写报告 → render HTML
python scripts/cli.py report --format html --date today
```

打开 `reports/<date>/report.html` 查看可视化结果。

## 项目结构

```
daily_news/
├── SKILL.md              # Claude 入口（YAML + 工作流）
├── README.md             # 本文件
├── requirements.txt
├── .env.example
├── config/
│   ├── sources.json      # 13 个数据源配置
│   └── user_preferences.json
├── data/
│   └── daily_news.db     # SQLite
├── reports/
│   └── YYYY-MM-DD/       # 每日报告
├── scripts/
│   ├── cli.py            # click CLI（6 个子命令）
│   ├── fetch.py          # 多源抓取编排
│   ├── data_sources/     # 13 个数据源 + BaseDataSource 抽象
│   ├── storage/          # SQLite DataStore
│   └── reports/          # Markdown / HTML 渲染
├── templates/
│   ├── news.md.j2
│   ├── needs.md.j2
│   └── report.html.j2
├── prompts/
│   ├── mining_brief.md   # 给 Claude 看的"挖需求"指令
│   └── report_brief.md   # 给 Claude 看的"写报告"指令
└── evals/
    └── evals.json
```

## CLI 命令

```bash
python scripts/cli.py init                 # 建库
python scripts/cli.py fetch                # 抓取所有启用源
python scripts/cli.py fetch --source hackernews  # 单源
python scripts/cli.py query news           # 列出新闻
python scripts/cli.py query demands        # 列出需求
python scripts/cli.py query stats          # 数据库统计
python scripts/cli.py save-needs --json -  # 接收 Claude 产出 JSON 入库（heredoc）
python scripts/cli.py save-news-report --markdown -  # 接收 Claude 产出 Markdown
python scripts/cli.py save-demand-report --markdown -
python scripts/cli.py report --format html --date today
python scripts/cli.py export demands --format csv
python scripts/cli.py sources list
python scripts/cli.py sources disable weibo
python scripts/cli.py clean --days 30 --yes
```

## 完整工作流示例

```bash
# === 步骤 1：抓数据（机械）===
python scripts/cli.py init
python scripts/cli.py fetch --hours 24

# === 步骤 2：查询（机械）===
python scripts/cli.py query news --hours 24 --limit 50

# === 步骤 3：Claude 在对话中挖需求（智能）===
# （Claude 读 prompts/mining_brief.md → 产出 JSON → heredoc 喂 CLI）

python scripts/cli.py save-needs --json - << 'EOF'
[{"title": "...", ...}]
EOF

# === 步骤 4：Claude 在对话中写报告（智能）===
python scripts/cli.py save-news-report --markdown - --date today << 'EOF'
# 每日热点简报 ...
EOF

python scripts/cli.py save-demand-report --markdown - --date today << 'EOF'
# 今日需求清单 ...
EOF

# === 步骤 5：渲染 HTML（机械）===
python scripts/cli.py report --format html --date today

# === 步骤 6：查看（机械 + Claude 总结）===
# 浏览器打开 reports/<date>/report.html
```

## 配置 NewsNow API（推荐）

热榜类源（微博、知乎、B 站、抖音等）反爬强，**默认已接入公开 NewsNow 服务**：

```bash
# .env 中默认就有（无需配置）：
NEWSNOW_BASE_URL=https://newsnow.busiyi.world/api/s
# 兼容别名（原项目 TrendSearch-main 用的变量名）：
NEWS_API_URL=
```

各源调用格式：`GET {URL}?id={newsnow_id}&latest`，newsnow_id 映射见 `config/sources.json`：

| 源名 | newsnow_id |
|---|---|
| weibo | weibo |
| zhihu | zhihu |
| bilibili_hot | bilibili |
| douyin | douyin |
| toutiao | toutiao |
| tieba | tieba |
| wallstreetcn_hot | wallstreetcn-hot |
| cls_hot | cls-hot |
| baidu | baidu |

非热榜源（hackernews/ifeng/thepaper/github_trending）走 RSS/Trending，不走 NewsNow。

### 每日缓存机制

**每个数据源每天最多远程抓一次**：

- 第一次 `fetch` 触发 NewsNow API → 入库
- 当天再次 `fetch` → 源类 `fetch()` 内部发现 DB 已有当天数据 → 直接返回缓存，无远程请求
- `query` / `report` / `export` 等命令永远从 DB 读，**绝不触发远程**
- 强制重抓：用 `refresh --date today --yes`（清掉当天 DB + daily_runs，再走 NewsNow）

## SQLite 表结构

- `news` - 新闻条目（带 url_hash 去重）
- `demands` - 产品需求（带 derived_from_news_uuids 关联）
- `news_report` / `demands_report` - Markdown 报告存档
- `daily_runs` - 每日运行日志

## 数据源清单（13 个）

详见 [config/sources.json](config/sources.json)。已实现的源：

| Type | 源 |
|---|---|
| RSS | hackernews, ifeng, thepaper |
| Trending | github |
| Hot list (NewsNow + 兜底) | weibo, zhihu, douyin, bilibili-hot, toutiao, tieba, wallstreetcn-hot, cls-hot, baidu |

## License

MIT