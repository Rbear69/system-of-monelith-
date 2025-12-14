# L2 ORDERBOOK EXPORTER - OKX PERPS

**Deep liquidity intelligence for BTC-USDT-SWAP & ETH-USDT-SWAP**

---

## MISSION

Capture top 400 levels of orderbook depth every 2 seconds:
- Track liquidity concentration zones
- Identify support/resistance from resting orders
- Detect whale walls and liquidity shifts
- Feed notional calculations for position sizing

---

## ARCHITECTURE

```
OKX WebSocket ("books" channel)
        ↓
 [In-Memory Orderbook]
  - Incremental updates
  - Gap detection
  - Checksum validation
        ↓
 [Snapshot Writer] (every 2s)
        ↓
Vault\raw\okx\l2_perps\{INSTID}\{DATE}\{HOUR}.jsonl
```

---

## CONFIGURATION

**Instruments:** BTC-USDT-SWAP, ETH-USDT-SWAP  
**Depth:** Top 400 levels per side  
**Cadence:** 2 seconds (configurable)  
**Rotation:** Hourly JSONL files  
**Retention:**  
- 6 hours uncompressed
- Then compress to .gz
- Delete after 5 days

---

## DATA FORMAT

### Snapshot Record (JSONL)
```json
{
  "timestamp_utc": "2023-12-14T15:30:45.123Z",
  "exchange": "okx",
  "market": "perp",
  "channel": "books",
  "instId": "BTC-USDT-SWAP",
  "bids_top400": [
    ["43250.5", "100", "0", "5"],
    ["43250.0", "200", "0", "8"]
  ],
  "asks_top400": [
    ["43251.0", "150", "0", "6"],
    ["43251.5", "180", "0", "7"]
  ],
  "best_bid": "43250.5",
  "best_ask": "43251.0",
  "mid_price": "43250.75",
  "checksum": -123456789,
  "seqId": 987654321,
  "prevSeqId": 987654320,
  "gap_detected": false
}
```

**Level Format:** `[price_str, qty_str, "0", order_count_str]`
- `price_str` - Price level
- `qty_str` - Quantity in contracts
- `"0"` - Deprecated field (always "0")
- `order_count_str` - Number of orders at this level

---

## USAGE

### Start L2 Exporter
```bash
cd "C:\Users\M.R Bear\Documents\RaveQuant\L2_Bot"
python l2_exporter.py
```

Or use batch launcher:
```bash
start_l2.bat
```

### Run Retention Management
```bash
python l2_retention.py
```

Schedule this hourly (Windows Task Scheduler or cron).

---

## FEATURES

### Gap Detection
- Tracks `seqId` and `prevSeqId` from OKX
- If `prevSeqId != last_seqId` → gap detected
- Actions:
  1. Write snapshot with `gap_detected=true`
  2. Clear in-memory orderbook
  3. Force resubscribe
  4. Wait for fresh snapshot

**Why:** Prevents writing corrupt orderbook state after missed updates.

