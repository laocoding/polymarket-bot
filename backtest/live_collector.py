#!/usr/bin/env python3
"""
Live tick data collector for BTC Up/Down 5m markets.

Runs continuously, capturing price snapshots every few seconds for each active
market. When a market resolves, it records the outcome. This produces the
tick-level data needed to properly backtest the signal logic.

Data format (backtest/ticks.json):
{
  "markets": {
    "btc-updown-5m-1713000000": {
      "slug": "btc-updown-5m-1713000000",
      "start_ts": 1713000000,
      "ticks": [
        {"t": 1713000002, "up": 0.52, "down": 0.48, "src": "clob"},
        {"t": 1713000005, "up": 0.55, "down": 0.45, "src": "clob"},
        ...
      ],
      "winner": "Up",          // null while active
      "resolved_at": 1713000300
    }
  },
  "collection_started": "2026-04-13T...",
  "last_updated": "2026-04-13T..."
}

Usage:
    python backtest/live_collector.py [--interval 3] [--output backtest/ticks.json]

Let it run for 3-4 days to collect 500-1000 markets with full tick histories.
"""

import json
import time
import os
import sys
import signal
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TICKS_FILE_DEFAULT = PROJECT_ROOT / "backtest" / "ticks.json"
GAMMA_API = "https://gamma-api.polymarket.com/markets"


def load_ticks(path):
    """Load existing tick data or create empty structure."""
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {
        "markets": {},
        "collection_started": datetime.now(timezone.utc).isoformat(),
        "last_updated": None,
        "stats": {"total_markets": 0, "resolved": 0, "ticks_collected": 0},
    }


def save_ticks(data, path):
    """Save tick data to disk. Uses atomic write to avoid corruption."""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Count stats
    markets = data["markets"]
    data["stats"] = {
        "total_markets": len(markets),
        "resolved": sum(1 for m in markets.values() if m.get("winner")),
        "ticks_collected": sum(len(m.get("ticks", [])) for m in markets.values()),
    }

    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, str(path))


def get_current_slug():
    """Calculate the current active market slug from timestamp."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    base_ts = (now_ts // 300) * 300
    return f"btc-updown-5m-{base_ts}", base_ts, now_ts


def fetch_market_data(slug):
    """Fetch market data from Gamma API."""
    import requests

    try:
        url = f"{GAMMA_API}?slug={slug}&t={int(time.time()*1000)}"
        resp = requests.get(url, headers={"Accept-Encoding": "none"}, timeout=10)
        if resp.status_code == 200 and resp.json():
            return resp.json()[0]
    except Exception as e:
        print(f"  [warn] Gamma API error for {slug}: {e}")
    return None


def fetch_clob_prices(token_ids):
    """Fetch real-time prices from CLOB API."""
    try:
        from py_clob_client.client import ClobClient

        client = ClobClient("https://clob.polymarket.com")
        if len(token_ids) >= 2:
            p_up = client.get_last_trade_price(token_ids[0])
            p_down = client.get_last_trade_price(token_ids[1])
            up = float(p_up.get("price", 0))
            down = float(p_down.get("price", 0))
            if 0.01 < up < 0.99:
                return up, down, "clob"
    except Exception:
        pass
    return None, None, None


def parse_json_field(val):
    """Parse JSON string or return as-is."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return []
    return val if val else []


def get_prices_from_gamma(market_data):
    """Extract prices from Gamma API market data."""
    best_bid = market_data.get("bestBid")
    best_ask = market_data.get("bestAsk")
    last_price = market_data.get("lastTradePrice")
    outcome_prices = parse_json_field(market_data.get("outcomePrices", "[]"))

    if best_bid and best_ask:
        try:
            return float(best_ask), float(best_bid), "gamma_bbo"
        except (ValueError, TypeError):
            pass

    if last_price:
        try:
            mid = float(last_price)
            return min(mid + 0.01, 0.99), max(mid - 0.01, 0.01), "gamma_last"
        except (ValueError, TypeError):
            pass

    if len(outcome_prices) >= 2:
        try:
            return float(outcome_prices[0]), float(outcome_prices[1]), "gamma_outcome"
        except (ValueError, TypeError):
            pass

    return None, None, None


