"""
CVD Calculator from JSONL (No SQL)
----------------------------------
Reads raw trade JSONL files from vault, calculates CVD, outputs 1m buckets.

Strategy:
1. Process trades in strict order (timestamp_utc, trade_id numeric)
2. Maintain state per symbol (last_timestamp_utc, last_trade_id, last_cvd)
3. Calculate CVD: buy adds size_usd, sell subtracts size_usd
4. Aggregate to 1m windows, output to derived/cvd/okx/{symbol}/1m/
"""

import json
import logging
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
from dataclasses import dataclass
import argparse

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CVD_Calculator')

# Paths
VAULT_BASE = Path(r"C:\Users\M.R Bear\Documents\RaveQuant\Rave_Quant_Vault")


@dataclass
class CVDState:
    """State tracker for CVD calculation."""
    last_timestamp_utc: Optional[str]  # ISO format
    last_trade_id: Optional[str]
    last_cvd: str  # Decimal as string for JSON


@dataclass
class Trade:
    """Trade record from JSONL."""
    exchange: str
    symbol: str
    trade_id: str
    timestamp_utc: str  # ISO format
    price: str
    size: str
    side: str  # 'buy' or 'sell'
    
    @property
    def size_usd(self) -> Decimal:
        """Calculate size in USD."""
        return Decimal(self.price) * Decimal(self.size)
    
    @property
    def timestamp(self) -> datetime:
        """Parse timestamp to datetime."""
        return datetime.fromisoformat(self.timestamp_utc.replace('Z', '+00:00'))


def floor_to_minute(ts: datetime) -> datetime:
    """Floor timestamp to nearest minute."""
    return ts.replace(second=0, microsecond=0)


def load_state(symbol: str) -> CVDState:
    """Load state for symbol, or create new if doesn't exist."""
    state_file = VAULT_BASE / 'state' / 'cvd' / 'okx' / f'{symbol}.state.json'
    
    if not state_file.exists():
        return CVDState(
            last_timestamp_utc=None,
            last_trade_id=None,
            last_cvd="0"
        )
    
    with open(state_file, 'r') as f:
        data = json.load(f)
    
    return CVDState(**data)


def save_state(symbol: str, state: CVDState):
    """Save state for symbol."""
    state_file = VAULT_BASE / 'state' / 'cvd' / 'okx' / f'{symbol}.state.json'
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(state_file, 'w') as f:
        json.dump({
            'last_timestamp_utc': state.last_timestamp_utc,
            'last_trade_id': state.last_trade_id,
            'last_cvd': state.last_cvd
        }, f, indent=2)


def read_trade_files(symbol: str) -> List[Path]:
    """Get all trade JSONL files for symbol, sorted by date."""
    trade_dir = VAULT_BASE / 'raw' / 'okx' / 'trades' / symbol
    
    if not trade_dir.exists():
        return []
    
    # Get all JSONL files, sorted by name (YYYY-MM-DD.jsonl)
    files = sorted(trade_dir.glob('*.jsonl'))
    return files



