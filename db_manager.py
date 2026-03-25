import sqlite3
import logging

logger = logging.getLogger(__name__)

DB_PATH = 'data/live_ledger.db'

def init_db():
    """
    Initialize the SQLite database for live trading.
    This database logs the AI reasoning and maps real blockchain execution states.
    It does NOT serve as a source of truth for assets or funds.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create the live_trades table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS live_trades (
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
            tx_hash TEXT,
            status TEXT NOT NULL,
            pnl REAL
        )
    ''')
    
    cursor.execute("PRAGMA table_info(live_trades)")
    columns = [col[1] for col in cursor.fetchall()]
    if "tx_hash" not in columns and len(columns) > 0:
        logger.info("Migrating live_trades table: adding tx_hash column.")
        cursor.execute("ALTER TABLE live_trades ADD COLUMN tx_hash TEXT")
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def insert_trade(match_name: str, pm_condition_id: str, side: str, buy_price: float, 
                 amount: float, ai_prob: float, pm_prob: float, reasoning: str, 
                 tx_hash: str, llm_model: str = "unknown"):
    """
    Insert a new LIVE trade into the database with SUBMITTED status.
    This should be called *after* receiving a successful tx_hash from wallet_manager.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO live_trades (
            match_name, pm_condition_id, side, buy_price, amount, ai_prob, pm_prob, 
            llm_model, llm_reasoning, tx_hash, status, pnl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', 0.0)
    ''', (match_name, pm_condition_id, side, buy_price, amount, ai_prob, pm_prob, llm_model, reasoning, tx_hash))
    
    conn.commit()
    conn.close()
    logger.info(f"Inserted SUBMITTED trade: {side} {amount} USDC on {match_name} @ {buy_price} [Tx: {tx_hash}]")

def get_unsettled_trades():
    """
    Retrieve all trades that haven't been finally settled on-chain.
    This includes 'SUBMITTED' and 'PENDING_SETTLEMENT' states.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM live_trades WHERE status IN ('SUBMITTED', 'PENDING_SETTLEMENT')")
    rows = cursor.fetchall()
    
    conn.close()
    return [dict(row) for row in rows]

def update_trade_settlement(trade_id: int, new_status: str, pnl: float):
    """
    Update the status and real PnL (net of gas) of a trade after blockchain settlement.
    new_status typically one of: 'WIN', 'LOSS', 'FAILED', 'PENDING_SETTLEMENT'
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE live_trades
        SET status = ?, pnl = ?
        WHERE id = ?
    ''', (new_status, pnl, trade_id))
    
    conn.commit()
    conn.close()
    logger.info(f"Updated trade {trade_id} settlement: {new_status}, PnL: {pnl}")
