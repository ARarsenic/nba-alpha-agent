import json
import os
import logging
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()

# We can specify these in .env later, but provide sensible defaults for Polygon Mainnet
POLYGON_RPC_URL = os.environ.get("POLYGON_RPC_URL", "https://polygon.drpc.org")

# Bridged USDC token address on Polygon (Polygon POS Bridged)
_raw_usdc_address = os.environ.get("USDC_ADDRESS")
if not _raw_usdc_address:
    raise ValueError("USDC_ADDRESS not found in .env file. Please add USDC_ADDRESS to your .env.")
USDC_ADDRESS = Web3.to_checksum_address(_raw_usdc_address)

# Minimal ERC20 ABI to call balanceOf, approve, decimals, allowance
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]')

class WalletManager:
    def __init__(self, keystore_path: str = "data/keystore.json"):
        self.w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
        if not self.w3.is_connected():
            logger.error(f"Failed to connect to Polygon RPC at {POLYGON_RPC_URL}")
            raise ConnectionError("Web3 connection failed")
            
        self.keystore_path = keystore_path
        self.account = self._load_account()
        
        self.usdc_contract = self.w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
        try:
            self.usdc_decimals = self.usdc_contract.functions.decimals().call()
        except Exception:
            self.usdc_decimals = 6  # Fallback: USDC on Polygon typically has 6 decimals
            logger.warning("Failed to fetch USDC decimals, defaulting to 6")

    def _load_account(self):
        """Loads and decrypts the keystore file based on .env password."""
        password = os.environ.get("KEYSTORE_PASSWORD")
        if not password:
            raise ValueError("KEYSTORE_PASSWORD not found in .env file")
            
        if not os.path.exists(self.keystore_path):
            raise FileNotFoundError(f"Keystore file not found at {self.keystore_path}. Please generate a keystore first.")
            
        with open(self.keystore_path, 'r') as f:
            keystore_data = json.load(f)
            
        try:
            private_key = Account.decrypt(keystore_data, password)
            account = Account.from_key(private_key)
            logger.info(f"[WalletManager] Wallet decrypted successfully. Address: {account.address}")
            return account
        except ValueError as e:
            logger.error("[WalletManager] Failed to decrypt keystore. Is the KEYSTORE_PASSWORD correct?")
            raise e

    def get_pol_balance(self) -> float:
        """Returns the native POL balance for paying gas fees."""
        wei_balance = self.w3.eth.get_balance(self.account.address)
        return float(self.w3.from_wei(wei_balance, 'ether'))
        
    def get_usdc_balance(self) -> float:
        """Returns the actual USDC balance available for betting."""
        raw_balance = self.usdc_contract.functions.balanceOf(self.account.address).call()
        return raw_balance / (10 ** self.usdc_decimals)
        
    def sign_and_send_transaction(self, tx_dict: dict) -> str:
        """
        Signs and broadcasts a transaction hash.
        tx_dict should contain keys like 'to', 'value', 'data', etc.
        """
        # Auto-fill nonce, gasPrice, chainId if they are missing
        if 'nonce' not in tx_dict:
            tx_dict['nonce'] = self.w3.eth.get_transaction_count(self.account.address)
        if 'chainId' not in tx_dict:
            tx_dict['chainId'] = self.w3.eth.chain_id
        if 'gasPrice' not in tx_dict and 'maxFeePerGas' not in tx_dict:
            tx_dict['gasPrice'] = self.w3.eth.gas_price
            
        signed_tx = self.w3.eth.account.sign_transaction(tx_dict, private_key=self.account.key)
        
        try:
            # type ignore because send_raw_transaction might complain about HexBytes
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hex = tx_hash.hex()
            logger.info(f"[WalletManager] Transaction broadcasted successfully. Hash: {tx_hex}")
            return tx_hex
        except Exception as e:
            logger.error(f"[WalletManager] Failed to broadcast transaction: {e}")
            raise e
            
    def approve_usdc(self, spender_address: str, amount_usdc: float) -> str:
        """
        Approves a spender (e.g., a Polymarket Router Contract) to spend your USDC.
        Returns the tx_hash of the approval transaction, or "ALREADY_APPROVED" if sufficient allowance.
        """
        raw_amount = int(amount_usdc * (10 ** self.usdc_decimals))
        spender = Web3.to_checksum_address(spender_address)
        
        current_allowance = self.usdc_contract.functions.allowance(self.account.address, spender).call()
        if current_allowance >= raw_amount:
            logger.info(f"[WalletManager] Allowance for {spender} is already sufficient.")
            return "ALREADY_APPROVED"
            
        logger.info(f"[WalletManager] Approving {spender} for {amount_usdc} USDC...")
        tx = self.usdc_contract.functions.approve(spender, raw_amount).build_transaction({
            'from': self.account.address,
            'nonce': self.w3.eth.get_transaction_count(self.account.address),
            'gasPrice': self.w3.eth.gas_price
        })
        
        return self.sign_and_send_transaction(tx)


# =====================================================================
# Utility helper section: Used purely for local setup, not part of pipeline
# =====================================================================
def create_new_wallet_keystore(keystore_path: str = "data/keystore.json", password: str = None):
    """
    Utility function to create a brand new wallet and save it as a Keystore V3 JSON.
    DO NOT CALL this inside the pipeline, it's just for setup.
    """
    if not password:
        load_dotenv()
        password = os.environ.get("KEYSTORE_PASSWORD")
    if not password:
        raise ValueError("Password is required to encrypt the newly created keystore. Add KEYSTORE_PASSWORD to .env.")
        
    Account.enable_unaudited_hdwallet_features()
    acct, _ = Account.create_with_mnemonic()
    
    keystore_json = Account.encrypt(acct.key, password)
    
    os.makedirs(os.path.dirname(keystore_path), exist_ok=True)
    with open(keystore_path, 'w') as f:
        json.dump(keystore_json, f)
        
    logger.info(f"[Setup] New wallet successfully created!")
    logger.info(f"[Setup] Public Address: {acct.address}")
    logger.info(f"[Setup] Keystore file securely saved to: {keystore_path}")
    logger.info("[Setup] PLEASE FUND THIS WALLET WITH POL (GAS) AND USDC (FUNDS) BEFORE TRADING.")
    return acct.address


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # create_new_wallet_keystore()
    wallet = WalletManager()
    print(wallet.get_pol_balance())
    