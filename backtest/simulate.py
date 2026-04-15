#!/usr/bin/env python3
"""
Backtest the BTC Up/Down 5m bot strategy against tick data.

Replays the exact bot signal logic against real price ticks captured by
live_collector.py or the --paper mode of the bot.

Usage:
    python backtest/simulate.py
    python backtest/simulate.py --ticks backtest/ticks.json
    python backtest/simulate.py --bet-size 5 --stop-loss 30

Collect tick data first:
    python backtest/live_collector.py
    # or run the bot in paper mode: python poly-cli.py btc-watch-order --paper
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone


def simulate_ticks(markets_dict, bid_prices, min_durations, bet_size, stop_loss_pct=30):
    """
    Replay the actual bot signal against tick data.

    Signal logic: buy the dominant side (Up or Down) when its price stays
    above bid_price for min_duration consecutive seconds.

    Returns results per (bid_price, min_duration) parameter pair.
    """
    # Sort markets by start time
    resolved = [
        m for m in markets_dict.values()
        if m.get("winner") and len(m.get("ticks", [])) >= 5
    ]
    resolved.sort(key=lambda m: m["start_ts"])

    results = {}

    for bp in bid_prices:
        for md in min_durations:
            trades = []

            for market in resolved:
                ticks = market["ticks"]
                winner = market["winner"]
                slug = market["slug"]

                # Simulate the signal: track UP and DOWN independently (matches real bot)
                bought_side = None
                bought_price = None
                up_above_since = None
                down_above_since = None

                for tick in ticks:
                    up = tick["up"]
                    down = tick["down"]
                    t = tick["t"]

                    if bought_side:
                        # Already bought — check stop-loss
                        current_price = up if bought_side == "Up" else down
                        loss_pct = (bought_price - current_price) / bought_price * 100
                        if loss_pct >= stop_loss_pct:
                            trades.append({
                                "slug": slug,
                                "side": bought_side,
                                "entry": bought_price,
                                "exit": current_price,
                                "pnl": (current_price - bought_price) * bet_size,
                                "result": "stop_loss",
                            })
                            bought_side = None
                            break
                        continue

                    # Track UP and DOWN independently
                    should_buy = False
                    buy_side = None

                    if up > bp:
                        if up_above_since is None:
                            up_above_since = t
                        if t - up_above_since >= md:
                            should_buy = True
                            buy_side = "Up"
                    else:
                        up_above_since = None

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
                        bought_price = bp

                # Market resolved — close the position
                if bought_side:
                    won = (bought_side == winner)
                    if won:
                        pnl = (1.0 - bought_price) * bet_size
                    else:
                        pnl = -bought_price * bet_size

                    trades.append({
                        "slug": slug,
                        "side": bought_side,
                        "entry": bought_price,
                        "exit": 1.0 if won else 0.0,
                        "pnl": round(pnl, 4),
                        "result": "win" if won else "loss",
                    })

            # Compute stats for this parameter pair
            if trades:
                wins = [t for t in trades if t["result"] == "win"]
                losses = [t for t in trades if t["result"] == "loss"]
                stops = [t for t in trades if t["result"] == "stop_loss"]
                total_pnl = sum(t["pnl"] for t in trades)
                win_rate = len(wins) / len(trades) * 100 if trades else 0
                breakeven_wr = bp * 100

                # Max drawdown
                peak = 0
                max_dd = 0
                running = 0
                for t in trades:
                    running += t["pnl"]
                    if running > peak:
                        peak = running
                    dd = peak - running
                    if dd > max_dd:
                        max_dd = dd

                # Trade rate (% of markets where signal fired)
                trade_rate = len(trades) / len(resolved) * 100

                results[(bp, md)] = {
                    "bid_price": bp,
                    "min_duration": md,
                    "total_trades": len(trades),
                    "wins": len(wins),
                    "losses": len(losses),
                    "stop_losses": len(stops),
                    "win_rate": round(win_rate, 2),
                    "breakeven_wr": round(breakeven_wr, 1),
                    "edge": round(win_rate - breakeven_wr, 2),
                    "total_pnl": round(total_pnl, 2),
                    "avg_pnl": round(total_pnl / len(trades), 4),
                    "max_drawdown": round(max_dd, 2),
                    "trade_rate": round(trade_rate, 1),
                    "trades": trades,
                }
            else:
                results[(bp, md)] = {
                    "bid_price": bp,
                    "min_duration": md,
                    "total_trades": 0,
                    "win_rate": 0,
                    "edge": 0,
                    "total_pnl": 0,
                    "trades": [],
                }

    return results, len(resolved)


def print_tick_results(results, n_markets):
    """Print tick-based backtest results in a table."""
    print(f"\n{'='*110}")
    print(f"TICK-BASED BACKTEST RESULTS ({n_markets} markets with tick data)")
    print(f"{'='*110}")
    print(f"{'BidPx':>6} {'MinDur':>6} {'Trades':>7} {'Wins':>5} {'Loss':>5} {'SL':>4} "
          f"{'WinRate':>8} {'BrkEvn':>7} {'Edge':>7} {'TotalPnL':>10} {'AvgPnL':>9} "
          f"{'MaxDD':>8} {'Rate%':>6} {'Verdict':>10}")
    print(f"{'-'*110}")

    for key in sorted(results.keys()):
        r = results[key]
        if r["total_trades"] == 0:
            print(f"{r['bid_price']:>6.2f} {r['min_duration']:>6}s {'NO TRADES':>60}")
            continue

        verdict = "PROFIT" if r["total_pnl"] > 0 else "LOSS"
        edge_str = f"{r['edge']:+.1f}%"

        print(f"{r['bid_price']:>6.2f} {r['min_duration']:>6}s {r['total_trades']:>7} "
              f"{r['wins']:>5} {r['losses']:>5} {r['stop_losses']:>4} "
              f"{r['win_rate']:>7.1f}% {r['breakeven_wr']:>6.0f}% {edge_str:>7} "
              f"${r['total_pnl']:>9.2f} ${r['avg_pnl']:>8.4f} "
              f"${r['max_drawdown']:>7.2f} {r['trade_rate']:>5.1f}% {verdict:>10}")


def main():
    parser = argparse.ArgumentParser(description="Backtest BTC Up/Down 5m strategy against tick data")
    parser.add_argument("--ticks", type=str, default=None, help="Tick data file (default: backtest/ticks.json)")
    parser.add_argument("--bet-size", type=float, default=10.0, help="Bet size in USD")
    parser.add_argument("--stop-loss", type=float, default=30.0, help="Stop loss percentage")
    parser.add_argument("--report", type=str, default="backtest/report.json", help="Output report file")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_path = os.path.join(project_root, args.report)

    # Resolve ticks file path
    if args.ticks:
        ticks_path = args.ticks
    else:
        ticks_path = os.path.join(project_root, "backtest", "ticks.json")

    if not os.path.exists(ticks_path):
        print(f"No tick data found at: {ticks_path}")
        print(f"\nCollect data first:")
        print(f"  python backtest/live_collector.py")
        print(f"  # or run the bot in paper mode:")
        print(f"  python poly-cli.py btc-watch-order --paper")
        sys.exit(1)

    print("=== BTC Up/Down 5m Backtest ===")
    print(f"Tick data: {ticks_path}\n")

    with open(ticks_path, "r") as f:
        tick_data = json.load(f)

    markets_dict = tick_data.get("markets", {})
    resolved_ticks = {k: v for k, v in markets_dict.items()
                     if v.get("winner") and len(v.get("ticks", [])) >= 5}

    print(f"Total markets: {len(markets_dict)}")
    print(f"Resolved with ticks: {len(resolved_ticks)}")
    total_ticks = sum(len(m.get("ticks", [])) for m in resolved_ticks.values())
    print(f"Total ticks: {total_ticks}")

    if len(resolved_ticks) < 20:
        print(f"\nNot enough resolved markets ({len(resolved_ticks)} — need 20+ to run, 500+ for reliable results).")
        print("Keep collecting data:")
        print("  python backtest/live_collector.py")
        sys.exit(0)

    if len(resolved_ticks) < 500:
        print(f"\nNote: {len(resolved_ticks)} resolved markets. Results may not be reliable.")
        print(f"Target 500+ for statistical confidence ({500 - len(resolved_ticks)} more needed).\n")

    # Test parameter grid
    bid_prices = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    min_durations = [2, 4, 6, 8, 10, 15, 20]

    results, n_markets = simulate_ticks(
        resolved_ticks, bid_prices, min_durations,
        bet_size=args.bet_size, stop_loss_pct=args.stop_loss,
    )
    print_tick_results(results, n_markets)

    # Find best parameters
    profitable = {k: v for k, v in results.items()
                 if v["total_trades"] > 0 and v["total_pnl"] > 0}

    print(f"\n{'='*60}")
    print(f"VERDICT")
    print(f"{'='*60}")

    if profitable:
        best_key = max(profitable, key=lambda k: profitable[k]["avg_pnl"])
        best = profitable[best_key]
        print(f"\nBest parameters by avg P&L/trade:")
        print(f"  bid_price={best['bid_price']}, min_duration={best['min_duration']}s")
        print(f"  Win rate: {best['win_rate']:.1f}% (breakeven: {best['breakeven_wr']:.0f}%)")
        print(f"  Edge: {best['edge']:+.1f}%")
        print(f"  Total P&L: ${best['total_pnl']:.2f} over {best['total_trades']} trades")
        print(f"  Avg P&L/trade: ${best['avg_pnl']:.4f}")
        print(f"  Max drawdown: ${best['max_drawdown']:.2f}")

        top5 = sorted(profitable.items(), key=lambda x: x[1]["avg_pnl"], reverse=True)[:5]
        print(f"\nTop 5 profitable parameter sets:")
        for _, r in top5:
            print(f"  bp={r['bid_price']:.2f} md={r['min_duration']}s: "
                  f"WR={r['win_rate']:.1f}% edge={r['edge']:+.1f}% "
                  f"PnL=${r['total_pnl']:.2f} ({r['total_trades']} trades)")

        print(f"\n  RECOMMENDATION: Go live with small bets using best parameters.")
        print(f"  Use: python poly-cli.py btc-watch-order "
              f"--bid-price {best['bid_price']} --min-duration {best['min_duration']} "
              f"--bet-size 2.0 --stop-loss {args.stop_loss:.0f}")
    else:
        print(f"\n  NO profitable parameter set found across {len(results)} combinations.")
        print(f"  The current signal has no edge at any threshold.")
        print(f"\n  RECOMMENDATION:")
        print(f"    1. Do NOT trade with the current strategy")
        print(f"    2. Add Binance BTC price feed for cross-exchange signal")
        print(f"    3. The market is efficient — you need an information edge")

    # Save report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "tick_based",
        "data_summary": {
            "total_markets": len(markets_dict),
            "resolved_with_ticks": len(resolved_ticks),
            "total_ticks": total_ticks,
        },
        "results": {f"bp{k[0]}_md{k[1]}": {kk: vv for kk, vv in v.items() if kk != "trades"}
                   for k, v in results.items()},
        "best_params": {
            "bid_price": best["bid_price"],
            "min_duration": best["min_duration"],
            "win_rate": best["win_rate"],
            "edge": best["edge"],
        } if profitable else None,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
