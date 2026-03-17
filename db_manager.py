import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = 'data/paper_ledger.db'

def init_db():
    """
    Initialize a lightweight SQLite database to match the whitepaper schema.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create the paper_trades table according to whitepaper design
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            match_name TEXT NOT NULL,
            pm_condition_id TEXT,
            side TEXT NOT NULL,
            buy_price REAL NOT NULL,
            amount REAL NOT NULL,
            ai_prob REAL,
            pm_prob REAL,
            llm_model TEXT,
            llm_reasoning TEXT,
            status TEXT NOT NULL,
            pnl REAL
        )
    ''')
    
    # Check if llm_model column exists (for migration)
    cursor.execute("PRAGMA table_info(paper_trades)")
    columns = [col[1] for col in cursor.fetchall()]
    if "llm_model" not in columns:
        logger.info("Migrating paper_trades table: adding llm_model column.")
        cursor.execute("ALTER TABLE paper_trades ADD COLUMN llm_model TEXT DEFAULT 'unknown'")
    
    # Create portfolio table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY,
            balance REAL NOT NULL
        )
    ''')
    
    cursor.execute('SELECT balance FROM portfolio WHERE id = 1')
    res = cursor.fetchone()
    if not res:
        cursor.execute('INSERT INTO portfolio (id, balance) VALUES (1, 1000.0)')
        logger.info("Initialized portfolio with 1000 USDC.")
        
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def get_balance() -> float:
    """
    Get the current portfolio balance.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM portfolio WHERE id = 1')
    balance = cursor.fetchone()[0]
    conn.close()
    return balance

def insert_trade(match_name: str, pm_condition_id: str, side: str, buy_price: float, amount: float, ai_prob: float, pm_prob: float, reasoning: str, llm_model: str = "unknown"):
    """
    Insert a new mock trade into the database with PENDING status.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO paper_trades (
            match_name, pm_condition_id, side, buy_price, amount, ai_prob, pm_prob, llm_model, llm_reasoning, status, pnl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0.0)
    ''', (match_name, pm_condition_id, side, buy_price, amount, ai_prob, pm_prob, llm_model, reasoning))
    
    # Deduct bet amount from portfolio balance
    cursor.execute('''
        UPDATE portfolio SET balance = balance - ? WHERE id = 1
    ''', (amount,))
    
    conn.commit()
    conn.close()
    logger.info(f"Inserted PENDING trade: {side} {amount} USDC on {match_name} @ {buy_price}")

def get_pending_trades():
    """
    Retrieve all trades with PENDING status for settlement.
    """
    conn = sqlite3.connect(DB_PATH)
    # Return rows as dictionaries
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM paper_trades WHERE status = 'PENDING'")
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]

def update_trade_settlement(trade_id: int, new_status: str, pnl: float):
    """
    Update the status and PnL of a trade after settlement.
    new_status should be 'WIN' or 'LOSS'.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE paper_trades
        SET status = ?, pnl = ?
        WHERE id = ?
    ''', (new_status, pnl, trade_id))
    
    # Update portfolio balance based on settlement
    # If WIN, refund wager + profit
    # If LOSS, wager is already lost, so don't deduct it again
    amount = 0.0
    cursor.execute('SELECT amount FROM paper_trades WHERE id = ?', (trade_id,))
    row = cursor.fetchone()
    if row:
        amount = row[0]
        
    if new_status == "WIN":
        cursor.execute('''
            UPDATE portfolio SET balance = balance + ? + ? WHERE id = 1
        ''', (amount, pnl))
    
    conn.commit()
    conn.close()
    logger.info(f"Updated trade {trade_id} settlement: {new_status}, PnL: {pnl}")
