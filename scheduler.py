import schedule
import time
import logging
from db_manager import get_pending_trades, update_trade_settlement
from main import daily_setup_and_execution

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def settlement_job():
    """
    Stage 5: Daily Settlement of pending trades.
    Runs every day to simulate checking actual NBA scores via API.
    """
    logger.info("=== Starting Settlement Job ===")
    
    pending_trades = get_pending_trades()
    if not pending_trades:
        logger.info("No pending trades to settle. Skipping.")
        return
        
    for trade in pending_trades:
        match_name = trade['match_name']
        trade_id = trade['id']
        amount = trade['amount']
        
        logger.info(f"Settling Trade #{trade_id} for {match_name}...")
        
        # In a real scenario, call NBA API and compare with Polymarket condition_id outcome
        # Stub: Randomly assign WIN or LOSS
        import random
        is_win = random.choice([True, False])
        
        if is_win:
            # Simple PnL calculation: (amount / buy_price) - amount
            buy_price = trade['buy_price']
            profit = round((amount / buy_price) - amount, 2)
            update_trade_settlement(trade_id, "WIN", profit)
        else:
            # Total loss of wagered amount
            loss = -amount
            update_trade_settlement(trade_id, "LOSS", loss)
            
    logger.info("=== Settlement Job Finished ===")

def start_scheduler():
    """
    Run loops for defined cron schedules.
    - 10:00 AM Eastern time setup.
    - 02:00 AM Eastern time settlement.
    """
    logger.info("Starting OpenClaw NBA Alpha Agent Scheduler...")
    
    # schedule uses local time by default; assuming server runs on US Eastern time
    schedule.every().day.at("10:00").do(daily_setup_and_execution)
    schedule.every().day.at("02:00").do(settlement_job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # For standalone manual testing
    # settlement_job()
    start_scheduler()
