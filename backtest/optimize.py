#!/usr/bin/env python3
"""
Parameter optimizer for BTC Up/Down 5m strategy.

Runs a full grid search over bid_price, min_duration, stop_loss, and
time-of-entry parameters against collected tick data. Ranks results by
risk-adjusted dollar P&L.

Usage:
    python backtest/optimize.py
    python backtest/optimize.py --ticks backtest/ticks.json --bet-size 2
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone


def load_markets(ticks_path):
    """Load and filter resolved markets from ticks.json."""
    with open(ticks_path) as f:
        data = json.load(f)

    markets = data.get("markets", {})
    resolved = [
        m for m in markets.values()
        if m.get("winner") and len(m.get("ticks", [])) >= 5 and m.get("start_ts")
    ]
    resolved.sort(key=lambda m: m["start_ts"])
    return resolved


def simulate(markets, bp, md, bet_size, stop_loss_pct, min_time_left):
    """
    Simulate the base strategy for one parameter set.

    Returns a list of trade dicts with full detail.
    """
    trades = []

    for market in markets:
        ticks = market["ticks"]
        winner = market["winner"]
        start_ts = market["start_ts"]
        end_ts = start_ts + 300  # 5-minute market

        bought_side = None
        bought_price = None
        up_above_since = None
        down_above_since = None

        for tick in ticks:
            up = tick["up"]
            down = tick["down"]
            t = tick["t"]
            time_remaining = end_ts - t

            if bought_side:
                # Check stop loss
                if stop_loss_pct > 0:
                    current_price = up if bought_side == "Up" else down
                    loss_pct = (bought_price - current_price) / bought_price * 100
                    if loss_pct >= stop_loss_pct:
                        pnl = (current_price - bought_price) * bet_size
                        trades.append({
                            "slug": market["slug"],
                            "side": bought_side,
                            "entry": bought_price,
                            "exit": current_price,
                            "pnl": round(pnl, 4),
                            "result": "stop_loss",
                            "time_left_at_entry": entry_time_left,
                        })
                        bought_side = None
                        break
                continue

            # Skip if not enough time left
            if time_remaining < min_time_left:
                continue

            # Track UP and DOWN independently (matches real bot logic)
            should_buy = False
            buy_side = None

            # Up price > bid_price for min_duration seconds
            if up > bp:
                if up_above_since is None:
                    up_above_since = t
                if t - up_above_since >= md:
                    should_buy = True
                    buy_side = "Up"
            else:
                up_above_since = None

            # Down price > bid_price for min_duration seconds
            if down > bp:
                if down_above_since is None:
                    down_above_since = t
                if t - down_above_since >= md and not should_buy:
                    should_buy = True
                    buy_side = "Down"
            else:
                down_above_since = None

            if should_buy and buy_side:
                bought_side = buy_side
                bought_price = bp  # fixed limit price, matching real bot
                entry_time_left = time_remaining

        # Market resolved — close position
        if bought_side:
            won = bought_side == winner
            if won:
                pnl = (1.0 - bought_price) * bet_size
            else:
                pnl = -bought_price * bet_size

            trades.append({
                "slug": market["slug"],
                "side": bought_side,
                "entry": bought_price,
                "exit": 1.0 if won else 0.0,
                "pnl": round(pnl, 4),
                "result": "win" if won else "loss",
                "time_left_at_entry": entry_time_left,
            })

    return trades


def compute_stats(trades, n_markets, bet_size):
    """Compute performance statistics from a list of trades."""
    if not trades:
        return None

    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]
    stops = [t for t in trades if t["result"] == "stop_loss"]

    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = len(wins) / len(trades) * 100

    # Max drawdown & streak tracking
    peak = 0
    max_dd = 0
    running = 0
    streak = 0
    max_loss_streak = 0
    max_win_streak = 0
    current_streak_type = None

    for t in trades:
        running += t["pnl"]
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

        # Streak
        is_win = t["pnl"] > 0
        if current_streak_type == is_win:
            streak += 1
        else:
            streak = 1
            current_streak_type = is_win

        if is_win:
            max_win_streak = max(max_win_streak, streak)
        else:
            max_loss_streak = max(max_loss_streak, streak)

    # Profit factor
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Avg time left at entry
    time_lefts = [t["time_left_at_entry"] for t in trades if "time_left_at_entry" in t]
    avg_time_left = sum(time_lefts) / len(time_lefts) if time_lefts else 0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "stop_losses": len(stops),
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(trades), 4),
        "max_drawdown": round(max_dd, 2),
        "peak_equity": round(peak, 2),
        "profit_factor": round(profit_factor, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "trade_rate": round(len(trades) / n_markets * 100, 1),
        "avg_time_left": round(avg_time_left),
    }


def run_grid(markets, bet_size):
    """Run full parameter grid and return ranked results."""
    bid_prices = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    min_durations = [2, 4, 6, 8, 10, 14, 20]
    stop_losses = [0, 20, 30, 50]
    min_time_lefts = [15, 30, 60, 90]

    results = []
    n_markets = len(markets)

    total = len(bid_prices) * len(min_durations) * len(stop_losses) * len(min_time_lefts)
    i = 0

    for bp in bid_prices:
        for md in min_durations:
            for sl in stop_losses:
                for mtl in min_time_lefts:
                    i += 1
                    trades = simulate(markets, bp, md, bet_size, sl, mtl)
                    stats = compute_stats(trades, n_markets, bet_size)

                    if stats and stats["total_trades"] >= 5:
                        stats["bid_price"] = bp
                        stats["min_duration"] = md
                        stats["stop_loss"] = sl
                        stats["min_time_left"] = mtl
                        results.append(stats)

    return results


def print_results(results, n_markets, bet_size):
    """Print ranked optimization results."""
    # Primary ranking: avg P&L per trade (risk-adjusted profitability)
    results.sort(key=lambda r: r["avg_pnl"], reverse=True)

    print(f"\n{'=' * 120}")
    print(f"PARAMETER OPTIMIZATION RESULTS ({n_markets} markets, ${bet_size} bet)")
    print(f"{'=' * 120}")

    # Top 20 by avg P&L
    print(f"\n--- TOP 20 by Avg P&L/Trade ---")
    print(f"{'Rank':>4} {'BP':>5} {'MD':>4} {'SL':>4} {'MTL':>4} "
          f"{'Trades':>6} {'WR%':>6} {'PnL':>8} {'AvgPnL':>8} "
          f"{'MaxDD':>7} {'PF':>5} {'WStrk':>5} {'LStrk':>5} {'AvgTL':>5}")
    print(f"{'-' * 120}")

    for i, r in enumerate(results[:20], 1):
        print(f"{i:>4} {r['bid_price']:>5.2f} {r['min_duration']:>4}s {r['stop_loss']:>3}% {r['min_time_left']:>4}s "
              f"{r['total_trades']:>6} {r['win_rate']:>5.1f}% ${r['total_pnl']:>7.2f} ${r['avg_pnl']:>7.4f} "
              f"${r['max_drawdown']:>6.2f} {r['profit_factor']:>5.1f} {r['max_win_streak']:>5} {r['max_loss_streak']:>5} {r['avg_time_left']:>4}s")

    # Top 10 by total P&L (for volume players)
    by_total = sorted(results, key=lambda r: r["total_pnl"], reverse=True)
    print(f"\n--- TOP 10 by Total P&L ---")
    print(f"{'Rank':>4} {'BP':>5} {'MD':>4} {'SL':>4} {'MTL':>4} "
          f"{'Trades':>6} {'WR%':>6} {'PnL':>8} {'AvgPnL':>8} "
          f"{'MaxDD':>7} {'PF':>5}")
    print(f"{'-' * 90}")

    for i, r in enumerate(by_total[:10], 1):
        print(f"{i:>4} {r['bid_price']:>5.2f} {r['min_duration']:>4}s {r['stop_loss']:>3}% {r['min_time_left']:>4}s "
              f"{r['total_trades']:>6} {r['win_rate']:>5.1f}% ${r['total_pnl']:>7.2f} ${r['avg_pnl']:>7.4f} "
              f"${r['max_drawdown']:>6.2f} {r['profit_factor']:>5.1f}")

    # Top 10 by lowest max drawdown (for conservative players)
    profitable = [r for r in results if r["total_pnl"] > 0]
    if profitable:
        by_dd = sorted(profitable, key=lambda r: r["max_drawdown"])
        print(f"\n--- TOP 10 Lowest Drawdown (profitable only) ---")
        print(f"{'Rank':>4} {'BP':>5} {'MD':>4} {'SL':>4} {'MTL':>4} "
              f"{'Trades':>6} {'WR%':>6} {'PnL':>8} {'AvgPnL':>8} "
              f"{'MaxDD':>7} {'PF':>5} {'LStrk':>5}")
        print(f"{'-' * 95}")

        for i, r in enumerate(by_dd[:10], 1):
            print(f"{i:>4} {r['bid_price']:>5.2f} {r['min_duration']:>4}s {r['stop_loss']:>3}% {r['min_time_left']:>4}s "
                  f"{r['total_trades']:>6} {r['win_rate']:>5.1f}% ${r['total_pnl']:>7.2f} ${r['avg_pnl']:>7.4f} "
                  f"${r['max_drawdown']:>6.2f} {r['profit_factor']:>5.1f} {r['max_loss_streak']:>5}")

    # Current config comparison
    print(f"\n--- YOUR CURRENT CONFIG (bp=0.60, md=8s, sl=0%, mtl=15s) ---")
    current = [r for r in results
               if r["bid_price"] == 0.60 and r["min_duration"] == 8
               and r["stop_loss"] == 0 and r["min_time_left"] == 15]
    if current:
        c = current[0]
        rank = next(i for i, r in enumerate(results, 1)
                    if r["bid_price"] == c["bid_price"] and r["min_duration"] == c["min_duration"]
                    and r["stop_loss"] == c["stop_loss"] and r["min_time_left"] == c["min_time_left"])
        print(f"  Rank: #{rank}/{len(results)}")
        print(f"  Trades: {c['total_trades']}, WR: {c['win_rate']:.1f}%")
        print(f"  Total P&L: ${c['total_pnl']:.2f}, Avg: ${c['avg_pnl']:.4f}")
        print(f"  Max DD: ${c['max_drawdown']:.2f}, Profit Factor: {c['profit_factor']:.1f}")

    # Recommendation
    best = results[0]
    print(f"\n{'=' * 120}")
    print(f"RECOMMENDATION")
    print(f"{'=' * 120}")
    print(f"  Best parameters (by avg P&L/trade):")
    print(f"    bid_price:     {best['bid_price']}")
    print(f"    min_duration:  {best['min_duration']}s")
    print(f"    stop_loss:     {best['stop_loss']}%")
    print(f"    min_time_left: {best['min_time_left']}s")
    print(f"")
    print(f"  Expected performance:")
    print(f"    Win rate:      {best['win_rate']:.1f}%")
    print(f"    Avg P&L:       ${best['avg_pnl']:.4f}/trade")
    print(f"    Total P&L:     ${best['total_pnl']:.2f} over {best['total_trades']} trades")
    print(f"    Max drawdown:  ${best['max_drawdown']:.2f}")
    print(f"    Profit factor: {best['profit_factor']:.1f}")
    print(f"    Max loss streak: {best['max_loss_streak']}")
    print(f"")
    print(f"  Config update:")
    print(f"    python poly-cli.py btc-watch-order "
          f"--bid-price {best['bid_price']} --min-duration {best['min_duration']} "
          f"--bet-size {bet_size} --stop-loss {best['stop_loss']}")

    if current:
        c = current[0]
        improvement = best["avg_pnl"] - c["avg_pnl"]
        print(f"\n  vs current config: ${improvement:+.4f}/trade ({improvement/c['avg_pnl']*100:+.0f}%)")

    # Warning about sample size
    print(f"\n  WARNING: Based on {n_markets} markets. Collect 200+ for higher confidence.")

    return results


def main():
    parser = argparse.ArgumentParser(description="Optimize BTC Up/Down 5m strategy parameters")
    parser.add_argument("--ticks", type=str, default=None, help="Tick data file")
    parser.add_argument("--bet-size", type=float, default=2.0, help="Bet size in USD")
    parser.add_argument("--report", type=str, default="backtest/optimize_report.json", help="Output report file")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.ticks:
        ticks_path = args.ticks
    else:
        ticks_path = os.path.join(project_root, "backtest", "ticks.json")

    if not os.path.exists(ticks_path):
        print(f"No tick data at: {ticks_path}")
        print("Collect data first: python poly-cli.py btc-watch-order --paper")
        sys.exit(1)

    markets = load_markets(ticks_path)
    print(f"Loaded {len(markets)} resolved markets from {ticks_path}")

    if len(markets) < 20:
        print(f"Need at least 20 markets (have {len(markets)}). Keep collecting.")
        sys.exit(0)

    print(f"Running parameter grid search...")
    results = run_grid(markets, args.bet_size)
    print(f"Tested {len(results)} parameter combinations with 5+ trades")

    ranked = print_results(results, len(markets), args.bet_size)

    # Save report
    report_path = os.path.join(project_root, args.report)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_markets": len(markets),
        "bet_size": args.bet_size,
        "top_20": ranked[:20],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
