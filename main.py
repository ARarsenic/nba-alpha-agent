import logging
import json
import os
import requests
from data_engine import get_todays_matches, get_market_odds, get_nba_intelligence, get_game_result
from llm_analyzer import analyze_match
from db_manager import init_db, insert_trade, get_unsettled_trades, update_trade_settlement
from wallet_manager import WalletManager

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.constants import POLYGON

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Polymarket CTF Exchange Address on Polygon (Spender for USDC to trade)
PM_CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

def _get_token_ids_for_condition(condition_id: str) -> tuple:
    """Helper to get Polymarket yes_token_id and no_token_id from condition_id."""
    try:
        url = "https://gamma-api.polymarket.com/markets"
        params = {"conditionId": condition_id}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list):
            tokens = data[0].get("tokens", [])
            # Assuming outcome 0 is YES, outcome 1 is NO
            if len(tokens) >= 2:
                return tokens[0]["token_id"], tokens[1]["token_id"]
    except Exception as e:
        logger.error(f"Failed to fetch token IDs for condition {condition_id}: {e}")
    return None, None

def daily_setup_and_execution():
    """
    Main pipeline coordinating Stages 1 to 4 with Live Trading via py_clob_client.
    """
    logger.info("=== Starting Live Daily Pipeline ===")
    
    init_db()
    
    try:
        wallet = WalletManager()
    except Exception as e:
        logger.error(f"Failed to initialize wallet: {e}")
        return
        
    pol_balance = wallet.get_pol_balance()
    if pol_balance < 0.05:
        logger.error(f"Insufficient POL for gas ({pol_balance} POL). Halting execution.")
        return
        
    initial_usdc_balance = wallet.get_usdc_balance()
    logger.info(f"Starting balance: {initial_usdc_balance} USDC | {pol_balance} POL")
    
    if initial_usdc_balance < 2.0:
        logger.error("USDC balance below minimum bet size (2.0 USDC). Halting execution.")
        return

    try:
        # Initialize Polymarket CLOB Client
        host = "https://clob.polymarket.com"
        client = ClobClient(host, key=wallet.account.key.hex(), chain_id=137, funder=wallet.account.address, signature_type=0)
        client.set_creds(client.create_or_derive_creds())
        logger.info("Polymarket CLOB client initialized and authenticated.")
    except Exception as e:
        logger.error(f"Failed to initialize Polymarket CLOB client: {e}")
        return
        
    # Approve Polymarket Router to spend USDC for trading
    wallet.approve_usdc(PM_CTF_EXCHANGE, initial_usdc_balance)
    
    matches = get_todays_matches()
    for match in matches:
        match_name = match["match_name"]
        logger.info(f"--- Processing {match_name} ---")
        
        if "Final" in match.get("status", ""):
            logger.info(f"[{match_name}] Match is already Final. Skipping.")
            continue
            
        try:
            # Stage 2: Data Aggregation
            odds = get_market_odds(match)
            if not odds:
                continue
                
            intel = get_nba_intelligence(match_name)
            
            # Stage 3: Risk & Prediction
            llm_response = analyze_match(match_name, odds, intel)
            if not llm_response:
                continue
                
            risk = llm_response.get("risk_assessment", {})
            if risk.get("status") == "FAIL":
                logger.warning(f"[{match_name}] Risk Gatekeeper FAIL. Reason: {risk.get('risk_notes')}")
                continue
                
            decision = llm_response.get("decision", {})
            action = decision.get("action")
            target_team = decision.get("target_team")
            reasoning = decision.get("reasoning", "No reason provided")
            
            if action == "SKIP":
                logger.warning(f"[{match_name}] Skipped by LLM. Reason: {reasoning}")
                continue
                
            analysis = llm_response.get("analysis", {})
            home_prob = analysis.get("home_true_probability", 0.0)
            away_prob = analysis.get("away_true_probability", 0.0)
            
            # Stage 4: Live Execution
            pm_yes_prob = odds["yes_price"]
            pm_no_prob = odds["no_price"]
            condition_id = odds["condition_id"]
            yes_team = odds["yes_team"]
            no_team = odds["no_team"]
            
            current_usdc = wallet.get_usdc_balance()
            if current_usdc < 2.0:
                logger.warning(f"[{match_name}] Insufficient USDC balance midway: {current_usdc}. Skipping further bets.")
                break
                
            bet_amount = round(min(50.0, current_usdc * 0.10), 2)
            if bet_amount < 2.0:
                continue
            
            edge_found = False
            trade_side = None
            target_price = 0.0
            is_yes = True
            
            away_abbr, home_abbr = match_name.split(" vs ")
            if yes_team.upper() == home_abbr.upper() or yes_team in match.get("home_team", ""):
                ai_prob = home_prob
            else:
                ai_prob = away_prob
                
            if action == "BUY":
                if not target_team:
                    logger.warning(f"[{match_name}] LLM returned BUY but no target_team. Skipping.")
                    continue
                    
                target_upper = target_team.upper()
                yes_upper = yes_team.upper()
                no_upper = no_team.upper()
                
                if target_upper in yes_upper or yes_upper in target_upper:
                    trade_side = yes_team
                    target_price = round(min(0.99, pm_yes_prob * 1.005), 3) # Max price we are willing to pay (+0.5% slippage)
                    edge_found = True
                    is_yes = True
                elif target_upper in no_upper or no_upper in target_upper:
                    trade_side = no_team
                    target_price = round(min(0.99, pm_no_prob * 1.005), 3)
                    edge_found = True
                    is_yes = False
                else:
                    logger.warning(f"[{match_name}] Mismatch between target_team '{target_team}' and PM teams (yes: {yes_team}, no: {no_team}). Skipping.")
                    continue
                
            if edge_found and trade_side:
                yes_token, no_token = _get_token_ids_for_condition(condition_id)
                token_to_buy = yes_token if is_yes else no_token
                
                if not token_to_buy:
                    logger.error(f"[{match_name}] Could not resolve token_id for condition {condition_id}")
                    continue
                
                logger.info(f"[{match_name}] Submitting limit FOK order to Buy {trade_side} | Size: {bet_amount} | Max Price: {target_price}")
                
                # Abstracting creation and posting of an order onto the Orderbook
                order_args = OrderArgs(
                    price=target_price,
                    size=bet_amount,
                    side="BUY", 
                    token_id=token_to_buy
                )
                try:
                    signed_order = client.create_order(order_args)
                    resp = client.post_order(signed_order, OrderType.FOK)
                    
                    if resp and resp.get("success"):
                        order_id = resp.get("orderID")
                        logger.info(f"[{match_name}] Order Success! OrderID: {order_id}")
                        
                        insert_trade(
                            match_name=match_name,
                            pm_condition_id=condition_id,
                            side=trade_side,
                            buy_price=target_price,
                            amount=bet_amount,
                            ai_prob=ai_prob,
                            pm_prob=pm_yes_prob if is_yes else pm_no_prob,
                            reasoning=reasoning,
                            tx_hash=order_id, # Safely use Order ID as tracking receipt 
                            llm_model=llm_response.get("llm_model", "unknown")
                        )
                    else:
                        logger.error(f"[{match_name}] Order Post Failed: {resp.get('errorMsg', resp)}")
                except Exception as e:
                    logger.error(f"[{match_name}] Order creation/execution exception: {e}")

        except Exception as e:
            logger.error(f"[{match_name}] Unexpected error processing match: {e}", exc_info=True)
            continue

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

    logger.info("=== Settlement Job Finished ===")


if __name__ == "__main__":
    # Test execution manually
    daily_setup_and_execution()
    #settlement_job()
