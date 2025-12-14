"""
Quick Test - Inserts sample wick data
======================================

USAGE:
    python quick_test.py

Inserts 5 sample wicks into database so you can test validator
without waiting for real data.
"""

import sqlite3
from datetime import datetime, timedelta


def insert_test_data():
    """Insert 5 sample wicks for testing"""
    
    print("\n⚡ QUICK TEST - Inserting Sample Data")
    print("-" * 40)
    
    db_path = "wick_data.db"
    
    # Create database if doesn't exist
    conn = sqlite3.connect(db_path)
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
    
    print("✅ Database ready")
    
    # Sample wick data
    base_time = datetime.now()
    
    test_wicks = [
        # (timestamp, symbol, O, H, L, C, upper_wick, lower_wick, body, wick_type, seq)
        (
            (base_time - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S'),
            'ETH-USDT', 2850.0, 2890.0, 2820.0, 2870.0, 20.0, 30.0, 20.0, 'LOWER', 1
        ),
        (
            (base_time - timedelta(minutes=4)).strftime('%Y-%m-%d %H:%M:%S'),
            'ETH-USDT', 2870.0, 2895.0, 2850.0, 2875.0, 20.0, 20.0, 5.0, 'UPPER', 2
        ),
        (
            (base_time - timedelta(minutes=3)).strftime('%Y-%m-%d %H:%M:%S'),
            'ETH-USDT', 2875.0, 2900.0, 2840.0, 2880.0, 20.0, 35.0, 5.0, 'LOWER', 3
        ),
        (
            (base_time - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S'),
            'ETH-USDT', 2880.0, 2910.0, 2860.0, 2890.0, 20.0, 20.0, 10.0, 'UPPER', 4
        ),
        (
            (base_time - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S'),
            'ETH-USDT', 2890.0, 2920.0, 2865.0, 2900.0, 20.0, 25.0, 10.0, 'LOWER', 5
        ),
    ]
    
    print("📝 Inserting 5 sample wicks...")
    
    for wick in test_wicks:
        cursor.execute('''
            INSERT INTO wicks (
                timestamp, symbol, open, high, low, close,
                upper_wick, lower_wick, body, wick_type, sequence_position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', wick)
    
    conn.commit()
    
    # Verify
    cursor.execute("SELECT COUNT(*) FROM wicks")
    total = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"✅ Inserted 5 sample wicks")
    print(f"📊 Total wicks in database: {total}")
    print("\n⚡ Now run: python validator.py")
    print("-" * 40 + "\n")


if __name__ == "__main__":
    insert_test_data()
