"""
WICK VALIDATOR - Query Untouched Wicks
=======================================

Query the wick database to find untouched wicks across all timeframes.
Perfect for finding high-probability entry zones.

USAGE:
    python validator_complete.py

Interactive menu lets you:
1. View all active untouched wicks
2. Find wicks near current price
3. Get wick statistics
4. Export to CSV
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict


class WickValidator:
    def __init__(self):
        """Initialize wick validator"""
        script_dir = Path(__file__).parent.absolute()
        self.db_path = script_dir / "wick_data_multitf.db"
        
        if not self.db_path.exists():
            print(f"❌ Database not found: {self.db_path}")
            print("   Run okx_wick_detector_COMPLETE.py first")
            exit(1)
        
        print(f"✅ Connected to: {self.db_path}")
    
    def get_active_wicks(self, timeframe: str = None, wick_type: str = None) -> List[Dict]:
        """
        Get all active untouched wicks
        
        Args:
            timeframe: Filter by timeframe (1m, 5m, 15m, 1H, 4H, 1D) or None for all
            wick_type: Filter by UPPER/LOWER or None for all
        
        Returns:
            List of active wick dictionaries
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            query = "SELECT * FROM untouched_wicks WHERE status = 'ACTIVE'"
            params = []
            
            if timeframe:
                query += " AND timeframe = ?"
                params.append(timeframe)
            
            if wick_type:
                query += " AND wick_type = ?"
                params.append(wick_type)
            
            query += " ORDER BY timeframe, formation_time DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            conn.close()
            
            # Convert to dictionaries
            wicks = []
            for row in rows:
                wick = {
                    'id': row[0],
                    'timeframe': row[1],
                    'wick_type': row[2],
                    'formation_time': row[3],
                    'wick_price': row[4],
                    'candle_high': row[5],
                    'candle_low': row[6],
                    'candle_close': row[7],
                    'wick_size': row[8],
                    'status': row[9]
                }
                
                # Calculate age
                formation_dt = datetime.strptime(wick['formation_time'], '%Y-%m-%d %H:%M:%S')
                age = datetime.now() - formation_dt
                wick['age_hours'] = round(age.total_seconds() / 3600, 2)
                
                wicks.append(wick)
            
            return wicks
            
        except Exception as e:
            print(f"❌ Query error: {e}")
            return []
    
    def find_wicks_near_price(self, price: float, tolerance_pct: float = 1.0, 
                              timeframe: str = None) -> List[Dict]:
        """
        Find untouched wicks near a specific price
        
        Args:
            price: Target price to search near
            tolerance_pct: Price tolerance (% from target)
            timeframe: Filter by timeframe or None for all
        
        Returns:
            List of wicks within tolerance
        """
        wicks = self.get_active_wicks(timeframe=timeframe)
        
        tolerance = price * (tolerance_pct / 100)
        min_price = price - tolerance
        max_price = price + tolerance
        
        nearby = [w for w in wicks if min_price <= w['wick_price'] <= max_price]
        
        # Sort by distance from target price
        for wick in nearby:
            wick['distance'] = abs(wick['wick_price'] - price)
            wick['distance_pct'] = (wick['distance'] / price) * 100
        
        return sorted(nearby, key=lambda x: x['distance'])
    
    def get_statistics(self) -> Dict:
        """Get overall wick tracking statistics"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            stats = {}
            
            # Total wicks by status
            cursor.execute("SELECT status, COUNT(*) FROM untouched_wicks GROUP BY status")
            stats['by_status'] = dict(cursor.fetchall())
            
            # Wicks by timeframe
            cursor.execute("""
                SELECT timeframe, status, COUNT(*) 
                FROM untouched_wicks 
                GROUP BY timeframe, status
            """)
            tf_stats = {}
            for row in cursor.fetchall():
                tf = row[0]
                if tf not in tf_stats:
                    tf_stats[tf] = {}
                tf_stats[tf][row[1]] = row[2]
            stats['by_timeframe'] = tf_stats
            
            # Average wick lifetime (for touched wicks)
            cursor.execute("""
                SELECT AVG(
                    (julianday(touched_time) - julianday(formation_time)) * 24
                ) FROM untouched_wicks 
                WHERE status = 'TOUCHED'
            """)
            result = cursor.fetchone()
            stats['avg_lifetime_hours'] = round(result[0], 2) if result[0] else 0
            
            # Total candles processed
            cursor.execute("SELECT COUNT(*) FROM candles")
            stats['total_candles'] = cursor.fetchone()[0]
            
            conn.close()
            return stats
            
        except Exception as e:
            print(f"❌ Stats error: {e}")
            return {}
    
    def print_wicks(self, wicks: List[Dict]):
        """Pretty print wick list"""
        if not wicks:
            print("   No wicks found")
            return
        
        print(f"\n{'TF':<6} {'Type':<8} {'Price':<12} {'Age (hrs)':<12} {'Size':<10}")
        print("-" * 60)
        
        for wick in wicks:
            print(f"{wick['timeframe']:<6} "
                  f"{wick['wick_type']:<8} "
                  f"${wick['wick_price']:>10,.2f} "
                  f"{wick['age_hours']:>10.2f} "
                  f"{wick['wick_size']:>8.2f}")
    
    def export_to_csv(self, wicks: List[Dict], filename: str = "active_wicks.csv"):
        """Export wicks to CSV"""
        try:
            import csv
            
            script_dir = Path(__file__).parent.absolute()
            filepath = script_dir / filename
            
            with open(filepath, 'w', newline='') as f:
                if not wicks:
                    f.write("No active wicks\n")
                    return
                
                writer = csv.DictWriter(f, fieldnames=wicks[0].keys())
                writer.writeheader()
                writer.writerows(wicks)
            
            print(f"✅ Exported to: {filepath}")
            
        except Exception as e:
            print(f"❌ Export error: {e}")
    
    def interactive_menu(self):
        """Interactive query menu"""
        while True:
            print("\n" + "="*60)
            print("WICK VALIDATOR - INTERACTIVE MENU")
            print("="*60)
            print("1. View all active untouched wicks")
            print("2. Find wicks near current price")
            print("3. Filter by timeframe")
            print("4. View statistics")
            print("5. Export active wicks to CSV")
            print("6. Exit")
            print("="*60)
            
            choice = input("\nSelect option (1-6): ").strip()
            
            if choice == '1':
                print("\n🔍 ALL ACTIVE UNTOUCHED WICKS:")
                wicks = self.get_active_wicks()
                print(f"\nFound {len(wicks)} active wicks")
                self.print_wicks(wicks)
            
            elif choice == '2':
                try:
                    price = float(input("\nEnter price to search near: $"))
                    tolerance = float(input("Enter tolerance % (default 1.0): ") or "1.0")
                    
                    wicks = self.find_wicks_near_price(price, tolerance)
                    print(f"\n🎯 WICKS WITHIN {tolerance}% OF ${price:,.2f}:")
                    print(f"Found {len(wicks)} wicks")
                    self.print_wicks(wicks)
                except ValueError:
                    print("❌ Invalid input")
            
            elif choice == '3':
                print("\nTimeframes: 1m, 5m, 15m, 1H, 4H, 1D")
                tf = input("Enter timeframe: ").strip()
                
                wicks = self.get_active_wicks(timeframe=tf)
                print(f"\n🔍 ACTIVE WICKS ON {tf}:")
                print(f"Found {len(wicks)} wicks")
                self.print_wicks(wicks)
            
            elif choice == '4':
                print("\n📊 STATISTICS:")
                stats = self.get_statistics()
                
                print(f"\nTotal candles processed: {stats.get('total_candles', 0)}")
                print(f"\nWicks by status:")
                for status, count in stats.get('by_status', {}).items():
                    print(f"  {status}: {count}")
                
                print(f"\nWicks by timeframe:")
                for tf, tf_stats in stats.get('by_timeframe', {}).items():
                    active = tf_stats.get('ACTIVE', 0)
                    touched = tf_stats.get('TOUCHED', 0)
                    print(f"  {tf}: {active} active, {touched} touched")
                
                print(f"\nAverage wick lifetime: {stats.get('avg_lifetime_hours', 0):.2f} hours")
            
            elif choice == '5':
                wicks = self.get_active_wicks()
                self.export_to_csv(wicks)
            
            elif choice == '6':
                print("\n👋 Goodbye")
                break
            
            else:
                print("❌ Invalid option")


def main():
    """Run validator"""
    print("\n" + "="*60)
    print("  WICK VALIDATOR - QUERY UNTOUCHED WICKS")
    print("="*60)
    
    validator = WickValidator()
    validator.interactive_menu()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Exited")
