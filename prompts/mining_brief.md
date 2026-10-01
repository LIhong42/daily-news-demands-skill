# 挖需求指令（Claude 阅读并按此执行）

> **触发条件**：用户在 daily-news skill 中要求"挖需求 / 挖掘机会 / 从新闻里找 idea"。
> **本指令定义了 Claude 在阅读新闻后，应产出什么样的需求 JSON、如何调用 `cli.py save-needs` 入库。**

---

## 你的任务

从当日新闻中，按 **"过滤 → 挖 → 去重"三步法**，挖掘"下周能开工"的产品需求，最终输出**保底数量**且**品类多样**的需求清单。

---

## 三步法

### 第 1 步：分桶（30 秒）—— 过滤噪声

按 source/category 把当日新闻拆成 3 个桶，**先剔除噪声源**，避免被娱乐八卦稀释：

| 桶 | source | 用途 |
|---|---|---|
| 🟢 **矿脉桶** | `github_trending / hackernews / cls_hot / wallstreetcn_hot` | 默认挖这里 |
| 🟡 **灰度桶** | `thepaper / ifeng / toutiao / baidu` | 保留政策/宏观/产业类 |
| 🔴 **噪声桶** | `weibo / zhihu / bilibili / douyin / tieba` | **默认剔除**，除非用户明确说"娱乐挖准口子" |

**分桶命令**：

```bash
# 矿脉桶
python scripts/cli.py query news --category tech --hours 24
python scripts/cli.py query news --category finance --hours 24
# 或一行多源
python scripts/cli.py query news --source github_trending,hackernews,cls_hot,wallstreetcn_hot --hours 24
# 灰度桶（可选）
python scripts/cli.py query news --source thepaper,ifeng,toutiao --hours 24
```

> `--category` 已映射到 sources.json 的真实 category（tech / finance / social / qa / video / news / community / search），多 category 可叠加：`--category tech --category finance`。

---

### 第 2 步：挖（5 分钟）

仅在 🟢 桶 + 🟡 桶挖，每条新闻按以下流程过一遍：

```
新闻标题 + 摘要 + 内容
   ↓
识别"用户痛点"：谁、原本怎么解决、现在为何变难
   ↓
判断"why now"：政策/平台/用户行为拐点（2024 年也能做？→ 砍）
   ↓
构造"用户四要素"：行业 + 体量 + 角色 + 工作流
   ↓
写出 MVP 方案（1-2 人 2 周能否起步）
   ↓
产出 1 条候选需求（带 priority_score）
```

**字段规范**（保持现有 JSON 格式）：

```json
{
  "title": "动词+名词+限定语，≤30 字",
  "demand_scenario": "痛点场景，谁、原本怎么解决、现在为何变难",
  "user_profile": "行业+体量+角色+工作流，四要素齐全",
  "description": "完整需求描述",
  "value": "解决后带来什么价值（量化或可观察）",
  "proposed_solution": "MVP 方案，≤80 字",
  "feasibility": "高" | "中" | "低",
  "priority_score": 0.0-10.0 综合评分（可保留 1 位小数）,
  "derived_from_news_uuids": ["新闻 uuid1", "新闻 uuid2"],
  "tags": ["AI", "跨境电商", ...],
  "evidence": {
    "news_titles": ["新闻标题1", "新闻标题2"],
    "news_uuids": ["...", "..."]
  }
}
```

产出 **候选 N+3 条**（让第 3 步去重时有挑头）。

---

### 第 3 步：去重 + 选优

在候选里做 3 维去重，最终输出**保底数量**且**品类多样**：

| 维度 | 规则 |
|---|---|
| **品类去重** | 相同一级品类（如「AI 工具」/「内容创作」/「电商」/「金融」）最多保留 2 条 |
| **用户画像去重** | 用户四要素（行业/体量/角色/工作流）完全相同 → 合并取 priority_score 高的 |
| **方案相似度去重** | MVP 方案核心机制雷同（如"都是 RAG + 摘要"）→ 合并 |

最终：
- 覆盖 **≥ 3 个不同品类**
- 每条 priority_score ≥ 5.0（低于的淘汰或升级方案后再回）

---

## 输出数量硬约束（重要）

| 矿脉桶新闻数 | 至少输出 |
|---|---|
| **≥ 30 条** | **5 条**（且品类 ≥ 3）|
| **15-29 条** | **3 条** |
| **< 15 条** | 1-2 条，并在响应里说明"今日矿脉不足" |

> 这条是**硬下限**，不是建议。如果品类去重后凑不到 5 条，先放宽品类约束（每品类允许 3 条）而不是减条数。

---

## 强制原则

1. **可执行性**：每条需求都能回答"下周一开始做，需要招几个人做什么模块"
2. **新闻支撑**：每条需求都有 ≥1 条新闻显式支撑，禁止凭空推断
3. **避免大厂矩阵**：禁止与字节/阿里/腾讯/百度/华为/小米/Google/Microsoft/Anthropic/OpenAI 现有产品直接重叠
4. **避免空泛**：禁止"通用聊天机器人/笔记 AI/ChatGPT 套壳/RAG 框架/prompt 市场"

## 反模式（命中即砍）

- 宽泛描述："做一个 AI 助手提升效率"
- 无痛点：用户没在用脚投票
- 无 why now：2024 年也能做，没变化
- 目标用户缺失四要素："所有用户" / "中小企业"
- **同质化候选**：5 条都是「AI 摘要工具」→ 砍到 2 条

---

## 保存方式

产出后**必须用 heredoc 喂给 CLI 入库**：

```bash
python scripts/cli.py save-needs --json - << 'EOF'
[
  {"title": "...", ...},
  {"title": "...", ...}
]
EOF
```

成功标志：CLI 输出 `✓ 已写入 N 条需求`。

---

## 完成后的下一步

1. 用 `Read` 工具读 `prompts/report_brief.md`，按指引撰写 Markdown 报告
2. 调用 `cli.py save-news-report --markdown - --date today` 保存新闻报告
3. 调用 `cli.py save-demand-report --markdown - --date today` 保存需求报告
4. 用 Bash 调用 `python scripts/cli.py report --format html --date today` 生成可视化 HTML
5. 用 Read 工具打开 `reports/<today>/report.html` 并向用户做要点总结

---

## 评分细则（priority_score 0-10）

| 维度 | 权重 | 说明 |
|------|------|------|
| 可行性（技术+合规） | 30% | 1-2 人 2 周能否起步；是否需牌照 |
| 痛点强度 | 30% | 用户是否在用脚投票（数据/案例支撑） |
| 市场空间 | 25% | TAM 与可切入细分 |
| 时机（why now） | 15% | 政策/平台/用户行为拐点 |

- 8-10：本周就值得动手
- 5-7：值得做用户调研
- 3-5：列入 backlog
- 0-3：观察，不做

`feasibility` 字段则只反映"能不能做"（技术+监管），不看痛点。