### Checksum Validation
- OKX provides CRC32 checksum of top 25 levels
- Validates after each update
- Logs warnings on mismatch (doesn't stop)
- Helps detect orderbook corruption

### Deduplication
- Tracks written timestamps per instrument
- Skips duplicate writes (same `timestamp_utc`)
- Idempotent: safe to restart anytime

### Hourly Rotation
- Files named: `{HOUR}.jsonl` (00-23)
- New file created automatically each hour
- Clean time-based file organization

---

## RETENTION POLICY

### Compression (After 6 Hours)
```
15.jsonl → 15.jsonl.gz (gzip compression)
Delete 15.jsonl
```

**Why:** Reduces storage ~10x while keeping recent data fast.

### Deletion (After 5 Days)
```
Delete 15.jsonl.gz
```

**Why:** Balance historical data vs disk usage.

---

## MONITORING

### Check Exporter Status
```bash
# Logs
type "C:\Users\M.R Bear\Documents\RaveQuant\L2_Bot\l2_exporter.log"

# Recent snapshots
dir "C:\Users\M.R Bear\Documents\RaveQuant\Rave_Quant_Vault\raw\okx\l2_perps\BTC-USDT-SWAP"
```

### Verify Snapshots
```bash
# Latest hour file
type "C:\Users\M.R Bear\Documents\RaveQuant\Rave_Quant_Vault\raw\okx\l2_perps\BTC-USDT-SWAP\2023-12-14\15.jsonl"
```

### Health Metrics
Watch logs for:
- `Snapshot written` - Successful writes
- `GAP DETECTED` - Orderbook gaps
- `Checksum mismatch` - Validation warnings
- `Forced resubscribe` - Gap recovery

---

## INSTRUMENT METADATA

Fetched once per instrument from OKX REST API:  
`/api/v5/public/instruments?instType=SWAP&instId={INSTID}`

**Saved to:**  
`Vault\meta\okx\instruments\{INSTID}.json`

**Contains:**
- Contract value / multiplier
- Tick size
- Lot size
- Settlement currency
- Min order size

**Used for:** Converting contract quantities to base quantity and notional value.

---

## FILE STRUCTURE

```
L2_Bot\
├── l2_exporter.py       - Main exporter
├── l2_retention.py      - Compression + deletion
├── start_l2.bat         - Launcher
├── requirements.txt     - Dependencies
└── README.md            - This file

Vault\
├── raw\okx\l2_perps\
│   ├── BTC-USDT-SWAP\
│   │   └── 2023-12-14\
│   │       ├── 15.jsonl
│   │       ├── 16.jsonl.gz
│   │       └── ...
│   └── ETH-USDT-SWAP\
│       └── ...
└── meta\okx\instruments\
    ├── BTC-USDT-SWAP.json
    └── ETH-USDT-SWAP.json
```

---

## ADVERSARIAL USE CASES

### 1. Liquidity Wall Detection
```python
# Load snapshot
snapshot = json.loads(line)

# Find large bids (whale walls)
whale_bids = [
    level for level in snapshot['bids_top400']
    if float(level[1]) > 1000  # >1000 contracts
]
```

### 2. Support/Resistance Zones
```python
# Cluster levels by price
from collections import defaultdict

liquidity_zones = defaultdict(float)
for level in snapshot['bids_top400']:
    price_zone = int(float(level[0]) / 100) * 100  # $100 zones
    liquidity_zones[price_zone] += float(level[1])

# Top 5 zones
top_zones = sorted(liquidity_zones.items(), key=lambda x: x[1], reverse=True)[:5]
```

### 3. Spread Monitoring
```python
best_bid = float(snapshot['best_bid'])
best_ask = float(snapshot['best_ask'])
spread_bps = ((best_ask - best_bid) / best_bid) * 10000

if spread_bps > 10:  # >10 bps
    print("WIDE SPREAD - Low liquidity")
```

### 4. Liquidity Imbalance
```python
# Sum top 10 levels each side
bid_liq = sum(float(level[1]) for level in snapshot['bids_top400'][:10])
ask_liq = sum(float(level[1]) for level in snapshot['asks_top400'][:10])

imbalance = (bid_liq - ask_liq) / (bid_liq + ask_liq)

if imbalance > 0.3:  # 30% more bids
    print("BUY PRESSURE")
elif imbalance < -0.3:
    print("SELL PRESSURE")
```

---

## PERFORMANCE

**Write Rate:** ~2 snapshots/sec × 2 instruments = 4 writes/sec  
**File Size:** ~200KB/hour uncompressed, ~20KB/hour compressed  
**Daily Storage:** ~10MB/day compressed per instrument  
**Memory:** <50MB (orderbook + dedup tracking)  
**CPU:** <2% (idle), <5% (active updates)

---

## TROUBLESHOOTING

**"BUILD_FAIL: Missing required fields"**  
→ OKX changed message schema. Check logs for missing fields.

**"GAP DETECTED" frequently**  
→ Network instability or OKX server issues. Check connection.

**"Checksum mismatch" warnings**  
→ Orderbook corruption detected. Should auto-recover via gap detection.

**No snapshots written**  
→ Check if WebSocket connected. Verify instruments subscribed.

**Files not compressing**  
→ Run `l2_retention.py` manually to test. Check file ages.

---

## EXPANSION

### Add More Instruments
Edit `l2_exporter.py`:
```python
INSTRUMENTS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",  # Add here
]
```

### Change Snapshot Cadence
```python
SNAPSHOT_CADENCE_SEC = 1  # 1s snapshots
```

### Adjust Depth
```python
DEPTH_LEVELS = 200  # Top 200 levels
```

---

**Deep liquidity intelligence. Hunt the whales.**
