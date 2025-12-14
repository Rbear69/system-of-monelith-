"""
OKX L2 Orderbook Exporter - PERPS Only
---------------------------------------
Maintains in-memory orderbook from OKX WebSocket "books" channel.
Writes snapshots every 2s (configurable) to hourly-rotated JSONL files.

INSTRUMENTS: BTC-USDT-SWAP, ETH-USDT-SWAP
DEPTH: Top 400 levels per side
OUTPUT: Vault\raw\okx\l2_perps\{INSTID}\{DATE}\{HOUR}.jsonl
"""

import asyncio
import json
import logging
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict
import websockets
import zlib

# Configuration
INSTRUMENTS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
VAULT_BASE = Path(r"C:\Users\M.R Bear\Documents\RaveQuant\Rave_Quant_Vault")
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
REST_BASE = "https://www.okx.com"

# Settings
SNAPSHOT_CADENCE_SEC = 2  # Configurable: 1s/2s/5s
DEPTH_LEVELS = 400  # Top N levels per side
UNCOMPRESSED_HOURS = 6  # Keep last 6 hours uncompressed
RETENTION_DAYS = 5  # Delete compressed files older than this

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('l2_exporter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('L2_Exporter')


class OrderBook:
    """In-memory orderbook with incremental update support."""
    
    def __init__(self, inst_id: str):
        self.inst_id = inst_id
        self.bids: OrderedDict[str, List[str]] = OrderedDict()  # price -> [price, qty, "0", order_count]
        self.asks: OrderedDict[str, List[str]] = OrderedDict()
        self.last_seq_id: Optional[int] = None
        self.checksum: Optional[int] = None
        self.last_update_ts: Optional[str] = None
        self.is_snapshot_loaded = False
    
    def clear(self):
        """Clear orderbook (used on gap detection)."""
        self.bids.clear()
        self.asks.clear()
        self.last_seq_id = None
        self.is_snapshot_loaded = False
        logger.warning(f"[{self.inst_id}] Orderbook cleared")
    
    def process_snapshot(self, data: Dict) -> bool:
        """Process snapshot message. Returns True if successful."""
        try:
            self.bids.clear()
            self.asks.clear()
            
            # Load bids
            for level in data.get('bids', []):
                if len(level) < 4:
                    logger.error(f"[{self.inst_id}] Invalid bid level: {level}")
                    return False
                price = level[0]
                self.bids[price] = level
            
            # Load asks
            for level in data.get('asks', []):
                if len(level) < 4:
                    logger.error(f"[{self.inst_id}] Invalid ask level: {level}")
                    return False
                price = level[0]
                self.asks[price] = level
            
            self.last_seq_id = data.get('seqId')
            self.checksum = data.get('checksum')
            self.last_update_ts = data.get('ts')
            self.is_snapshot_loaded = True
            
            logger.info(f"[{self.inst_id}] Snapshot loaded: {len(self.bids)} bids, {len(self.asks)} asks")
            return True
            
        except Exception as e:
            logger.error(f"[{self.inst_id}] Snapshot processing failed: {e}")
            return False
    
    def process_update(self, data: Dict) -> bool:
        """Process incremental update. Returns True if successful."""
        try:
            # Update bids
            for level in data.get('bids', []):
                if len(level) < 4:
                    continue
                price, qty = level[0], level[1]
                
                if float(qty) == 0:
                    # Remove level
                    self.bids.pop(price, None)
                else:
                    # Update level
                    self.bids[price] = level
            
            # Update asks
            for level in data.get('asks', []):
                if len(level) < 4:
                    continue
                price, qty = level[0], level[1]
                
                if float(qty) == 0:
                    # Remove level
                    self.asks.pop(price, None)
                else:
                    # Update level
                    self.asks[price] = level
            
            self.last_seq_id = data.get('seqId')
            self.checksum = data.get('checksum')
            self.last_update_ts = data.get('ts')
            
            return True
            
        except Exception as e:
            logger.error(f"[{self.inst_id}] Update processing failed: {e}")
            return False
    
    def get_sorted_book(self) -> Tuple[List[List[str]], List[List[str]]]:
        """Get sorted bids (desc) and asks (asc), truncated to DEPTH_LEVELS."""
        # Sort bids descending by price
        sorted_bids = sorted(
            self.bids.items(),
            key=lambda x: float(x[0]),
            reverse=True
        )[:DEPTH_LEVELS]
        
        # Sort asks ascending by price
        sorted_asks = sorted(
            self.asks.items(),
            key=lambda x: float(x[0]),
            reverse=False
        )[:DEPTH_LEVELS]
        
        # Extract level data
        bids_top = [level for _, level in sorted_bids]
        asks_top = [level for _, level in sorted_asks]
        
        return bids_top, asks_top
    
    def validate_checksum(self) -> bool:
        """Validate checksum if provided (OKX CRC32 algorithm)."""
        if self.checksum is None:
            return True  # No checksum to validate
        
        try:
            # Get top 25 levels for checksum (OKX spec)
            bids_top, asks_top = self.get_sorted_book()
            
            # Build checksum string
            checksum_str = ""
            for i in range(min(25, len(bids_top), len(asks_top))):
                if i < len(bids_top):
                    bid = bids_top[i]
                    checksum_str += f"{bid[0]}:{bid[1]}:"
                if i < len(asks_top):
                    ask = asks_top[i]
                    checksum_str += f"{ask[0]}:{ask[1]}:"
            
            # Remove trailing colon
            if checksum_str.endswith(':'):
                checksum_str = checksum_str[:-1]
            
            # Calculate CRC32
            calculated = zlib.crc32(checksum_str.encode()) & 0xffffffff
            calculated_signed = calculated - 2**32 if calculated > 2**31 else calculated
            
            if calculated_signed != self.checksum:
                logger.warning(
                    f"[{self.inst_id}] Checksum mismatch: "
                    f"expected={self.checksum}, calculated={calculated_signed}"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"[{self.inst_id}] Checksum validation failed: {e}")
            return False



class SnapshotWriter:
    """Writes L2 snapshots to hourly-rotated JSONL files."""
    
    def __init__(self):
        self.written_snapshots: Dict[str, set] = {}  # inst_id -> set of timestamps written
        self.current_hour: Dict[str, str] = {}  # inst_id -> current hour string
    
    def get_output_path(self, inst_id: str, timestamp_utc: datetime) -> Path:
        """Get output file path for snapshot."""
        date_str = timestamp_utc.strftime('%Y-%m-%d')
        hour_str = timestamp_utc.strftime('%H')
        
        output_dir = VAULT_BASE / 'raw' / 'okx' / 'l2_perps' / inst_id / date_str
        output_dir.mkdir(parents=True, exist_ok=True)
        
        return output_dir / f"{hour_str}.jsonl"
    
    def write_snapshot(self, orderbook: OrderBook, prev_seq_id: Optional[int] = None, 
                      gap_detected: bool = False) -> bool:
        """
        Write orderbook snapshot to JSONL file.
        Returns True if written, False if deduplicated.
        """
        if not orderbook.is_snapshot_loaded:
            logger.warning(f"[{orderbook.inst_id}] Cannot write: no snapshot loaded")
            return False
        
        # Parse timestamp
        if not orderbook.last_update_ts:
            logger.error(f"[{orderbook.inst_id}] Missing timestamp")
            return False
        
        try:
            ts_ms = int(orderbook.last_update_ts)
            timestamp_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            timestamp_str = timestamp_utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
        except Exception as e:
            logger.error(f"[{orderbook.inst_id}] Timestamp parse failed: {e}")
            return False
        
        # Deduplication check
        inst_id = orderbook.inst_id
        if inst_id not in self.written_snapshots:
            self.written_snapshots[inst_id] = set()
        
        if timestamp_str in self.written_snapshots[inst_id]:
            return False  # Already written
        
        # Get sorted book
        bids_top, asks_top = orderbook.get_sorted_book()
        
        # Calculate best bid, best ask, mid price
        best_bid = bids_top[0][0] if bids_top else None
        best_ask = asks_top[0][0] if asks_top else None
        
        mid_price = None
        if best_bid and best_ask:
            mid_price = str((float(best_bid) + float(best_ask)) / 2)
        
        # Build snapshot record
        snapshot = {
            'timestamp_utc': timestamp_str,
            'exchange': 'okx',
            'market': 'perp',
            'channel': 'books',
            'instId': inst_id,
            'bids_top400': bids_top,
            'asks_top400': asks_top,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'mid_price': mid_price,
            'checksum': orderbook.checksum,
            'seqId': orderbook.last_seq_id,
            'prevSeqId': prev_seq_id,
            'gap_detected': gap_detected
        }
        
        # Get output path
        output_path = self.get_output_path(inst_id, timestamp_utc)
        
        # Write JSONL (append-only)
        with open(output_path, 'a') as f:
            f.write(json.dumps(snapshot) + '\n')
        
        # Track written snapshot
        self.written_snapshots[inst_id].add(timestamp_str)
        
        # Limit memory (keep last 1000 per inst)
        if len(self.written_snapshots[inst_id]) > 1000:
            old_timestamps = sorted(self.written_snapshots[inst_id])[:500]
            for ts in old_timestamps:
                self.written_snapshots[inst_id].discard(ts)
        
        logger.debug(
            f"[{inst_id}] Snapshot written: "
            f"bids={len(bids_top)}, asks={len(asks_top)}, gap={gap_detected}"
        )
        
        return True



def fetch_instrument_metadata(inst_id: str):
    """Fetch and save instrument metadata from OKX REST API."""
    try:
        url = f"{REST_BASE}/api/v5/public/instruments"
        params = {
            'instType': 'SWAP',
            'instId': inst_id
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('code') != '0':
            logger.error(f"[{inst_id}] API error: {data}")
            return False
        
        instruments = data.get('data', [])
        if not instruments:
            logger.error(f"[{inst_id}] No instrument data returned")
            return False
        
        # Save metadata
        meta_dir = VAULT_BASE / 'meta' / 'okx' / 'instruments'
        meta_dir.mkdir(parents=True, exist_ok=True)
        
        meta_file = meta_dir / f"{inst_id}.json"
        with open(meta_file, 'w') as f:
            json.dump(instruments[0], f, indent=2)
        
        logger.info(f"[{inst_id}] Metadata saved: {meta_file}")
        return True
        
    except Exception as e:
        logger.error(f"[{inst_id}] Metadata fetch failed: {e}")
        return False


class L2Exporter:
    """Main L2 orderbook exporter."""
    
    def __init__(self):
        self.orderbooks: Dict[str, OrderBook] = {}
        self.writer = SnapshotWriter()
        self.ws = None
        self.running = False
        self.last_snapshot_time: Dict[str, float] = {}
        
        # Initialize orderbooks
        for inst_id in INSTRUMENTS:
            self.orderbooks[inst_id] = OrderBook(inst_id)
            self.last_snapshot_time[inst_id] = 0
    
    async def subscribe(self):
        """Subscribe to orderbook channels."""
        subscriptions = []
        for inst_id in INSTRUMENTS:
            subscriptions.append({
                "channel": "books",
                "instId": inst_id
            })
        
        subscribe_msg = {
            "op": "subscribe",
            "args": subscriptions
        }
        
        await self.ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to {len(INSTRUMENTS)} instruments")
    
    def validate_message(self, data: Dict) -> bool:
        """Validate required fields are present."""
        if 'arg' not in data or 'data' not in data:
            return True  # Event message or non-data message
        
        arg = data.get('arg', {})
        message_data = data.get('data', [])
        
        if not message_data:
            return True
        
        first_item = message_data[0]
        
        # REQUIRED fields
        required = ['ts', 'bids', 'asks']
        missing = [f for f in required if f not in first_item]
        
        if missing:
            logger.error(f"BUILD_FAIL: Missing required fields: {missing}")
            logger.error(f"Full message: {json.dumps(data, indent=2)}")
            return False
        
        # Validate bids/asks are list-of-lists
        if not isinstance(first_item['bids'], list) or not isinstance(first_item['asks'], list):
            logger.error(f"BUILD_FAIL: bids/asks must be list-of-lists")
            return False
        
        return True
    
    async def process_message(self, data: Dict):
        """Process WebSocket message."""
        try:
            # Handle event messages
            if 'event' in data:
                logger.info(f"Event: {data}")
                return
            
            # Validate message structure
            if not self.validate_message(data):
                logger.error("Stopping due to schema validation failure")
                self.running = False
                return
            
            if 'arg' not in data or 'data' not in data:
                return
            
            arg = data.get('arg', {})
            inst_id = arg.get('instId')
            
            if inst_id not in self.orderbooks:
                return
            
            orderbook = self.orderbooks[inst_id]
            message_data = data.get('data', [])
            
            for item in message_data:
                action = item.get('action', 'snapshot')
                
                # Get sequence IDs for gap detection
                current_seq_id = item.get('seqId')
                prev_seq_id = item.get('prevSeqId')
                
                # Gap detection
                gap_detected = False
                if prev_seq_id is not None and orderbook.last_seq_id is not None:
                    if prev_seq_id != orderbook.last_seq_id:
                        gap_detected = True
                        logger.warning(
                            f"[{inst_id}] GAP DETECTED: "
                            f"expected prevSeqId={orderbook.last_seq_id}, got={prev_seq_id}"
                        )
                        
                        # Write snapshot with gap_detected=true
                        self.writer.write_snapshot(orderbook, prev_seq_id, gap_detected=True)
                        
                        # Clear orderbook and force resubscribe
                        orderbook.clear()
                        await self.resubscribe(inst_id)
                        continue
                
                # Process based on action
                if action == 'snapshot':
                    success = orderbook.process_snapshot(item)
                    if success:
                        # Validate checksum
                        orderbook.validate_checksum()
                else:
                    # Incremental update
                    success = orderbook.process_update(item)
                    if success:
                        # Validate checksum
                        orderbook.validate_checksum()
        
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
    
    async def resubscribe(self, inst_id: str):
        """Force resubscribe for an instrument after gap detection."""
        try:
            # Unsubscribe
            unsub_msg = {
                "op": "unsubscribe",
                "args": [{"channel": "books", "instId": inst_id}]
            }
            await self.ws.send(json.dumps(unsub_msg))
            
            # Wait briefly
            await asyncio.sleep(0.5)
            
            # Resubscribe
            sub_msg = {
                "op": "subscribe",
                "args": [{"channel": "books", "instId": inst_id}]
            }
            await self.ws.send(json.dumps(sub_msg))
            
            logger.info(f"[{inst_id}] Forced resubscribe completed")
            
        except Exception as e:
            logger.error(f"[{inst_id}] Resubscribe failed: {e}")
    
    async def snapshot_loop(self):
        """Periodically write snapshots (every SNAPSHOT_CADENCE_SEC seconds)."""
        while self.running:
            await asyncio.sleep(SNAPSHOT_CADENCE_SEC)
            
            current_time = time.time()
            
            for inst_id, orderbook in self.orderbooks.items():
                # Check if it's time to snapshot
                last_snapshot = self.last_snapshot_time.get(inst_id, 0)
                
                if current_time - last_snapshot >= SNAPSHOT_CADENCE_SEC:
                    if orderbook.is_snapshot_loaded:
                        self.writer.write_snapshot(orderbook)
                        self.last_snapshot_time[inst_id] = current_time
    
    async def message_listener(self):
        """Listen to WebSocket messages."""
        try:
            async for message in self.ws:
                if message == "pong":
                    continue
                
                try:
                    data = json.loads(message)
                    await self.process_message(data)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode message: {message}")
        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in message listener: {e}", exc_info=True)
    
    async def run(self):
        """Main run loop with auto-reconnect."""
        self.running = True
        
        logger.info("L2 Exporter starting...")
        logger.info(f"Instruments: {INSTRUMENTS}")
        logger.info(f"Snapshot cadence: {SNAPSHOT_CADENCE_SEC}s")
        logger.info(f"Depth: {DEPTH_LEVELS} levels")
        
        # Fetch instrument metadata
        for inst_id in INSTRUMENTS:
            fetch_instrument_metadata(inst_id)
        
        while self.running:
            try:
                logger.info(f"Connecting to {WS_URL}")
                async with websockets.connect(WS_URL) as ws:
                    self.ws = ws
                    logger.info("Connected successfully")
                    
                    # Subscribe to channels
                    await self.subscribe()
                    
                    # Start snapshot loop
                    snapshot_task = asyncio.create_task(self.snapshot_loop())
                    
                    # Listen for messages
                    await self.message_listener()
                    
                    # Cancel snapshot task
                    snapshot_task.cancel()
            
            except Exception as e:
                logger.error(f"Connection error: {e}", exc_info=True)
            
            if self.running:
                logger.warning("Reconnecting in 5s...")
                await asyncio.sleep(5)
        
        logger.info("L2 Exporter stopped")
    
    def stop(self):
        """Stop the exporter."""
        logger.info("Stopping L2 Exporter...")
        self.running = False



async def main():
    """Main entry point."""
    exporter = L2Exporter()
    
    try:
        await exporter.run()
    except KeyboardInterrupt:
        logger.info("\nShutdown requested...")
        exporter.stop()


if __name__ == '__main__':
    asyncio.run(main())
