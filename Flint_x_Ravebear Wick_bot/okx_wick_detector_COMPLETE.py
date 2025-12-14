"""
OKX WebSocket Multi-Timeframe Wick Detector - PRODUCTION READY
===============================================================

RAVEBEAR'S EDGE: TIP-TO-TIP UNTOUCHED WICKS
--------------------------------------------
This bot tracks untouched wicks with ZERO air gap between tip-to-tip touches.
NOT just any wick - specifically wicks that haven't been touched yet.

MULTI-TIMEFRAME SUPPORT:
- 1m, 5m, 15m, 1h, 4h, 1d
- Separate tracking per timeframe
- Database stores all timeframes with proper indexing

WHAT THIS TRACKS:
1. Untouched upper wicks (resistance not retested)
2. Untouched lower wicks (support not retested)
3. Tip-to-tip validation (exact price level touch = invalidated)
4. Wick age tracking (how long since formation)

REQUIREMENTS:
    pip install websockets aiosqlite

USAGE:
    python okx_wick_detector_COMPLETE.py

Press Ctrl+C to stop gracefully.
"""

import asyncio
import json
import websockets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import sys
import io

# Fix Windows console UTF-8 encoding for emojis
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class MultiTimeframeWickDetector:
    def __init__(self, symbol="BTC-USDT-SWAP"):
        """
        Initialize multi-timeframe wick detector
        
        Args:
            symbol: OKX symbol (must use -SWAP suffix for perps)
        """
        self.symbol = symbol
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        
        # Multi-timeframe configuration
        self.timeframes = {
            '1m': 'candle1m',
            '5m': 'candle5m',
            '15m': 'candle15m',
            '1H': 'candle1H',
            '4H': 'candle4H',
            '1D': 'candle1D'
        }
        
        # Track untouched wicks per timeframe
        self.untouched_wicks = {tf: [] for tf in self.timeframes.keys()}
        
        # Statistics
        self.stats = {tf: {'candles': 0, 'wicks_detected': 0, 'wicks_touched': 0} 
                     for tf in self.timeframes.keys()}
        
        # Database setup
        script_dir = Path(__file__).parent.absolute()
        self.db_path = script_dir / "wick_data_multitf.db"
        self.init_database()
        
        print(f"✅ Multi-TF Wick Detector initialized")
        print(f"   Symbol: {symbol}")
        print(f"   Timeframes: {list(self.timeframes.keys())}")
        print(f"   Database: {self.db_path}")
    
    def init_database(self):
        """
        Create database schema for multi-timeframe wick tracking
        
        Schema tracks:
        - All candles with wick calculations
        - Untouched wick registry with status tracking
        - Touch events when wicks get invalidated
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Main candles table with timeframe support
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timeframe TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    upper_wick REAL NOT NULL,
                    lower_wick REAL NOT NULL,
                    body REAL NOT NULL,
                    has_upper_wick BOOLEAN,
                    has_lower_wick BOOLEAN,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(timeframe, timestamp)
                )
            ''')
            
            # Untouched wicks registry
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS untouched_wicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timeframe TEXT NOT NULL,
                    wick_type TEXT NOT NULL,
                    formation_time TEXT NOT NULL,
                    wick_price REAL NOT NULL,
                    candle_high REAL NOT NULL,
                    candle_low REAL NOT NULL,
                    candle_close REAL NOT NULL,
                    wick_size REAL NOT NULL,
                    status TEXT DEFAULT 'ACTIVE',
                    touched_time TEXT,
                    touched_price REAL,
                    age_hours REAL,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes separately (SQLite doesn't support inline INDEX in CREATE TABLE)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_tf_status 
                ON untouched_wicks(timeframe, status)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_wick_price 
                ON untouched_wicks(wick_price)
            ''')
            
            # Touch events table (when wicks get invalidated)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wick_touches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wick_id INTEGER NOT NULL,
                    touch_time TEXT NOT NULL,
                    touch_price REAL NOT NULL,
                    price_distance REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(wick_id) REFERENCES untouched_wicks(id)
                )
            ''')
            
            # Statistics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timeframe TEXT NOT NULL,
                    date TEXT NOT NULL,
                    candles_processed INTEGER DEFAULT 0,
                    wicks_formed INTEGER DEFAULT 0,
                    wicks_touched INTEGER DEFAULT 0,
                    active_wicks INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(timeframe, date)
                )
            ''')
            
            conn.commit()
            conn.close()
            print(f"✅ Database initialized: {self.db_path}")
            
        except Exception as e:
            print(f"❌ Database init failed: {e}")
            exit(1)
    
    def save_candle(self, timeframe: str, candle_data: Dict):
        """Save candle with wick calculations to database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO candles (
                    timeframe, timestamp, open, high, low, close, volume,
                    upper_wick, lower_wick, body, has_upper_wick, has_lower_wick
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                timeframe,
                candle_data['timestamp'],
                candle_data['open'],
                candle_data['high'],
                candle_data['low'],
                candle_data['close'],
                candle_data.get('volume', 0),
                candle_data['upper_wick'],
                candle_data['lower_wick'],
                candle_data['body'],
                candle_data['has_upper_wick'],
                candle_data['has_lower_wick']
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"❌ Save candle error: {e}")
            return False
    
    def save_untouched_wick(self, timeframe: str, wick_data: Dict) -> int:
        """
        Save new untouched wick to registry
        Returns: wick_id for tracking
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO untouched_wicks (
                    timeframe, wick_type, formation_time, wick_price,
                    candle_high, candle_low, candle_close, wick_size, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
            ''', (
                timeframe,
                wick_data['wick_type'],
                wick_data['timestamp'],
                wick_data['wick_price'],
                wick_data['high'],
                wick_data['low'],
                wick_data['close'],
                wick_data['wick_size']
            ))
            
            wick_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            print(f"   💾 [{timeframe}] Saved {wick_data['wick_type']} wick @ ${wick_data['wick_price']:,.2f}")
            return wick_id
            
        except Exception as e:
            print(f"❌ Save wick error: {e}")
            return -1
    
    def mark_wick_touched(self, wick_id: int, touch_time: str, touch_price: float):
        """Mark a wick as touched (invalidated)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Update wick status
            cursor.execute('''
                UPDATE untouched_wicks 
                SET status = 'TOUCHED',
                    touched_time = ?,
                    touched_price = ?
                WHERE id = ?
            ''', (touch_time, touch_price, wick_id))
            
            # Record touch event
            cursor.execute('''
                INSERT INTO wick_touches (wick_id, touch_time, touch_price)
                VALUES (?, ?, ?)
            ''', (wick_id, touch_time, touch_price))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"❌ Mark touched error: {e}")
            return False
    
    def calculate_wick_stats(self, candle_data: List) -> Dict:
        """
        Calculate wick statistics from OKX candle data
        
        Args:
            candle_data: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        
        Returns:
            Dict with wick calculations and validation flags
        """
        try:
            timestamp = candle_data[0]
            open_price = float(candle_data[1])
            high = float(candle_data[2])
            low = float(candle_data[3])
            close = float(candle_data[4])
            volume = float(candle_data[5]) if len(candle_data) > 5 else 0
            
            # Determine candle direction
            is_bullish = close > open_price
            
            # Calculate wicks based on candle direction
            if is_bullish:
                upper_wick = high - close
                lower_wick = open_price - low
            else:
                upper_wick = high - open_price
                lower_wick = close - low
            
            # Body size
            body = abs(close - open_price)
            if body == 0:
                body = 0.0001  # Prevent division by zero
            
            # Significant wick threshold: >20% of body
            has_upper_wick = upper_wick > body * 0.2
            has_lower_wick = lower_wick > body * 0.2
            
            return {
                'timestamp': datetime.fromtimestamp(int(timestamp) / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'upper_wick': round(upper_wick, 2),
                'lower_wick': round(lower_wick, 2),
                'body': round(body, 2),
                'has_upper_wick': has_upper_wick,
                'has_lower_wick': has_lower_wick,
                'is_bullish': is_bullish
            }
            
        except Exception as e:
            print(f"❌ Wick calculation error: {e}")
            return None
    
    def check_tip_to_tip_touch(self, timeframe: str, current_high: float, current_low: float):
        """
        Check if current candle touches any untouched wick tips
        
        A wick is considered TOUCHED when price reaches the exact wick tip price
        with ZERO air gap tolerance.
        
        Args:
            timeframe: Which timeframe to check
            current_high: Current candle high
            current_low: Current candle low
        """
        active_wicks = self.untouched_wicks[timeframe]
        touched = []
        
        for wick in active_wicks:
            wick_price = wick['wick_price']
            
            # Tip-to-tip validation: exact price touch
            if wick['wick_type'] == 'UPPER':
                # Upper wick touched if price reaches the high
                if current_high >= wick_price:
                    touched.append(wick)
                    print(f"   🎯 [{timeframe}] UPPER wick TOUCHED @ ${wick_price:,.2f}")
            
            elif wick['wick_type'] == 'LOWER':
                # Lower wick touched if price reaches the low
                if current_low <= wick_price:
                    touched.append(wick)
                    print(f"   🎯 [{timeframe}] LOWER wick TOUCHED @ ${wick_price:,.2f}")
        
        # Remove touched wicks and mark in database
        for wick in touched:
            self.untouched_wicks[timeframe].remove(wick)
            self.mark_wick_touched(
                wick['id'],
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                wick_price
            )
            self.stats[timeframe]['wicks_touched'] += 1
    
    def process_candle(self, timeframe: str, candle_data: List):
        """
        Process incoming candle:
        1. Calculate wick stats
        2. Check if it touches existing untouched wicks
        3. If it forms new wick, add to untouched registry
        4. Save everything to database
        """
        stats = self.calculate_wick_stats(candle_data)
        
        if not stats:
            return
        
        # Update stats
        self.stats[timeframe]['candles'] += 1
        
        # Check for tip-to-tip touches FIRST
        self.check_tip_to_tip_touch(timeframe, stats['high'], stats['low'])
        
        # Save candle to database
        self.save_candle(timeframe, stats)
        
        # Track new untouched wicks
        if stats['has_upper_wick']:
            wick_data = {
                'wick_type': 'UPPER',
                'timestamp': stats['timestamp'],
                'wick_price': stats['high'],  # Upper wick tip = candle high
                'high': stats['high'],
                'low': stats['low'],
                'close': stats['close'],
                'wick_size': stats['upper_wick']
            }
            
            wick_id = self.save_untouched_wick(timeframe, wick_data)
            if wick_id > 0:
                wick_data['id'] = wick_id
                self.untouched_wicks[timeframe].append(wick_data)
                self.stats[timeframe]['wicks_detected'] += 1
        
        if stats['has_lower_wick']:
            wick_data = {
                'wick_type': 'LOWER',
                'timestamp': stats['timestamp'],
                'wick_price': stats['low'],  # Lower wick tip = candle low
                'high': stats['high'],
                'low': stats['low'],
                'close': stats['close'],
                'wick_size': stats['lower_wick']
            }
            
            wick_id = self.save_untouched_wick(timeframe, wick_data)
            if wick_id > 0:
                wick_data['id'] = wick_id
                self.untouched_wicks[timeframe].append(wick_data)
                self.stats[timeframe]['wicks_detected'] += 1
        
        # Print status
        wick_status = []
        if stats['has_upper_wick']:
            wick_status.append(f"⬆️ UPPER: ${stats['upper_wick']:.2f}")
        if stats['has_lower_wick']:
            wick_status.append(f"⬇️ LOWER: ${stats['lower_wick']:.2f}")
        
        wick_display = " | ".join(wick_status) if wick_status else "No significant wicks"
        active_count = len(self.untouched_wicks[timeframe])
        
        print(f"[{timeframe}] {stats['timestamp']} | ${stats['close']:,.2f} | {wick_display} | Active: {active_count}")
    
    async def connect_and_stream(self):
        """
        Main WebSocket connection with multi-timeframe subscriptions
        Handles auto-reconnect and error recovery
        """
        reconnect_delay = 2
        max_reconnect_delay = 60
        
        while True:
            try:
                print(f"\n⚡ CONNECTING TO OKX")
                print(f"   Symbol: {self.symbol}")
                print(f"   Timeframes: {list(self.timeframes.keys())}")
                print("-" * 60)
                
                async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                    # Subscribe to all timeframes
                    subscribe_args = [
                        {"channel": channel, "instId": self.symbol}
                        for channel in self.timeframes.values()
                    ]
                    
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": subscribe_args
                    }
                    
                    await ws.send(json.dumps(subscribe_msg))
                    print(f"✅ Subscribed to {len(self.timeframes)} timeframes")
                    print("✅ Streaming live data...\n")
                    
                    # Reset reconnect delay
                    reconnect_delay = 2
                    
                    # Listen for messages
                    while True:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(message)
                            
                            # Handle subscription confirmation
                            if 'event' in data:
                                if data['event'] == 'subscribe':
                                    print(f"✅ Subscription confirmed: {data.get('arg', {}).get('channel')}")
                                elif data['event'] == 'error':
                                    print(f"❌ Subscription error: {data}")
                                continue
                            
                            # Handle candle data
                            if 'data' in data and 'arg' in data:
                                channel = data['arg']['channel']
                                
                                # Map channel to timeframe
                                timeframe = None
                                for tf, ch in self.timeframes.items():
                                    if ch == channel:
                                        timeframe = tf
                                        break
                                
                                if timeframe:
                                    for candle in data['data']:
                                        self.process_candle(timeframe, candle)
                        
                        except asyncio.TimeoutError:
                            print("⚠️  No data for 30s, checking connection...")
                            try:
                                pong = await ws.ping()
                                await asyncio.wait_for(pong, timeout=5)
                                print("✅ Connection alive")
                            except:
                                print("❌ Connection dead, reconnecting...")
                                break
                        
                        except json.JSONDecodeError:
                            continue
            
            except Exception as e:
                print(f"❌ Connection error: {e}")
                print(f"⏳ Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
    
    def print_summary(self):
        """Print current statistics"""
        print("\n" + "="*80)
        print("WICK DETECTOR STATISTICS")
        print("="*80)
        for tf in self.timeframes.keys():
            active = len(self.untouched_wicks[tf])
            print(f"\n[{tf}]")
            print(f"  Candles processed: {self.stats[tf]['candles']}")
            print(f"  Wicks detected: {self.stats[tf]['wicks_detected']}")
            print(f"  Wicks touched: {self.stats[tf]['wicks_touched']}")
            print(f"  Active untouched: {active}")
        print("="*80 + "\n")


async def main():
    """
    Main entry point
    
    Tracks untouched wicks across multiple timeframes:
    - 1m, 5m, 15m, 1h, 4h, 1d
    
    Each wick is tracked until price touches it tip-to-tip (ZERO air gap).
    Database stores full history for analysis and validator queries.
    
    Press Ctrl+C to stop and see statistics.
    """
    
    print("\n" + "="*80)
    print("  RAVEBEAR MULTI-TIMEFRAME WICK DETECTOR - PRODUCTION")
    print("="*80)
    print("\n🎯 Tracking TIP-TO-TIP untouched wicks")
    print("   Edge: Wicks that haven't been retouched yet")
    print("   Validation: ZERO air gap tolerance\n")
    
    # Initialize detector
    detector = MultiTimeframeWickDetector("BTC-USDT-SWAP")
    
    # Start streaming
    try:
        await detector.connect_and_stream()
    except KeyboardInterrupt:
        print("\n\n⚠️  Stopped by user")
        detector.print_summary()
        print(f"💾 Database: {detector.db_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Shutdown complete")
