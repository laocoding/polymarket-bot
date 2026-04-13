#!/usr/bin/env python3
"""
Collect historical BTC Up/Down 5m market data from Gamma API
for backtesting the bot strategy.

Uses paginated search through crypto-tagged markets (the only reliable method
since the Gamma API removes expired 5m markets from direct slug lookups quickly).

Usage:
    .venv/bin/python3 backtest/collect.py [--hours 72] [--output backtest/data.json]
"""

import json
import time
import sys
import os
import argparse
from datetime import datetime, timezone


GAMMA_API = "https://gamma-api.polymarket.com/markets"


def fetch_json_requests(url, retries=2):
    """Fetch JSON using requests library (available in .venv)."""
    import requests
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=15, headers={"Accept-Encoding": "none"})
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.5)
    return None


def parse_json_field(val, default=None):
    """Parse a JSON string field or return as-is if already parsed."""
    if default is None:
        default = []
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return val if val else default


def parse_market(slug, m):
    """Parse raw Gamma API market into clean format."""
    outcome_prices = parse_json_field(m.get("outcomePrices", "[]"))
    outcomes = parse_json_field(m.get("outcomes", "[]"))
    token_ids = parse_json_field(m.get("clobTokenIds", "[]"))

    # Determine winner
    winner = None
    if len(outcome_prices) >= 2:
        try:
            up_final = float(outcome_prices[0])
            down_final = float(outcome_prices[1])
            if up_final >= 0.99:
                winner = "Up"
            elif down_final >= 0.99:
                winner = "Down"
        except (ValueError, TypeError):
            pass

    try:
        market_ts = int(slug.split("-")[-1])
    except ValueError:
        market_ts = 0

    return {
        "slug": slug,
        "timestamp": market_ts,
        "question": m.get("question", ""),
        "end_date": m.get("endDate", ""),
        "closed": m.get("closed", False),
        "closed_time": m.get("closedTime"),
        "outcomes": outcomes,
        "outcome_prices": [float(p) for p in outcome_prices] if outcome_prices else [],
        "winner": winner,
        "last_trade_price": m.get("lastTradePrice"),
        "best_bid": m.get("bestBid"),
        "best_ask": m.get("bestAsk"),
        "volume": float(m.get("volume", 0) or 0),
        "token_ids": token_ids,
        "condition_id": m.get("conditionId", ""),
    }


def collect_markets(max_pages=200):
    """Collect BTC Up/Down 5m markets via paginated crypto tag search."""
    print(f"Paginating through crypto markets (up to {max_pages} pages)...")

    all_btc = {}
    empty_streak = 0

    for page in range(max_pages):
        offset = page * 100
        data = fetch_json_requests(
            f"{GAMMA_API}?tag=crypto&limit=100&offset={offset}"
            f"&closed=true&order=closedTime&ascending=false"
        )

        if not data:
            empty_streak += 1
            if empty_streak >= 3:
                print(f"  3 consecutive empty pages at offset={offset}, stopping.")
                break
            continue

        empty_streak = 0

        btc_found = 0
        for m in data:
            slug = m.get("slug", "")
            if "btc-updown-5m" in slug:
                all_btc[slug] = m
                btc_found += 1

        if btc_found > 0 or page % 20 == 0:
            print(f"  offset={offset}: {len(data)} markets, {btc_found} BTC 5m (total: {len(all_btc)})")

        if len(data) < 100:
            print(f"  Last page at offset={offset} ({len(data)} results)")
            break

        time.sleep(0.15)

    # Also try to get active (not yet resolved) markets for reference
    print(f"\nFetching active markets...")
    for offset in [0, 100, 200]:
        data = fetch_json_requests(
            f"{GAMMA_API}?tag=crypto&limit=100&offset={offset}&active=true&order=endDate&ascending=false"
        )
        if data:
            for m in data:
                slug = m.get("slug", "")
                if "btc-updown-5m" in slug and slug not in all_btc:
                    all_btc[slug] = m
        time.sleep(0.15)

    # Parse all markets
    print(f"\nProcessing {len(all_btc)} markets...")
    results = []
    for slug in sorted(all_btc.keys()):
        results.append(parse_market(slug, all_btc[slug]))

    return results


def main():
    parser = argparse.ArgumentParser(description="Collect BTC Up/Down 5m market data")
    parser.add_argument("--max-pages", type=int, default=200, help="Max pages to scan (default: 200)")
    parser.add_argument("--output", type=str, default="backtest/data.json", help="Output file path")
    args = parser.parse_args()

    print(f"=== BTC Up/Down 5m Data Collector ===\n")

    start_time = time.time()
    results = collect_markets(max_pages=args.max_pages)
    elapsed = time.time() - start_time

    # Stats
    resolved = [r for r in results if r["winner"]]
    active = [r for r in results if not r["winner"]]
    up_wins = sum(1 for r in resolved if r["winner"] == "Up")
    down_wins = sum(1 for r in resolved if r["winner"] == "Down")

    print(f"\n=== Collection Complete ({elapsed:.1f}s) ===")
    print(f"Total markets found: {len(results)}")
    print(f"Resolved: {len(resolved)} (Up: {up_wins}, Down: {down_wins})")
    print(f"Active/Unresolved: {len(active)}")

    if resolved:
        avg_volume = sum(r["volume"] for r in resolved) / len(resolved)
        total_volume = sum(r["volume"] for r in resolved)
        print(f"Avg volume per market: ${avg_volume:,.0f}")
        print(f"Total volume: ${total_volume:,.0f}")
        print(f"Up win rate: {up_wins/len(resolved)*100:.1f}%")

        # Time range
        timestamps = [r["timestamp"] for r in resolved]
        oldest = datetime.fromtimestamp(min(timestamps), tz=timezone.utc)
        newest = datetime.fromtimestamp(max(timestamps), tz=timezone.utc)
        hours_span = (max(timestamps) - min(timestamps)) / 3600
        print(f"Time range: {oldest.strftime('%Y-%m-%d %H:%M')} to {newest.strftime('%Y-%m-%d %H:%M')} UTC ({hours_span:.0f}h)")

    # Save
    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump({
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "total_markets": len(results),
            "resolved_markets": len(resolved),
            "markets": results,
        }, f, indent=2)

    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
