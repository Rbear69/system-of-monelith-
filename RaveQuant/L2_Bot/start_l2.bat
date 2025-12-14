@echo off
echo ========================================
echo OKX L2 Orderbook Exporter
echo ========================================
echo.
echo Instruments: BTC-USDT-SWAP, ETH-USDT-SWAP
echo Depth: Top 400 levels
echo Cadence: 2 seconds
echo.
echo Press Ctrl+C to stop
echo ========================================
echo.

python l2_exporter.py

pause
