"""
OKX WebSocket Wick Detector - FIXED VERSION
============================================

WHAT WAS WRONG:
    ❌ Used "ETH-USDT" instead of "ETH-USDT-SWAP"
    ❌ OKX spot pairs don't have reliable 1m data
    ✅ SWAP (perpetual) contracts have guaranteed 1m candles

REQUIREMENTS:
    pip install websockets sqlite3

WHAT THIS DOES:
    1. Connects to OKX WebSocket
    2. Streams 1-minute SWAP candlesticks
    3. Detects 5 consecutive wicks
    4. Saves to SQLite database

USAGE:
    python okx_wick_detector_FIXED.py

DEFAULT: BTC-USDT-SWAP (most liquid)
"""

import asyncio
import json
import websockets
import sqlite3
from datetime import datetime
from pathlib import Path


class OKXWickDetector:
    def __init__(self, symbol="BTC-USDT-SWAP"):
        """
        Initialize OKX Wick Detector
        
        IMPORTANT: Use -SWAP suffix for perpetual contracts
        Valid symbols: BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP, etc.
        """
        self.symbol = symbol
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.wick_history = []
        self.candle_count = 0
        
        # Use absolute path for database
        script_dir = Path(__file__).parent.absolute()
        self.db_path = script_dir / "wick_data.db"
        self.init_database()
    
    def init_database(self):
        """Create SQLite database and wicks table"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    upper_wick REAL NOT NULL,
                    lower_wick REAL NOT NULL,
                    body REAL NOT NULL,
                    wick_type TEXT NOT NULL,
                    sequence_position INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            print(f"✅ Database initialized: {self.db_path}")
            
        except Exception as e:
            print(f"❌ Database init failed: {e}")
            exit(1)
    
    def save_wick(self, wick_data, sequence_position=None):
        """Save wick to SQLite database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO wicks (
                    timestamp, symbol, open, high, low, close,
                    upper_wick, lower_wick, body, wick_type, sequence_position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                wick_data['timestamp'],
                self.symbol,
                wick_data['open'],
                wick_data['high'],
                wick_data['low'],
                wick_data['close'],
                wick_data['upper_wick'],
                wick_data['lower_wick'],
                wick_data['body'],
                wick_data['wick_type'],
                sequence_position
            ))
            
            conn.commit()
            conn.close()
            print(f"   💾 Saved to database (ID: {cursor.lastrowid})")
            return True
            
        except Exception as e:
            print(f"   ❌ Database save failed: {e}")
            return False
        
    def calculate_wick_stats(self, candle_data):
        """
        Extract wick information from candle
        Returns: dict with wick stats or None on error
        """
        try:
            # OKX candle format: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
            timestamp = candle_data[0]
            open_price = float(candle_data[1])
            high = float(candle_data[2])
            low = float(candle_data[3])
            close = float(candle_data[4])
            
            # Determine candle direction
            is_bullish = close > open_price
            
            # Calculate wicks
            if is_bullish:
                upper_wick = high - close
                lower_wick = open_price - low
            else:
                upper_wick = high - open_price
                lower_wick = close - low
            
            # Body size
            body = abs(close - open_price)
            
            # Prevent division by zero
            if body == 0:
                body = 0.0001
            
            # Has significant wick if either wick > 20% of body
            has_wick = (upper_wick > body * 0.2) or (lower_wick > body * 0.2)
            
            # Wick type
            wick_type = None
            if has_wick:
                if upper_wick > lower_wick:
                    wick_type = "UPPER"
                else:
                    wick_type = "LOWER"
            
            return {
                'timestamp': datetime.fromtimestamp(int(timestamp) / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'has_wick': has_wick,
                'upper_wick': round(upper_wick, 2),
                'lower_wick': round(lower_wick, 2),
                'body': round(body, 2),
                'wick_type': wick_type,
                'high': high,
                'low': low,
                'open': open_price,
                'close': close
            }
            
        except Exception as e:
            print(f"❌ Error calculating wick: {e}")
            return None
    
    def check_consecutive_wicks(self, wick_data):
        """Track and detect 5 consecutive wicks"""
        if wick_data and wick_data['has_wick']:
            self.wick_history.append(wick_data)
            
            # Save to database with sequence position
            sequence_pos = len(self.wick_history)
            self.save_wick(wick_data, sequence_pos)
            
            # Keep only last 5
            if len(self.wick_history) > 5:
                self.wick_history.pop(0)
            
            # Check if we have 5 consecutive wicks
            if len(self.wick_history) == 5:
                print("\n" + "="*60)
                print("🎯 5 CONSECUTIVE WICKS DETECTED!")
                print("="*60)
                for i, wick in enumerate(self.wick_history, 1):
                    print(f"  {i}. {wick['timestamp']} | {wick['wick_type']} | Upper: {wick['upper_wick']} | Lower: {wick['lower_wick']}")
                print("="*60 + "\n")
                
                # Reset after detection
                self.wick_history = []
        else:
            # Reset if no wick detected
            if self.wick_history:
                print(f"⚠️  Wick sequence broken. Had {len(self.wick_history)} wicks, resetting...")
            self.wick_history = []
    
    async def health_check(self):
        """Test connection before main loop"""
        print("\n⚡ HEALTH CHECK")
        print("-" * 40)
        try:
            async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                print("✅ WebSocket connection successful")
                
                # OKX doesn't use standard ping, just verify connection
                print("✅ Connection verified")
                
                return True
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return False
    
    async def connect_and_stream(self):
        """Main WebSocket loop with auto-reconnect"""
        reconnect_delay = 2
        max_reconnect_delay = 60
        
        while True:
            try:
                print(f"\n⚡ CONNECTING TO OKX")
                print(f"   Symbol: {self.symbol}")
                print(f"   Timeframe: 1 minute")
                print("-" * 40)
                
                async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                    # Subscribe to 1m candles
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [
                            {
                                "channel": "candle1m",
                                "instId": self.symbol
                            }
                        ]
                    }
                    
                    await ws.send(json.dumps(subscribe_msg))
                    print(f"✅ Subscribed to {self.symbol} 1m candles")
                    print("✅ Streaming live data...\n")
                    
                    # Reset reconnect delay on successful connection
                    reconnect_delay = 2
                    
                    # Listen for messages
                    while True:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(message)
                            
                            # Handle subscription confirmation
                            if 'event' in data:
                                if data['event'] == 'subscribe':
                                    print(f"✅ Subscription confirmed: {data.get('arg', {})}")
                                elif data['event'] == 'error':
                                    print(f"❌ Subscription error: {data}")
                                    print(f"\n💡 TIP: Make sure to use -SWAP format")
                                    print(f"   Valid: BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP")
                                    return
                                continue
                            
                            # Handle candle data
                            if 'data' in data:
                                for candle in data['data']:
                                    self.candle_count += 1
                                    wick_data = self.calculate_wick_stats(candle)
                                    
                                    if wick_data:
                                        # Print candle info
                                        status = "🔥 WICK" if wick_data['has_wick'] else "📊 No wick"
                                        print(f"{status} | {wick_data['timestamp']} | O:{wick_data['open']} H:{wick_data['high']} L:{wick_data['low']} C:{wick_data['close']}")
                                        
                                        if wick_data['has_wick']:
                                            print(f"   └─ {wick_data['wick_type']} wick | Upper: {wick_data['upper_wick']} | Lower: {wick_data['lower_wick']} | Sequence: {len(self.wick_history) + 1}/5")
                                        
                                        # Check for 5 consecutive
                                        self.check_consecutive_wicks(wick_data)
                        
                        except asyncio.TimeoutError:
                            print("⚠️  No data for 30s, checking connection...")
                            try:
                                pong = await ws.ping()
                                await asyncio.wait_for(pong, timeout=5)
                                print("✅ Connection alive")
                            except:
                                print("❌ Connection dead, reconnecting...")
                                break
                        
                        except json.JSONDecodeError as e:
                            print(f"⚠️  Invalid JSON: {e}")
                            continue
            
            except websockets.exceptions.ConnectionClosed as e:
                print(f"❌ Connection closed: {e}")
                print(f"⏳ Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                
            except Exception as e:
                print(f"❌ Error: {e}")
                print(f"⏳ Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)


async def main():
    """
    Main entry point
    
    CHANGE SYMBOL HERE:
    - BTC-USDT-SWAP (default, most liquid)
    - ETH-USDT-SWAP
    - SOL-USDT-SWAP
    - etc.
    
    IMPORTANT: Always use -SWAP suffix!
    """
    
    print("\n" + "="*60)
    print("    OKX WICK DETECTOR - FIXED VERSION")
    print("="*60)
    
    # Initialize detector (CHANGE SYMBOL HERE if needed)
    detector = OKXWickDetector("BTC-USDT-SWAP")
    
    # Run health check
    if not await detector.health_check():
        print("\n❌ Health check failed. Check internet connection.")
        return
    
    print("\n✅ Health check passed. Starting main stream...\n")
    
    # Start main loop
    try:
        await detector.connect_and_stream()
    except KeyboardInterrupt:
        print("\n\n⚠️  Stopped by user")
        print(f"📊 Total candles processed: {detector.candle_count}")
        print(f"💾 Database location: {detector.db_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
