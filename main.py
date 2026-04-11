import os
import sys
import logging
import json

# Ensure environment variables are loaded from .env
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                os.environ[key] = val

from data_engine import get_todays_matches, get_market_odds, get_nba_intelligence, get_game_result
from llm_analyzer import analyze_match
from db_manager import init_db, insert_trade, get_balance, get_pending_trades, update_trade_settlement

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def daily_setup_and_execution():
    """
    Main pipeline coordinating Stages 1 to 4.
    """
    logger.info("=== Starting Daily Pipeline ===")
    
    # Ensure DB is initialized
    init_db()
    
    # Stage 1: Global Initialization
    matches = get_todays_matches()
    
    for match in matches:
        match_name = match["match_name"]
        logger.info(f"--- Processing {match_name} ---")
        
        if "Final" in match.get("status", ""):
            logger.info(f"[{match_name}] Match is already Final. Skipping.")
            continue
            
        try:
            # Stage 2: Data Aggregation
            print(match)
            odds = get_market_odds(match)
            if not odds:
                continue
                
            intel = get_nba_intelligence(match_name)
            
            # Stage 3: Risk & Prediction (LLM Reasoning Loop)
            llm_response = analyze_match(match_name, odds, intel)
            if not llm_response:
                continue
                
            risk = llm_response.get("risk_assessment", {})
            if risk.get("status") == "FAIL":
                logger.warning(f"[{match_name}] Risk Gatekeeper FAIL. Reason: {risk.get('risk_notes')}")
                continue
                
            decision = llm_response.get("decision", {})
            action = decision.get("action")
            reasoning = decision.get("reasoning", "No reason provided")
            
            if action == "SKIP":
                logger.warning(f"[{match_name}] Skipped by LLM. Reason: {reasoning}")
                continue
                
            analysis = llm_response.get("analysis", {})
            home_prob = analysis.get("home_true_probability", 0.0)
            away_prob = analysis.get("away_true_probability", 0.0)
            
            # Stage 4: Execution Simulation
            pm_yes_prob = odds["yes_price"]
            pm_no_prob = odds["no_price"]
            condition_id = odds["condition_id"]
            yes_team = odds["yes_team"]
            no_team = odds["no_team"]
            
            # Dynamically size bet: 10% of current portfolio balance
            balance = get_balance()
            if balance <= 0:
                logger.warning(f"[{match_name}] Insufficient portfolio balance: {balance} USDC. Skipping.")
                continue
                
            bet_amount = round(balance * 0.10, 2)
            
            edge_found = False
            trade_side = None
            trade_price = 0.0
            
            away_abbr, home_abbr = match_name.split(" vs ")
            # Try to map true prob to yes/no team
            if yes_team.upper() == home_abbr.upper() or yes_team in match.get("home_team", ""):
                ai_prob = home_prob
            else:
                ai_prob = away_prob
                
            if action == "BUY YES":
                trade_side = yes_team
                trade_price = round(pm_yes_prob * 1.005, 4) 
                edge_found = True
                logger.info(f"[{match_name}] LLM executed BUY YES. Buying {trade_side}.")
            elif action == "BUY NO":
                trade_side = no_team
                trade_price = round(pm_no_prob * 1.005, 4)
                edge_found = True
                logger.info(f"[{match_name}] LLM executed BUY NO. Buying {trade_side}.")
            else:
                logger.info(f"[{match_name}] LLM recommended SKIP. Holding.")
                
            if edge_found and trade_side:
                # Record execution to database
                insert_trade(
                    match_name=match_name,
                    pm_condition_id=condition_id,
                    side=trade_side,
                    buy_price=trade_price,
                    amount=bet_amount,
                    ai_prob=ai_prob,
                    pm_prob=pm_yes_prob if trade_side == yes_team else pm_no_prob,
                    reasoning=reasoning,
                    llm_model=llm_response.get("llm_model", "unknown")
                )
        except Exception as e:
            logger.error(f"[{match_name}] Unexpected error processing match: {e}", exc_info=True)
            continue
    
    logger.info("=== Daily Pipeline Done. Invoking Agent for Summary ===")
    os.system("""openclaw agent --channel telegram --to 7162183556 --reply-channel telegram --reply-to 7162183556 --message "我是系统 cron：今天 NBA_Alpha_Agent 数据初始化和模拟下注已完成。请你读取 ~/.openclaw/workspace/skills/nba_alpha_agent/data/paper_ledger.db 今天新增的 PENDING 订单，如果数量大于 0，向我汇报下注了哪些队伍和简单理由；如果没有订单，向我报告今天没有下注。" """)

def settlement_job():
    """
    Stage 5: Daily Settlement of pending trades.
    Queries real NBA scores via nba_api (primary) and Polymarket (secondary).
    Trades that cannot yet be determined stay PENDING for the next run.
    """
    logger.info("=== Starting Settlement Job ===")

    pending_trades = get_pending_trades()
    if not pending_trades:
        logger.info("No pending trades to settle. Skipping.")
        os.system("""openclaw agent --channel telegram --to 7162183556 --reply-channel telegram --reply-to 7162183556 --message "我是系统 cron：今天 NBA_Alpha_Agent 结算环节已完成。请查询 ~/.openclaw/workspace/skills/nba_alpha_agent/data/paper_ledger.db，如果昨天或今天有已结算的订单，向我汇报盈亏和总资金；如果没有结算订单，就报告没有订单需要结算。" """)
        return

    for trade in pending_trades:
        match_name = trade['match_name']
        trade_id   = trade['id']
        amount     = trade['amount']
        buy_price  = trade['buy_price']
        side       = trade['side']
        condition_id = trade.get('pm_condition_id', '')

        logger.info(f"Checking Trade #{trade_id}: {side} on {match_name}...")

        result = get_game_result(match_name, condition_id, side)
        status  = result["status"]
        method  = result["method"]
        details = result["details"]

        if status == "PENDING":
            logger.info(f"[{match_name}] Trade #{trade_id} still PENDING ({method}): {details}")
            continue

        if status == "WIN":
            if buy_price < 0.05:
                # Guard: near-zero price would produce unrealistic PnL; treat as LOSS
                logger.warning(f"[{match_name}] Trade #{trade_id} WIN but buy_price={buy_price} < 0.05 — marking LOSS to prevent bad PnL.")
                update_trade_settlement(trade_id, "LOSS", -amount)
                continue
            profit = round((amount / buy_price) - amount, 2)
            update_trade_settlement(trade_id, "WIN", profit)
            logger.info(f"[{match_name}] Trade #{trade_id} -> WIN  +{profit} USDC | {details}")
        else:
            loss = -amount
            update_trade_settlement(trade_id, "LOSS", loss)
            logger.info(f"[{match_name}] Trade #{trade_id} -> LOSS -{amount} USDC | {details}")

    logger.info("=== Settlement Job Finished. Invoking Agent for Summary ===")
    os.system("""openclaw agent --channel telegram --to 7162183556 --reply-channel telegram --reply-to 7162183556 --message "我是系统 cron：今天 NBA_Alpha_Agent 结算环节已完成。请你查询 ~/.openclaw/workspace/skills/nba_alpha_agent/data/paper_ledger.db 里最近结算完成的订单结果（WIN/LOSS）、盈亏，以及 portfolio 总资金，并向我做汇报总结。" """)


if __name__ == "__main__":
    # Test execution manually
    daily_setup_and_execution()
