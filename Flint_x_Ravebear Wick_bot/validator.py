"""
SQLite Validator - Checks wick_data.db integrity
================================================

USAGE:
    python validator.py

WHAT IT CHECKS:
    1. Database file exists
    2. Table structure correct
    3. Data stored properly
    4. Shows last 10 wicks
"""

import sqlite3
import os
from datetime import datetime


def validate_database():
    """Run all validation checks"""
    
    print("\n" + "="*60)
    print("    SQLITE VALIDATOR")
    print("="*60 + "\n")
    
    db_path = "wick_data.db"
    
    # Check 1: File exists
    print("⚡ CHECK 1: Database File")
    print("-" * 40)
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        print("   Run okx_wick_detector.py first to create it.\n")
        return False
    
    file_size = os.path.getsize(db_path)
    print(f"✅ Database exists: {db_path}")
    print(f"   Size: {file_size:,} bytes\n")
    
    # Check 2: Table structure
    print("⚡ CHECK 2: Table Structure")
    print("-" * 40)
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table info
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        if not tables:
            print("❌ No tables found in database\n")
            conn.close()
            return False
        
        print(f"✅ Tables found: {[t[0] for t in tables]}")
        
        # Get wicks table schema
        cursor.execute("PRAGMA table_info(wicks)")
        columns = cursor.fetchall()
        
        expected_columns = [
            'id', 'timestamp', 'symbol', 'open', 'high', 'low', 'close',
            'upper_wick', 'lower_wick', 'body', 'wick_type', 
            'sequence_position', 'created_at'
        ]
        
        actual_columns = [col[1] for col in columns]
        
        if set(actual_columns) == set(expected_columns):
            print(f"✅ Schema valid: {len(columns)} columns")
            for col in columns[:3]:  # Show first 3 columns
                print(f"   - {col[1]} ({col[2]})")
            print(f"   ... and {len(columns)-3} more\n")
        else:
            print("❌ Schema mismatch")
            print(f"   Expected: {expected_columns}")
            print(f"   Found: {actual_columns}\n")
            conn.close()
            return False
        
    except Exception as e:
        print(f"❌ Error checking table: {e}\n")
        return False
    
    # Check 3: Data storage
    print("⚡ CHECK 3: Data Storage")
    print("-" * 40)
    try:
        cursor.execute("SELECT COUNT(*) FROM wicks")
        total_wicks = cursor.fetchone()[0]
        
        if total_wicks == 0:
            print("⚠️  No wicks stored yet")
            print("   Run okx_wick_detector.py and wait for wicks to be detected.\n")
            conn.close()
            return True
        
        print(f"✅ Total wicks stored: {total_wicks}")
        
        # Get sequence stats
        cursor.execute("SELECT COUNT(*) FROM wicks WHERE sequence_position IS NOT NULL")
        sequenced_wicks = cursor.fetchone()[0]
        
        cursor.execute("SELECT MAX(sequence_position) FROM wicks")
        max_sequence = cursor.fetchone()[0]
        
        print(f"   Sequenced wicks: {sequenced_wicks}")
        print(f"   Max sequence: {max_sequence}/5\n")
        
        # Check 4: Show recent wicks
        print("⚡ CHECK 4: Recent Wicks (Last 10)")
        print("-" * 40)
        
        cursor.execute('''
            SELECT id, timestamp, symbol, wick_type, 
                   upper_wick, lower_wick, sequence_position
            FROM wicks 
            ORDER BY id DESC 
            LIMIT 10
        ''')
        
        recent_wicks = cursor.fetchall()
        
        if not recent_wicks:
            print("⚠️  No wicks to display\n")
        else:
            print(f"{'ID':<6} {'Timestamp':<20} {'Symbol':<12} {'Type':<8} {'Upper':<8} {'Lower':<8} {'Seq':<5}")
            print("-" * 80)
            for wick in recent_wicks:
                wick_id, ts, symbol, wtype, upper, lower, seq = wick
                seq_str = f"{seq}/5" if seq else "---"
                print(f"{wick_id:<6} {ts:<20} {symbol:<12} {wtype:<8} {upper:<8.2f} {lower:<8.2f} {seq_str:<5}")
            print()
        
        # Check 5: Data quality
        print("⚡ CHECK 5: Data Quality")
        print("-" * 40)
        
        # Check for nulls in critical fields
        cursor.execute('''
            SELECT COUNT(*) FROM wicks 
            WHERE timestamp IS NULL 
               OR symbol IS NULL 
               OR wick_type IS NULL
        ''')
        null_count = cursor.fetchone()[0]
        
        if null_count > 0:
            print(f"❌ Found {null_count} rows with NULL critical fields\n")
            conn.close()
            return False
        
        print("✅ No NULL values in critical fields")
        
        # Check for valid wick types
        cursor.execute("SELECT DISTINCT wick_type FROM wicks")
        wick_types = [w[0] for w in cursor.fetchall()]
        
        valid_types = ['UPPER', 'LOWER']
        invalid_types = [wt for wt in wick_types if wt not in valid_types]
        
        if invalid_types:
            print(f"❌ Invalid wick types found: {invalid_types}\n")
            conn.close()
            return False
        
        print(f"✅ Valid wick types: {wick_types}")
        
        # Stats
        cursor.execute("SELECT wick_type, COUNT(*) FROM wicks GROUP BY wick_type")
        type_counts = cursor.fetchall()
        
        print("\n📊 Wick Type Distribution:")
        for wtype, count in type_counts:
            percentage = (count / total_wicks) * 100
            print(f"   {wtype}: {count} ({percentage:.1f}%)")
        
        conn.close()
        
        print("\n" + "="*60)
        print("✅ ALL CHECKS PASSED")
        print("="*60 + "\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Error validating data: {e}\n")
        conn.close()
        return False


if __name__ == "__main__":
    success = validate_database()
    exit(0 if success else 1)
