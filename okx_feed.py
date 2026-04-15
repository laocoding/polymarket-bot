#!/usr/bin/env python3
"""
OKX BTC/USDT Real-Time Data Feed (ccxt free version)

v2 Phase 1: High-Speed Data Ingestion
Polls OKX for BTC/USDT price data and provides signals
that can be consumed by the Polymarket trading bot.
"""

import ccxt
import json
import time
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "okx_data"
TICKER_LOG = DATA_DIR / "tickers.jsonl"
KLINE_LOG = DATA_DIR / "klines_1m.jsonl"
LATEST_FILE = DATA_DIR / "latest.json"


class OKXFeed:
    """Fetches BTC/USDT market data from OKX via ccxt (REST polling)."""

    def __init__(self, symbol="BTC/USDT", kline_tf="1m"):
        self.symbol = symbol
        self.kline_tf = kline_tf
        self.exchange = ccxt.okx({"enableRateLimit": True})
        self.running = False

        # in-memory price history for signal helpers
        self.prices = []
        self.klines = []

        DATA_DIR.mkdir(exist_ok=True)

    # ── single-shot fetchers ──────────────────────────────────────

    def fetch_ticker(self):
        """Return current ticker dict and append to log."""
        ticker = self.exchange.fetch_ticker(self.symbol)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "last": ticker["last"],
            "bid": ticker["bid"],
            "ask": ticker["ask"],
            "vol_24h": ticker["quoteVolume"],
            "high": ticker["high"],
            "low": ticker["low"],
        }
        self.prices.append(record)
        self._append_jsonl(TICKER_LOG, record)
        self._write_latest(record)
        return record

    def fetch_klines(self, limit=60):
        """Return latest 1m klines and append new ones to log."""
        ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.kline_tf, limit=limit)
        new_klines = []
        seen_ts = {k["ts"] for k in self.klines}
        for candle in ohlcv:
            ts, o, h, l, c, v = candle
            rec = {
                "ts": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
            iso = rec["ts"]
            if iso not in seen_ts:
                new_klines.append(rec)
                self.klines.append(rec)
                seen_ts.add(iso)
                self._append_jsonl(KLINE_LOG, rec)
        # keep memory bounded
        self.klines = self.klines[-200:]
        self.prices = self.prices[-500:]
        return new_klines

    # ── signal helpers ────────────────────────────────────────────

    def momentum(self, window=5):
        """Simple price momentum over last `window` ticks.
        Returns (direction, pct_change) e.g. ("UP", 0.12) or ("DOWN", -0.08).
        Returns None if not enough data.
        """
        if len(self.prices) < window:
            return None
        recent = [p["last"] for p in self.prices[-window:]]
        first, last = recent[0], recent[-1]
        pct = ((last - first) / first) * 100
        direction = "UP" if pct >= 0 else "DOWN"
        return direction, round(pct, 4)

    def ema(self, period=14):
        """Exponential moving average over recent closes from klines.
        Returns (ema_value, price_vs_ema) where price_vs_ema is 'ABOVE' or 'BELOW'.
        Returns None if not enough data.
        """
        closes = [k["close"] for k in self.klines]
        if len(closes) < period:
            return None
        multiplier = 2 / (period + 1)
        ema_val = closes[0]
        for c in closes[1:]:
            ema_val = (c - ema_val) * multiplier + ema_val
        current = closes[-1]
        position = "ABOVE" if current >= ema_val else "BELOW"
        return round(ema_val, 2), position

    def volatility(self, window=20):
        """Standard deviation of recent closes (from klines).
        Returns None if not enough data.
        """
        closes = [k["close"] for k in self.klines]
        if len(closes) < window:
            return None
        recent = closes[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        return round(variance ** 0.5, 2)

    def summary(self):
        """One-shot summary of current BTC state for the trading bot."""
        ticker = self.fetch_ticker()
        self.fetch_klines(limit=60)

        result = {
            "price": ticker["last"],
            "bid": ticker["bid"],
            "ask": ticker["ask"],
            "spread": round(ticker["ask"] - ticker["bid"], 2),
            "momentum_60": self.momentum(60),   # 60 ticks × 2s = 2min (for M5 markets)
            "momentum_150": self.momentum(150),  # 150 ticks × 2s = 5min (full market window)
            "ema_5": self.ema(5),                # 5 × 1m = 5min EMA (matches M5)
            "ema_14": self.ema(14),              # 14 × 1m = 14min EMA (trend)
            "volatility_5": self.volatility(5),  # 5 × 1m volatility
            "ts": ticker["ts"],
        }
        return result

    # ── continuous polling loop ───────────────────────────────────

    def run(self, interval=2):
        """Poll ticker every `interval` seconds, klines every 30s. Ctrl+C to stop."""
        self.running = True
        signal.signal(signal.SIGINT, lambda *_: self._stop())

        print(f"[OKX Feed] Polling {self.symbol} every {interval}s  (Ctrl+C to stop)")
        print(f"[OKX Feed] Data dir: {DATA_DIR}")

        # initial kline fetch
        self.fetch_klines(limit=60)
        print(f"[OKX Feed] Loaded {len(self.klines)} initial 1m klines")

        tick = 0
        kline_every = max(1, int(30 / interval))

        while self.running:
            try:
                t = self.fetch_ticker()
                mom = self.momentum(5)
                ema_data = self.ema(14)

                mom_str = f"{mom[0]} {mom[1]:+.4f}%" if mom else "n/a"
                ema_str = f"{ema_data[0]} ({ema_data[1]})" if ema_data else "n/a"

                print(
                    f"[{t['ts'][:19]}]  "
                    f"BTC ${t['last']:,.2f}  "
                    f"bid/ask ${t['bid']:,.2f}/${t['ask']:,.2f}  "
                    f"mom5={mom_str}  ema14={ema_str}"
                )

                tick += 1
                if tick % kline_every == 0:
                    new = self.fetch_klines(limit=10)
                    if new:
                        print(f"  +{len(new)} new kline(s)")

                time.sleep(interval)

            except ccxt.NetworkError as e:
                print(f"[OKX Feed] Network error: {e}, retrying in 5s...")
                time.sleep(5)
            except ccxt.ExchangeError as e:
                print(f"[OKX Feed] Exchange error: {e}, retrying in 10s...")
                time.sleep(10)

        print("[OKX Feed] Stopped.")

    def _stop(self):
        self.running = False

    # ── file helpers ──────────────────────────────────────────────

    @staticmethod
    def _append_jsonl(path, record):
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")

    @staticmethod
    def _write_latest(record):
        with open(LATEST_FILE, "w") as f:
            json.dump(record, f, indent=2)


# ── CLI entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OKX BTC/USDT data feed")
    parser.add_argument("--interval", type=int, default=2, help="Poll interval in seconds (default: 2)")
    parser.add_argument("--summary", action="store_true", help="Print one-shot summary and exit")
    args = parser.parse_args()

    feed = OKXFeed()

    if args.summary:
        s = feed.summary()
        print(json.dumps(s, indent=2))
    else:
        feed.run(interval=args.interval)
