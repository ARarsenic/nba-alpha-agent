# 🏀 OpenClaw 架构设计：NBA 自动套利模拟系统 (NBA_Alpha_Agent)

## 一、 项目文件结构 (Project Structure)

建议在 OpenClaw 的 `skills/nba_alpha_agent/` 目录下创建以下结构：

```text
nba_alpha_agent/
├── skill.json           # 技能定义，向 OpenClaw 暴露定时任务和触发接口
├── main.py              # 核心控制流 (Pipeline 调度，包含执行与结算任务)
├── wallet_manager.py    # Web3/Polygon 实盘资金、私钥管理与交易签名
├── data_engine.py       # 数据聚合器 (Gamma API, NBA 慢数据, 伤病快数据, 高阶数据)
├── llm_analyzer.py      # 封装 System Prompts 和 Risk 判断逻辑
├── db_manager.py        # SQLite 数据库操作 (记录实盘订单与状态)
├── scheduler.py         # 定时触发器 (仅负责定时调用 main.py 中的任务)
├── requirements.txt     # 依赖包 (nba_api, sqlite3, requests, schedule, web3)
└── data/
    └── live_ledger.db   # 本地实盘日志数据库 (记录 LLM 推理和交易哈希)

```

---

## 二、 核心工作流 (The Daily Pipeline)

系统每天自动运行，核心流程分为 5 个阶段，由 `main.py` 统筹协调：

### 阶段 1：全局初始化 (Daily Setup)

* **时间点**：每天下午 14:00 (东部时间，通常各队伤病报告初步更新)。
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

### 阶段 4：实盘执行与签名下单 (Execution)

对比 `LLM_Win_Rate` 与 `Polymarket_Implied_Odds (市价)`：

* **买 YES 触发**：`LLM_Win_Rate > PM_Odds + 0.05`
* **买 NO 触发**：`LLM_Win_Rate < PM_Odds - 0.05`
* **实盘执行**：
  1. 调用 `wallet_manager` 检查真实的 USDC 余额和 MATIC (Gas)。
  2. 根据余额和凯利公式等计算真实的下注金额。
  3. 进行订单路由（Order Routing）并签名交易。
  4. 将交易广播到 Polygon 链/Polymarket 平台，获取真实的 `tx_hash`。
  5. 确认成功后，调用 `db_manager` 将订单与推理逻辑写入本地 SQLite，状态标记为 `SUBMITTED`。

### 阶段 5：链上结算与提款 (Post-Match Settlement)

* **触发机制**：由 `scheduler.py` 内部的定时器（或 Skill 平台的 Cron）定时触发执行 `main.py` 中的 `settlement_job`。
* **动作**：
  1. 查询本地数据库中状态为 `SUBMITTED` 或 `PENDING_SETTLEMENT` 的订单。
  2. 调用 Polymarket API / 智能合约，依靠 **UMA 预言机状态** 判断该市场是否已 `RESOLVED`。
* **结算提款**：
  - 如果预言机判定为赢单，系统自动发起一笔链上的 `Claim`（索赔提取）交易，将赢得的 USDC 提回钱包。完成提取后，本地状态更新为 `WIN` 并记录真实 PnL。
  - 如果输单，将状态更新为 `LOSS`。

---

## 三、 SQLite 数据库设计 (db_manager.py)

实盘状态下，不再使用虚拟的 `portfolio` 表记账，真实资金由链上查询。数据库降级为记录 LLM 推理和订单状态的日志簿。
核心表为：`live_trades`。

### 实盘交易记录 (live_trades)
用于全面记录系统下过的每一笔真实订单及关联的链上信息。

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键自增 |
| `timestamp` | DATETIME | 下单时间 |
| `match_name` | TEXT | 比赛名称 (如 LAL vs DEN) |
| `pm_condition_id` | TEXT | Polymarket 的唯一事件 ID |
| `side` | TEXT | `YES` 或 `NO` 或者具体的队名 |
| `buy_price` | REAL | 真实的平均执行价 |
| `amount` | REAL | 真实下注金额 (USDC) |
| `ai_prob` | REAL | LLM 预测胜率 |
| `pm_prob` | REAL | 下单时的市场隐含胜率 |
| `llm_model` | TEXT | 使用的 LLM 模型 |
| `llm_reasoning` | TEXT | LLM 给出的下单理由 (用于人工复盘) |
| `tx_hash` | TEXT | 链上交易哈希 |
| `status` | TEXT | `SUBMITTED`, `PENDING_SETTLEMENT`, `WIN`, `LOSS`, `FAILED` |
| `pnl` | REAL | 盈亏金额（扣除 Gas 后净利润/亏损） |

---


