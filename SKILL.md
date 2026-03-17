---
name: nba_alpha_agent
version: 1.0.0
description: NBA Alpha Agent - Automated quantitative NBA sports betting and arbitrage simulation system
entry_point: main.py
env:
  DASHSCOPE_API_KEY:
    required: true
    description: DashScope / Qwen LLM API key for match analysis
  CTG_SESSION_ID:
    required: false
    description: Cleaning the Glass session cookie for advanced stats. Leave empty to skip CTG data.
triggers:
  schedule:
    - cron: "0 14 * * *"
      action: daily_setup_and_execution
      timezone: America/New_York
      description: Daily initialization, data aggregation and simulation trading
    - cron: "0 2 * * *"
      action: settlement_job
      timezone: America/New_York
      description: Daily settlement of pending trades via NBA API + Polymarket
---

# 🏀 NBA Alpha Agent

An automated quantitative NBA sports betting and arbitrage simulation system. The Alpha Agent scrapes real-time market odds from Polymarket and combines them with comprehensive NBA data (injuries, rest context, advanced analytics) to identify Positive Expected Value (+EV) betting opportunities, orchestrated by an LLM.

## Agent Workflow

1. **Daily Initialization** (`daily_setup_and_execution` in `main.py`): Fetches today's NBA matches from Polymarket Gamma API.
2. **Data Assembly** (`data_engine.py`): For each match, retrieves market odds, injury reports, back-to-back rest situations, and advanced matchup statistics from Cleaning the Glass, CBS Sports, and Underdog Lineups.
3. **LLM Reasoning Loop** (`llm_analyzer.py`): Sends compiled match context to Qwen/DashScope LLM acting as a cold-blooded sports analyst.
   - **Risk Gatekeeper**: Blocks bets on highly uncertain games (e.g., star players GTD, major trades).
   - **Edge Finder**: Calculates *True Probability* vs. Polymarket implied probability to identify mispriced lines.
4. **Execution** (`db_manager.py`): If a +EV edge is found (`BUY YES` or `BUY NO`), bets 10% of portfolio balance and records the mock trade to a local SQLite ledger (`data/paper_ledger.db`).
5. **Settlement** (`settlement_job` in `main.py`, runs at 2 AM EST): Queries real NBA scores via `nba_api` (primary) and Polymarket resolution (secondary) to settle pending trades, updating portfolio balance accordingly.

## Project Structure

```
nba-alpha-agent/
├── main.py              # Core orchestrator: daily_setup_and_execution(), settlement_job()
├── data_engine.py       # Data aggregator (Polymarket odds, NBA Stats, Injuries, CTG)
├── llm_analyzer.py      # LLM reasoning loop: risk assessment and odds analysis
├── db_manager.py        # SQLite logic for paper trading ledger
├── scheduler.py         # Autonomous cron daemon (10 AM setup, 2 AM settlement)
├── requirements.txt     # Python dependencies
└── data/
    └── paper_ledger.db  # (Generated) SQLite trade history database
```

## Setup

```bash
pip install -r requirements.txt
```

Set the following environment variables before running:

| Variable | Required | Description |
|---|---|---|
| `DASHSCOPE_API_KEY` | ✅ Yes | DashScope / Qwen LLM API key |
| `CTG_SESSION_ID` | ❌ No | Cleaning the Glass session cookie for advanced stats |

## Running Manually

```bash
# Run today's full pipeline once
python main.py

# Run the autonomous scheduler (10 AM setup + 2 AM settlement, EST)
python scheduler.py
```
