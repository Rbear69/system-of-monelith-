"""
L2 Retention Manager
--------------------
Manages compression and deletion of L2 orderbook files.

POLICY:
- Keep last 6 hours UNCOMPRESSED for fast reads
- Compress files older than 6 hours to .jsonl.gz
- Delete .gz files older than 5 days

Run this separately from l2_exporter.py (e.g., hourly cron job)
"""

import gzip
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Configuration
VAULT_BASE = Path(r"C:\Users\M.R Bear\Documents\RaveQuant\Rave_Quant_Vault")
UNCOMPRESSED_HOURS = 6
RETENTION_DAYS = 5

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('L2_Retention')


def compress_old_files():
    """Compress .jsonl files older than UNCOMPRESSED_HOURS."""
    compressed_count = 0
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=UNCOMPRESSED_HOURS)
    
    l2_dir = VAULT_BASE / 'raw' / 'okx' / 'l2_perps'
    
    if not l2_dir.exists():
        logger.warning(f"L2 directory not found: {l2_dir}")
        return 0
    
    # Find all .jsonl files
    for jsonl_file in l2_dir.rglob('*.jsonl'):
        try:
            # Get file modification time
            file_mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            
            # Check if older than cutoff
            if file_mtime < cutoff_time:
                gz_file = jsonl_file.with_suffix('.jsonl.gz')
                
                # Skip if already compressed
                if gz_file.exists():
                    continue
                
                # Compress
                logger.info(f"Compressing: {jsonl_file}")
                with open(jsonl_file, 'rb') as f_in:
                    with gzip.open(gz_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Delete original
                jsonl_file.unlink()
                compressed_count += 1
                logger.info(f"Compressed and deleted: {jsonl_file.name}")
        
        except Exception as e:
            logger.error(f"Failed to compress {jsonl_file}: {e}")
    
    return compressed_count


def delete_old_compressed():
    """Delete .jsonl.gz files older than RETENTION_DAYS."""
    deleted_count = 0
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    
    l2_dir = VAULT_BASE / 'raw' / 'okx' / 'l2_perps'
    
    if not l2_dir.exists():
        return 0
    
    # Find all .jsonl.gz files
    for gz_file in l2_dir.rglob('*.jsonl.gz'):
        try:
            # Get file modification time
            file_mtime = datetime.fromtimestamp(gz_file.stat().st_mtime, tz=timezone.utc)
            
            # Check if older than cutoff
            if file_mtime < cutoff_time:
                logger.info(f"Deleting old compressed file: {gz_file}")
                gz_file.unlink()
                deleted_count += 1
        
        except Exception as e:
            logger.error(f"Failed to delete {gz_file}: {e}")
    
    return deleted_count


def main():
    """Run retention management."""
    logger.info("Starting L2 retention management")
    logger.info(f"Uncompressed hours: {UNCOMPRESSED_HOURS}")
    logger.info(f"Retention days: {RETENTION_DAYS}")
    
    # Compress old files
    compressed = compress_old_files()
    logger.info(f"Compressed {compressed} files")
    
    # Delete old compressed files
    deleted = delete_old_compressed()
    logger.info(f"Deleted {deleted} old compressed files")
    
    logger.info("Retention management complete")


if __name__ == '__main__':
    main()
