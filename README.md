# 🏀 OpenClaw NBA Alpha Agent

An automated quantitative NBA sports betting and arbitrage simulation system. The Alpha Agent is designed to scrape realtime market odds from Polymarket and combine them with comprehensive NBA data (including injuries, rest context, and advanced analytics) to identify Positive Expected Value (+EV) betting opportunities. The entire pipeline is orchestrated by an LLM with advanced reasoning capabilities.

## 🚀 Key Features

- **Automated Daily Pipeline**: A CRON-based scheduler fetches the daily NBA slate, queries the Polymarket Gamma API for active prediction markets, and initiates the data aggregation process.
- **Deep Data Aggregation**: Synthesizes structured data from multiple sources:
  - **Polymarket APIs**: Extracts the latest Implied Probabilities (`YES`/`NO` prices).
  - **NBA Advanced Stats**: Team ratings, Four Factors, shot selection frequencies, and accuracy.
  - **Real-Time Injury Reports**: Live tracking of player status (`OUT`, `GTD`) from CBS Sports and Underdog Lineups.
- **LLM-Driven Risk & Edge Identification**: 
  - **Risk Gatekeeper**: Prevents betting on highly uncertain games (e.g., star players GTD, major trades).
  - **Quantitative Edge Finding**: Calculates the *True Probability* of a team winning based solely on cold, hard data, comparing it against the market's implied probability to find mispriced lines.
- **Local Paper Trading Ledger**: Executes simulated trades locally via SQLite (`db_manager.py`), saving the action, reasoning, AI probability, and wager amount to build a robust track record before committing real capital.

## 📂 Project Structure

```text
nba-alpha-agent/
├── main.py              # The core orchestrator pipeline script
├── data_engine.py       # Data aggregator (Polymarket odds, NBA Stats, Injuries)
├── llm_analyzer.py      # LLM reasoning loop handling risk assessment and odds analysis
├── db_manager.py        # SQLite database logic for paper trading ledgers
├── scheduler.py         # Daily cron job daemon setup
├── requirements.txt     # Python dependencies
└── data/
    └── paper_ledger.db  # (Generated) SQLite Database storing trade history
```

## 🧠 The Agent Workflow

1. **Daily Initialization**: Fetches the day's matches.
2. **Data Assembly**: For each match, retrieves market odds, injury reports, back-to-back rest situations, and matchup statistics.
3. **LLM Reasoning Loop**: Sends the compiled match context to the LLM (e.g. OpenAI / Qwen) acting as a cold-blooded sports analyst. 
4. **Execution**: If the LLM identifies a +EV edge and recommends a `BUY YES` or `BUY NO`, the agent sizes a bet dynamically (10% of the portfolio balance) and writes the mock trade to the `paper_trades` DB table.
5. **Settlement**: (Mocked) Runs daily to evaluate if pending trades resulted in a win or loss, updating the portfolio's balance accordingly.

## 🔮 Future Roadmap

- **Expert Text Analysis Integration**: Scraping and cleaning whitelist sources (e.g., Cleaning the Glass article text previews) to feed pure tactical and matchup advantages into the LLM, stripping away emotional narratives.
- **On-Chain Execution**: Transitioning from a paper trading ledger to interacting directly with the Polymarket smart contracts using an agent wallet for live automated betting.

## 🛠 Setup & Installation

1. **Clone & Install Dependencies**
   ```bash
   git clone <repo-url>
   cd nba-alpha-agent
   pip install -r requirements.txt
   ```

2. **Configure API Keys**
   Ensure you set up your API keys (e.g., OpenAI API Key) in an `.env` file or directly in your environment variables before running, as required by `llm_analyzer.py`.

3. **Run the Daily Pipeline**
   To do a manual test run for the current day's matches:
   ```bash
   python main.py
   ```

4. **Start the Autonomous Scheduler**
   To leave the agent running autonomously in the background (fetches matchups at 10 AM EST and settles at 2 AM EST):
   ```bash
   python scheduler.py
   ```
