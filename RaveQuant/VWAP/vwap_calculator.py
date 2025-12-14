"""
VWAP Calculator - Rolling Windows (1h + 4h)
-------------------------------------------
Reads raw perps trades, calculates rolling VWAP with 1h and 4h windows.

INPUT: Vault\raw\okx\trades_perps\{INSTID}\{DATE}.jsonl
OUTPUT: Vault\derived\vwap\okx\perps\{INSTID}\vwap_1m.jsonl
STATE: Vault\state\vwap\okx\perps\{INSTID}.state.json
"""

import json
import logging
from pathlib import Path
from decimal import Decimal, getcontext
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from dataclasses import dataclass
from collections import deque
import argparse

# Set high precision for Decimal operations
getcontext().prec = 50

# Configuration
VAULT_BASE = Path(r"C:\Users\M.R Bear\Documents\RaveQuant\Rave_Quant_Vault")

# Window sizes (minutes)
WINDOW_1H = 60
WINDOW_4H = 240

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('VWAP_Calculator')


@dataclass
class Trade:
    """Trade record from JSONL."""
    timestamp_utc: str  # ISO format
    exchange: str
    market: str
    instId: str
    symbol_canon: str
    trade_id: str
    side: str
    price: str
    qty_contracts: str
    ctVal: str
    ctMult: str
    ctType: str
    
    @property
    def timestamp(self) -> datetime:
        """Parse timestamp to datetime."""
        return datetime.fromisoformat(self.timestamp_utc.replace('Z', '+00:00'))
    
    @property
    def notional(self) -> Decimal:
        """
        Calculate notional value.
        notional = qty_contracts × ctVal × price
        """
        qty = Decimal(self.qty_contracts)
        ct_val = Decimal(self.ctVal)
        price = Decimal(self.price)
        
        return qty * ct_val * price
    
    @property
    def price_decimal(self) -> Decimal:
        """Price as Decimal."""
        return Decimal(self.price)



@dataclass
class VWAPState:
    """State tracker for VWAP calculation."""
    last_timestamp_utc: Optional[str]  # ISO format
    last_trade_id: Optional[str]
    last_minute_processed: Optional[str]  # ISO minute timestamp (YYYY-MM-DDTHH:MM:00Z)


class RollingWindow:
    """Maintains rolling window of trades for VWAP calculation."""
    
    def __init__(self, window_minutes: int):
        self.window_minutes = window_minutes
        self.trades: deque[Trade] = deque()
    
    def add_trade(self, trade: Trade):
        """Add trade to window."""
        self.trades.append(trade)
    
    def trim_to_window(self, current_time: datetime):
        """Remove trades older than window size."""
        cutoff_time = current_time - timedelta(minutes=self.window_minutes)
        
        # Remove from left (oldest) while they're outside window
        while self.trades and self.trades[0].timestamp < cutoff_time:
            self.trades.popleft()
    
    def calculate_vwap(self) -> Optional[Decimal]:
        """
        Calculate VWAP for current window.
        VWAP = Σ(price × notional) / Σ(notional)
        """
        if not self.trades:
            return None
        
        sum_price_volume = Decimal('0')
        sum_volume = Decimal('0')
        
        for trade in self.trades:
            notional = trade.notional
            price = trade.price_decimal
            
            sum_price_volume += price * notional
            sum_volume += notional
        
        if sum_volume == 0:
            return None
        
        return sum_price_volume / sum_volume
    
    def get_trade_count(self) -> int:
        """Get number of trades in window."""
        return len(self.trades)



def floor_to_minute(ts: datetime) -> datetime:
    """Floor timestamp to nearest minute."""
    return ts.replace(second=0, microsecond=0)


def load_state(inst_id: str) -> VWAPState:
    """Load state for instrument, or create new if doesn't exist."""
    state_file = VAULT_BASE / 'state' / 'vwap' / 'okx' / 'perps' / f'{inst_id}.state.json'
    
    if not state_file.exists():
        return VWAPState(
            last_timestamp_utc=None,
            last_trade_id=None,
            last_minute_processed=None
        )
    
    with open(state_file, 'r') as f:
        data = json.load(f)
    
    return VWAPState(**data)


def save_state(inst_id: str, state: VWAPState):
    """Save state for instrument."""
    state_file = VAULT_BASE / 'state' / 'vwap' / 'okx' / 'perps' / f'{inst_id}.state.json'
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(state_file, 'w') as f:
        json.dump({
            'last_timestamp_utc': state.last_timestamp_utc,
            'last_trade_id': state.last_trade_id,
            'last_minute_processed': state.last_minute_processed
        }, f, indent=2)


def read_trade_files(inst_id: str) -> List[Path]:
    """Get all trade JSONL files for instrument, sorted by date."""
    trade_dir = VAULT_BASE / 'raw' / 'okx' / 'trades_perps' / inst_id
    
    if not trade_dir.exists():
        return []
    
    # Get all JSONL files, sorted by name (YYYY-MM-DD.jsonl)
    files = sorted(trade_dir.glob('*.jsonl'))
    return files


