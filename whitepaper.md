# 🏀 OpenClaw 架构设计：NBA 自动套利模拟系统 (NBA_Alpha_Agent)

## 一、 项目文件结构 (Project Structure)

建议在 OpenClaw 的 `skills/nba_alpha_agent/` 目录下创建以下结构：

```text
nba_alpha_agent/
├── skill.json           # 技能定义，向 OpenClaw 暴露定时任务和触发接口
├── main.py              # 核心控制流 (Pipeline 调度)
├── data_engine.py       # 数据聚合器 (Gamma API, NBA 慢数据, 伤病快数据, 高阶数据)
├── llm_analyzer.py      # 封装 System Prompts 和 Risk 判断逻辑
├── db_manager.py        # SQLite 数据库操作 (下单、更新状态)
├── scheduler.py         # 定时任务模块 (Cron / APScheduler)
├── requirements.txt     # 依赖包 (nba_api, sqlite3, requests, schedule)
└── data/
    └── paper_ledger.db  # 本地模拟盘数据库

```

---

## 二、 核心工作流 (The Daily Pipeline)

系统每天自动运行，核心流程分为 5 个阶段，由 `main.py` 统筹协调：

### 阶段 1：全局初始化 (Daily Setup)

* **时间点**：每天上午 10:00 (东部时间，通常各队伤病报告初步更新)。
* **动作**：`data_engine.get_todays_matches()` 获取当天所有比赛列表。

### 阶段 2：数据聚合与组装 (For 每一场比赛)

对列表中的每一场比赛，并行获取三路数据：

1. **市场数据 (Polymarket)**：调用 Gamma API，提取 `Yes_Price`, `No_Price`, `Condition_ID`。
2. **硬核数据 (NBA API)**：
* *慢数据*：双方胜率、近期 5 场净胜分、**是否背靠背 (B2B)**、**近期赛程密度**。
* *快数据*：核心球员伤病名单 (`OUT`, `GTD`)、预计首发阵容。


3. **专家文本分析 (Scraper - 规划中/暂未接入)**：抓取并清洗白名单信源（如 Cleaning the Glass 的前瞻），提取纯战术和对位优势，剔除情绪化语言。*(当前版本暂未融合文本分析，计划在未来升级中加入。)*

### 阶段 3：风控与预测 (LLM Reasoning Loop)

将上述三路数据拼装成 JSON Context，提交给 OpenClaw 的 LLM。

* **第一层：Risk 评估**：如果发现“核心首发当天交易”、“赛前 1 小时 3 名主力 GTD”等极高不确定性情况，LLM 必须输出 `{"action": "SKIP", "reason": "高不确定性"}`。
* **第二层：胜率推演**：如果 Risk 通过，LLM 基于硬数据和高阶战术数据，输出一个具体的预测行动和依据。

### 阶段 4：执行模拟下单 (Execution)

对比 `LLM_Win_Rate` 与 `Polymarket_Implied_Odds (市价)`：

* **买 YES 触发**：`LLM_Win_Rate > PM_Odds + 0.05`
* **买 NO 触发**：`LLM_Win_Rate < PM_Odds - 0.05`
* **记录入库**：调用 `db_manager`，将订单写入 SQLite，状态标记为 `PENDING`。

### 阶段 5：自动结算与复盘 (Post-Match Settlement)

* **触发机制**：系统每天凌晨 2:00 运行一次 `settlement_job`。
* **动作**：查询数据库中状态为 `PENDING` 的订单，通过 NBA API 获取真实比分。
* **结算**：如果是赢单，更新状态为 `WIN` 并计算利润；如果是输单，更新为 `LOSS`。*(注意：由于 Polymarket 结算可能有延迟，用 NBA 官方比分结算模拟盘更准更实时)*。

---

## 三、 SQLite 数据库设计 (db_manager.py)

包含两张核心表：`portfolio` 和 `paper_trades`。

### 1. 资产组合 (portfolio)
用于跟踪系统的总资金余额。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 (固定为 1) |
| `balance` | REAL | 系统当前可用资金余额 (USDC)，初始 1000 |

### 2. 模拟交易记录 (paper_trades)
用于全面记录系统下过的每一笔订单。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键自增 |
| `timestamp` | DATETIME | 下单时间 |
| `match_name` | TEXT | 比赛名称 (如 LAL vs DEN) |
| `pm_condition_id` | TEXT | Polymarket 的唯一事件 ID |
| `side` | TEXT | `YES` 或 `NO` 或者具体的队名 |
| `buy_price` | REAL | 买入价 (已含 0.5% 模拟滑点) |
| `amount` | REAL | 下注金额 (USDC) |
| `ai_prob` | REAL | LLM 预测胜率 |
| `pm_prob` | REAL | 下单时的市场隐含胜率 |
| `llm_reasoning` | TEXT | LLM 给出的下单理由 (用于人工复盘) |
| `status` | TEXT | `PENDING`, `WIN`, `LOSS` |
| `pnl` | REAL | 盈亏金额 |

---


