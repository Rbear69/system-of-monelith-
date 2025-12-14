OKX WICK DETECTOR - SETUP (with SQLite Storage)
================================================

⚡ INSTALL (run once)
-----------------------
pip install -r requirements.txt

NOTE: SQLite is built into Python, no extra install needed


⚡ RUN
-----------------------
python okx_wick_detector.py

(Default: ETH-USDT - better for altseason movement)


⚡ VALIDATE DATABASE
-----------------------
python validator.py

Checks:
- Database file exists
- Table structure correct
- Data stored properly
- Shows last 10 wicks
- Data quality stats


WHAT IT DOES
-----------------------
1. Health check → pings OKX server
2. Connects → OKX websocket  
3. Subscribes → ETH-USDT 1m candles (altseason optimized)
4. Detects → 5 consecutive wicks
5. Saves → SQLite database (wick_data.db)
6. Logs → real-time output


DATABASE SCHEMA
-----------------------
Table: wicks
- id (auto-increment)
- timestamp (candle time)
- symbol (ETH-USDT, etc)
- open, high, low, close
- upper_wick, lower_wick, body
- wick_type (UPPER/LOWER)
- sequence_position (1-5 if part of sequence)
- created_at (insert time)


CHANGE SYMBOL
-----------------------
Edit line 172 in okx_wick_detector.py:

    detector = OKXWickDetector("BTC-USDT")

Or: "SOL-USDT", "AVAX-USDT", "MATIC-USDT", etc.


WICK DEFINITION
-----------------------
Wick detected when:
    upper_wick OR lower_wick > 20% of candle body


OUTPUT EXAMPLE
-----------------------
✅ Database initialized: wick_data.db

🔥 WICK | 2025-10-25 12:34:56 | O:2850 H:2890 L:2820 C:2870
   └─ UPPER wick | Upper: 20 | Lower: 30 | Sequence: 1/5
   💾 Saved to database (ID: 1)

📊 No wick | 2025-10-25 12:35:56 | O:2870 H:2880 L:2860 C:2875

🔥 WICK | 2025-10-25 12:36:56 | O:2875 H:2895 L:2850 C:2880
   └─ LOWER wick | Upper: 15 | Lower: 25 | Sequence: 2/5
   💾 Saved to database (ID: 2)

🎯 5 CONSECUTIVE WICKS DETECTED!
==============================================================
  1. 2025-10-25 12:30:56 | LOWER | Upper: 10 | Lower: 35
  2. 2025-10-25 12:31:56 | UPPER | Upper: 25 | Lower: 12
  ...
==============================================================


REQUIREMENTS
-----------------------
Python 3.7+
websockets library


FIRST RUN VERSION
-----------------------
Basic functionality only:
- No advanced filtering
- Console output + SQLite storage
- Validator for data integrity


TESTING WORKFLOW
-----------------------
1. Run bot: python okx_wick_detector.py
2. Let it run for 5-10 minutes (collect wicks)
3. Stop bot: Ctrl+C
4. Validate: python validator.py
5. Check output for:
   ✅ Database exists
   ✅ Table structure correct
   ✅ Wicks stored properly
   ✅ Last 10 wicks displayed
   ✅ Data quality stats shown