def parse_trades(filepath: Path, state: VWAPState) -> List[Trade]:
    """
    Read trades from JSONL file.
    Only return trades AFTER the state cursor.
    """
    trades = []
    
    with open(filepath, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            
            data = json.loads(line)
            trade = Trade(**data)
            
            # Skip if before or equal to cursor
            if state.last_timestamp_utc is not None:
                if trade.timestamp_utc < state.last_timestamp_utc:
                    continue
                
                if trade.timestamp_utc == state.last_timestamp_utc:
                    # Same timestamp - check trade_id
                    if state.last_trade_id is not None:
                        if trade.trade_id <= state.last_trade_id:
                            continue
            
            trades.append(trade)
    
    return trades



def write_vwap_output(inst_id: str, minute_ts: datetime, vwap_1h: Optional[Decimal], 
                      vwap_4h: Optional[Decimal], trade_count_1h: int, trade_count_4h: int):
    """
    Write VWAP output to derived JSONL.
    Deduplicates by checking if minute already written.
    """
    output_dir = VAULT_BASE / 'derived' / 'vwap' / 'okx' / 'perps' / inst_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / 'vwap_1m.jsonl'
    
    minute_str = minute_ts.strftime('%Y-%m-%dT%H:%M:00Z')
    
    # Check if this minute already exists in output
    if output_file.exists():
        with open(output_file, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get('window_start_utc') == minute_str:
                    return  # Already written
    
    # Build VWAP record
    vwap_record = {
        'window_start_utc': minute_str,
        'instId': inst_id,
        'exchange': 'okx',
        'market': 'perp',
        'vwap_1h': str(vwap_1h) if vwap_1h is not None else None,
        'vwap_4h': str(vwap_4h) if vwap_4h is not None else None,
        'trade_count_1h': trade_count_1h,
        'trade_count_4h': trade_count_4h
    }
    
    # Append to output file
    with open(output_file, 'a') as f:
        f.write(json.dumps(vwap_record) + '\n')



def process_inst_id(inst_id: str):
    """
    Main processing loop for an instrument.
    1. Load state
    2. Read trade files
    3. Parse new trades
    4. Maintain rolling windows
    5. Output VWAP every minute
    6. Update state
    """
    logger.info(f"Processing VWAP for {inst_id}")
    
    # Load state
    state = load_state(inst_id)
    logger.info(f"Loaded state: last_ts={state.last_timestamp_utc}, last_minute={state.last_minute_processed}")
    
    # Initialize rolling windows
    window_1h = RollingWindow(WINDOW_1H)
    window_4h = RollingWindow(WINDOW_4H)
    
    # Get trade files
    trade_files = read_trade_files(inst_id)
    if not trade_files:
        logger.warning(f"No trade files found for {inst_id}")
        return
    
    logger.info(f"Found {len(trade_files)} trade files")
    
    # Process all files
    all_trades = []
    for filepath in trade_files:
        trades = parse_trades(filepath, state)
        all_trades.extend(trades)
    
    if not all_trades:
        logger.info(f"No new trades to process for {inst_id}")
        return
    
    # Sort trades by (timestamp, trade_id)
    all_trades.sort(key=lambda t: (t.timestamp_utc, t.trade_id))
    
    logger.info(f"Processing {len(all_trades)} new trades")
    
    # Track current minute for output
    current_minute = None
    vwap_outputs = 0
    
    for trade in all_trades:
        trade_minute = floor_to_minute(trade.timestamp)
        
        # Add trade to both windows
        window_1h.add_trade(trade)
        window_4h.add_trade(trade)
        
        # Trim windows to their respective sizes
        window_1h.trim_to_window(trade.timestamp)
        window_4h.trim_to_window(trade.timestamp)
        
        # Check if we've moved to a new minute
        if current_minute is None or trade_minute > current_minute:
            # Skip if this minute was already processed
            if state.last_minute_processed is not None:
                last_minute = datetime.fromisoformat(state.last_minute_processed.replace('Z', '+00:00'))
                if trade_minute <= last_minute:
                    current_minute = trade_minute
                    continue
            
            # Calculate VWAPs for this minute
            vwap_1h = window_1h.calculate_vwap()
            vwap_4h = window_4h.calculate_vwap()
            
            # Write output
            write_vwap_output(
                inst_id,
                trade_minute,
                vwap_1h,
                vwap_4h,
                window_1h.get_trade_count(),
                window_4h.get_trade_count()
            )
            
            vwap_outputs += 1
            current_minute = trade_minute
        
        # Update state with this trade
        state.last_timestamp_utc = trade.timestamp_utc
        state.last_trade_id = trade.trade_id
    
    # Update last minute processed
    if current_minute is not None:
        state.last_minute_processed = current_minute.strftime('%Y-%m-%dT%H:%M:00Z')
    
    # Save state
    save_state(inst_id, state)
    
    logger.info(f"VWAP processing complete for {inst_id}")
    logger.info(f"Output {vwap_outputs} new 1-minute VWAP records")
    logger.info(f"State updated: last_minute={state.last_minute_processed}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Calculate rolling VWAP from trades')
    parser.add_argument('--instId', required=True, help='Instrument ID (e.g., BTC-USDT-SWAP)')
    
    args = parser.parse_args()
    
    try:
        process_inst_id(args.instId)
    except Exception as e:
        logger.error(f"Error processing {args.instId}: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