def parse_trades(filepath: Path, state: CVDState) -> List[Trade]:
    """
    Read trades from JSONL file.
    Only return trades AFTER the state cursor (strictly increasing by timestamp, trade_id).
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
                    # Same timestamp - check trade_id (numeric comparison)
                    if state.last_trade_id is not None:
                        if int(trade.trade_id) <= int(state.last_trade_id):
                            continue
            
            trades.append(trade)
    
    return trades


def calculate_cvd_updates(trades: List[Trade], start_cvd: Decimal) -> Dict[datetime, Decimal]:
    """
    Calculate CVD for each 1m window.
    Returns dict of {window_start: cvd_value}
    """
    cvd = start_cvd
    windows = {}
    
    for trade in trades:
        # Update CVD
        if trade.side == 'buy':
            cvd += trade.size_usd
        elif trade.side == 'sell':
            cvd -= trade.size_usd
        else:
            logger.warning(f"Unknown side: {trade.side} for trade {trade.trade_id}")
            continue
        
        # Track CVD for this minute window
        window_start = floor_to_minute(trade.timestamp)
        windows[window_start] = cvd
    
    return windows



def write_cvd_outputs(symbol: str, windows: Dict[datetime, Decimal]):
    """
    Write CVD outputs to derived/cvd/okx/{symbol}/1m/YYYY-MM-DD.jsonl
    Deduplicates by reading existing file first and only appending new windows.
    """
    if not windows:
        return 0
    
    # Group by date
    by_date: Dict[str, Dict[datetime, Decimal]] = {}
    for window_start, cvd_value in windows.items():
        date_str = window_start.strftime('%Y-%m-%d')
        if date_str not in by_date:
            by_date[date_str] = {}
        by_date[date_str][window_start] = cvd_value
    
    total_written = 0
    
    for date_str, date_windows in by_date.items():
        output_dir = VAULT_BASE / 'derived' / 'cvd' / 'okx' / symbol / '1m'
        output_file = output_dir / f'{date_str}.jsonl'
        
        # Read existing windows to deduplicate
        existing_windows = set()
        if output_file.exists():
            with open(output_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    existing_windows.add(data['window_start_utc'])
        
        # Write new windows only
        with open(output_file, 'a') as f:
            for window_start, cvd_value in sorted(date_windows.items()):
                window_str = window_start.strftime('%Y-%m-%dT%H:%M:%SZ')
                
                if window_str in existing_windows:
                    continue  # Skip duplicate
                
                record = {
                    'window_start_utc': window_str,
                    'cvd_value': str(cvd_value),
                    'symbol': symbol.replace('-', '/'),
                    'exchange': 'okx',
                    'timeframe': '1m'
                }
                
                f.write(json.dumps(record) + '\n')
                total_written += 1
    
    return total_written



def process_symbol(symbol: str):
    """
    Main processing loop for a symbol.
    1. Load state
    2. Read trade files
    3. Parse new trades
    4. Calculate CVD
    5. Write outputs
    6. Update state
    """
    logger.info(f"Processing CVD for {symbol}")
    
    # Load state
    state = load_state(symbol)
    logger.info(f"Loaded state: last_ts={state.last_timestamp_utc}, last_id={state.last_trade_id}, cvd={state.last_cvd}")
    
    # Get trade files
    trade_files = read_trade_files(symbol)
    if not trade_files:
        logger.warning(f"No trade files found for {symbol}")
        return
    
    logger.info(f"Found {len(trade_files)} trade files")
    
    # Process all files
    all_trades = []
    for filepath in trade_files:
        trades = parse_trades(filepath, state)
        all_trades.extend(trades)
    
    if not all_trades:
        logger.info(f"No new trades to process for {symbol}")
        return
    
    # Sort trades strictly by (timestamp, trade_id numeric)
    all_trades.sort(key=lambda t: (t.timestamp_utc, int(t.trade_id)))
    
    logger.info(f"Processing {len(all_trades)} new trades")
    
    # Calculate CVD updates
    start_cvd = Decimal(state.last_cvd)
    windows = calculate_cvd_updates(all_trades, start_cvd)
    
    # Write outputs (deduplicated)
    written = write_cvd_outputs(symbol, windows)
    logger.info(f"Wrote {written} new 1m CVD windows")
    
    # Update state with last trade
    last_trade = all_trades[-1]
    final_cvd = list(windows.values())[-1] if windows else start_cvd
    
    new_state = CVDState(
        last_timestamp_utc=last_trade.timestamp_utc,
        last_trade_id=last_trade.trade_id,
        last_cvd=str(final_cvd)
    )
    
    save_state(symbol, new_state)
    logger.info(f"State updated: cvd={new_state.last_cvd}")
    logger.info(f"CVD processing complete for {symbol}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Calculate CVD from JSONL trade files')
    parser.add_argument('--symbol', required=True, help='Symbol (e.g., BTC-USDT)')
    
    args = parser.parse_args()
    
    try:
        process_symbol(args.symbol)
    except Exception as e:
        logger.error(f"Error processing {args.symbol}: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