def check_resolution(slug, market_data):
    """Check if a market has resolved and determine winner."""
    if not market_data:
        return None

    closed = market_data.get("closed", False)
    if not closed:
        return None

    outcome_prices = parse_json_field(market_data.get("outcomePrices", "[]"))
    if len(outcome_prices) >= 2:
        try:
            up_final = float(outcome_prices[0])
            down_final = float(outcome_prices[1])
            if up_final >= 0.99:
                return "Up"
            elif down_final >= 0.99:
                return "Down"
        except (ValueError, TypeError):
            pass
    return None


def run_collector(interval, output_path, save_interval=30):
    """Main collection loop."""
    data = load_ticks(output_path)
    print(f"=== Live Tick Collector ===")
    print(f"Interval: {interval}s | Save every: {save_interval}s")
    print(f"Output: {output_path}")

    existing = data["stats"]
    print(f"Existing data: {existing['total_markets']} markets, "
          f"{existing['resolved']} resolved, {existing['ticks_collected']} ticks")
    print(f"Press Ctrl+C to stop (data is saved periodically)\n")

    last_save_time = time.time()
    last_slug = None
    ticks_since_save = 0
    markets_resolved_session = 0

    # Graceful shutdown
    shutdown = False

    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True
        print("\n[!] Shutting down, saving data...")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not shutdown:
        try:
            slug, start_ts, now_ts = get_current_slug()
            elapsed_in_market = now_ts - start_ts
            remaining = 300 - elapsed_in_market

            # Detect market rotation
            if slug != last_slug:
                if last_slug:
                    print(f"\n--- Market rotated: {last_slug} -> {slug} ---")
                    # Check resolution of previous market
                    prev_data = fetch_market_data(last_slug)
                    if prev_data:
                        winner = check_resolution(last_slug, prev_data)
                        if winner and last_slug in data["markets"]:
                            data["markets"][last_slug]["winner"] = winner
                            data["markets"][last_slug]["resolved_at"] = now_ts
                            markets_resolved_session += 1
                            tick_count = len(data["markets"][last_slug].get("ticks", []))
                            print(f"  Resolved: {last_slug} -> {winner} ({tick_count} ticks)")
                else:
                    print(f"Starting with market: {slug}")

                last_slug = slug

                # Initialize market entry if new
                if slug not in data["markets"]:
                    data["markets"][slug] = {
                        "slug": slug,
                        "start_ts": start_ts,
                        "ticks": [],
                        "winner": None,
                        "resolved_at": None,
                    }

            # Fetch current prices
            market_data = fetch_market_data(slug)
            if not market_data:
                time.sleep(interval)
                continue

            # Get token IDs for CLOB
            token_ids = parse_json_field(market_data.get("clobTokenIds", "[]"))

            # Try CLOB first (more accurate), fall back to Gamma
            up_price, down_price, src = fetch_clob_prices(token_ids)
            if up_price is None:
                up_price, down_price, src = get_prices_from_gamma(market_data)

            if up_price is not None and down_price is not None:
                tick = {
                    "t": now_ts,
                    "up": round(up_price, 4),
                    "down": round(down_price, 4),
                    "src": src,
                }
                data["markets"][slug]["ticks"].append(tick)
                ticks_since_save += 1

                # Status line
                dominant = "UP" if up_price > down_price else "DOWN"
                dom_price = max(up_price, down_price)
                total_resolved = sum(1 for m in data["markets"].values() if m.get("winner"))
                total_ticks = sum(len(m.get("ticks", [])) for m in data["markets"].values())

                time_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(
                    f"[{time_str}] {slug[-10:]} | "
                    f"Up=${up_price:.3f} Down=${down_price:.3f} | "
                    f"{dominant} @{dom_price:.3f} | "
                    f"{remaining}s left | "
                    f"ticks={total_ticks} resolved={total_resolved}",
                    end="\r",
                )

            # Periodic save
            if time.time() - last_save_time > save_interval:
                save_ticks(data, output_path)
                last_save_time = time.time()
                stats = data["stats"]
                print(
                    f"\n[save] {stats['total_markets']} markets, "
                    f"{stats['resolved']} resolved, "
                    f"{stats['ticks_collected']} ticks "
                    f"(+{markets_resolved_session} resolved this session)"
                )

            time.sleep(interval)

        except Exception as e:
            print(f"\n[error] {e}")
            time.sleep(interval * 2)

    # Final save
    # Check resolution of the last active market
    if last_slug and last_slug in data["markets"] and not data["markets"][last_slug].get("winner"):
        print(f"Checking final market resolution for {last_slug}...")
        time.sleep(2)  # Brief wait for resolution
        prev_data = fetch_market_data(last_slug)
        if prev_data:
            winner = check_resolution(last_slug, prev_data)
            if winner:
                data["markets"][last_slug]["winner"] = winner
                data["markets"][last_slug]["resolved_at"] = int(time.time())
                print(f"  Resolved: {last_slug} -> {winner}")

    save_ticks(data, output_path)
    stats = data["stats"]
    print(f"\n=== Collection Stopped ===")
    print(f"Total: {stats['total_markets']} markets, "
          f"{stats['resolved']} resolved, "
          f"{stats['ticks_collected']} ticks")
    print(f"Saved to: {output_path}")

    # Estimate time to target
    if stats["resolved"] < 500:
        remaining_markets = 500 - stats["resolved"]
        hours_needed = remaining_markets * 5 / 60  # 5 min per market
        print(f"\nNeed ~{remaining_markets} more resolved markets for analysis.")
        print(f"Estimated time: ~{hours_needed:.0f} hours ({hours_needed/24:.1f} days)")


def print_summary(output_path):
    """Print summary of collected data."""
    if not output_path.exists():
        print("No data collected yet.")
        return

    data = load_ticks(output_path)
    markets = data["markets"]
    resolved = {k: v for k, v in markets.items() if v.get("winner")}
    active = {k: v for k, v in markets.items() if not v.get("winner")}

    print(f"\n=== Tick Data Summary ===")
    print(f"Total markets: {len(markets)}")
    print(f"Resolved: {len(resolved)}")
    print(f"Active/Pending: {len(active)}")

    if resolved:
        up_wins = sum(1 for m in resolved.values() if m["winner"] == "Up")
        down_wins = sum(1 for m in resolved.values() if m["winner"] == "Down")
        tick_counts = [len(m.get("ticks", [])) for m in resolved.values()]
        avg_ticks = sum(tick_counts) / len(tick_counts)
        total_ticks = sum(tick_counts)

        print(f"\nUp wins: {up_wins} ({up_wins/len(resolved)*100:.1f}%)")
        print(f"Down wins: {down_wins}")
        print(f"Total ticks: {total_ticks}")
        print(f"Avg ticks/market: {avg_ticks:.0f}")

        # Time range
        timestamps = [m["start_ts"] for m in resolved.values()]
        oldest = datetime.fromtimestamp(min(timestamps), tz=timezone.utc)
        newest = datetime.fromtimestamp(max(timestamps), tz=timezone.utc)
        hours = (max(timestamps) - min(timestamps)) / 3600
        print(f"Range: {oldest.strftime('%Y-%m-%d %H:%M')} to {newest.strftime('%Y-%m-%d %H:%M')} UTC ({hours:.0f}h)")

        # Readiness check
        print(f"\n--- Backtest Readiness ---")
        if len(resolved) >= 500:
            print(f"READY: {len(resolved)} resolved markets (target: 500+)")
            print(f"Run: python backtest/simulate.py --ticks backtest/ticks.json")
        else:
            remaining = 500 - len(resolved)
            hours_left = remaining * 5 / 60
            print(f"NOT READY: {len(resolved)}/500 resolved markets")
            print(f"Need ~{remaining} more (~{hours_left:.0f}h / {hours_left/24:.1f} days)")

    print(f"\nCollection started: {data.get('collection_started', 'unknown')}")
    print(f"Last updated: {data.get('last_updated', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(
        description="Live tick collector for BTC Up/Down 5m markets"
    )
    parser.add_argument(
        "--interval", type=int, default=3,
        help="Seconds between price snapshots (default: 3)"
    )
    parser.add_argument(
        "--output", type=str, default=str(TICKS_FILE_DEFAULT),
        help="Output file path"
    )
    parser.add_argument(
        "--save-interval", type=int, default=30,
        help="Seconds between disk saves (default: 30)"
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Print summary of collected data and exit"
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.summary:
        print_summary(output_path)
        return

    run_collector(
        interval=args.interval,
        output_path=output_path,
        save_interval=args.save_interval,
    )


if __name__ == "__main__":
    main()
