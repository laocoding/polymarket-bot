#!/usr/bin/env python3
"""
Backtest the BTC Up/Down 5m bot strategy against historical data.

IMPORTANT: The Gamma API only provides post-resolution prices (near $1 or $0),
not mid-market tick data. This means we CANNOT simulate the exact signal logic
("buy when price > threshold for N seconds").

Instead, we use statistical simulation:
- We know the resolution outcome (Up or Down) for each market
- We know the base rate: ~50% Up, ~50% Down
- We model the signal as: "the bot buys the side that will win" X% of the time
- The key question: at a given bid_price, what win rate do you need, and what
  win rate can you realistically expect?

We also provide a Monte Carlo simulation to estimate P&L distributions.

Usage:
    .venv/bin/python3 backtest/simulate.py [--data backtest/data.json]
"""

import json
import os
import sys
import random
import argparse
from datetime import datetime, timezone
from itertools import product


def load_data(path):
    """Load collected market data."""
    with open(path, "r") as f:
        raw = json.load(f)
    return raw["markets"]


def analyze_market_data(markets):
    """Analyze the raw market data for insights."""
    resolved = [m for m in markets if m["winner"]]
    up_wins = sum(1 for m in resolved if m["winner"] == "Up")
    down_wins = sum(1 for m in resolved if m["winner"] == "Down")

    # Look for consecutive runs (momentum)
    consecutive_up = 0
    consecutive_down = 0
    max_up_run = 0
    max_down_run = 0
    runs = []  # (direction, length)
    current_run_dir = None
    current_run_len = 0

    sorted_markets = sorted(resolved, key=lambda m: m["timestamp"])

    for m in sorted_markets:
        if m["winner"] == current_run_dir:
            current_run_len += 1
        else:
            if current_run_dir:
                runs.append((current_run_dir, current_run_len))
            current_run_dir = m["winner"]
            current_run_len = 1

        if m["winner"] == "Up":
            consecutive_up = max(consecutive_up, current_run_len if current_run_dir == "Up" else 0)
        else:
            consecutive_down = max(consecutive_down, current_run_len if current_run_dir == "Down" else 0)

    if current_run_dir:
        runs.append((current_run_dir, current_run_len))

    # Momentum analysis: after an Up win, what's the probability of another Up?
    prev = None
    up_after_up = 0
    down_after_up = 0
    up_after_down = 0
    down_after_down = 0

    for m in sorted_markets:
        if prev:
            if prev == "Up" and m["winner"] == "Up":
                up_after_up += 1
            elif prev == "Up" and m["winner"] == "Down":
                down_after_up += 1
            elif prev == "Down" and m["winner"] == "Up":
                up_after_down += 1
            elif prev == "Down" and m["winner"] == "Down":
                down_after_down += 1
        prev = m["winner"]

    # Streak analysis: after N consecutive same-direction wins, what happens?
    streak_analysis = {}
    for streak_len in [2, 3, 4, 5]:
        continues = 0
        reverses = 0
        for i in range(streak_len, len(sorted_markets)):
            window = [sorted_markets[i-j-1]["winner"] for j in range(streak_len)]
            if len(set(window)) == 1:  # All same direction
                streak_dir = window[0]
                next_dir = sorted_markets[i]["winner"]
                if next_dir == streak_dir:
                    continues += 1
                else:
                    reverses += 1
        total = continues + reverses
        streak_analysis[streak_len] = {
            "continues": continues,
            "reverses": reverses,
            "continuation_rate": continues / total * 100 if total > 0 else 0,
            "total_samples": total,
        }

    # Volume analysis
    volumes = [m["volume"] for m in resolved]

    return {
        "total": len(resolved),
        "up_wins": up_wins,
        "down_wins": down_wins,
        "up_rate": up_wins / len(resolved) * 100,
        "max_up_run": consecutive_up,
        "max_down_run": consecutive_down,
        "avg_run_length": sum(r[1] for r in runs) / len(runs) if runs else 0,
        "momentum": {
            "up_after_up": up_after_up,
            "down_after_up": down_after_up,
            "up_after_down": up_after_down,
            "down_after_down": down_after_down,
            "p_up_given_up": up_after_up / (up_after_up + down_after_up) * 100 if (up_after_up + down_after_up) > 0 else 0,
            "p_down_given_down": down_after_down / (up_after_down + down_after_down) * 100 if (up_after_down + down_after_down) > 0 else 0,
        },
        "streaks": streak_analysis,
        "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
        "median_volume": sorted(volumes)[len(volumes)//2] if volumes else 0,
    }


def monte_carlo_simulation(n_markets, bid_price, bet_size, win_rate, n_simulations=10000):
    """
    Monte Carlo simulation: given a bid_price, bet_size, and assumed win_rate,
    what is the distribution of outcomes over n_markets trades?
    """
    profit_per_win = (1.0 - bid_price) * bet_size
    loss_per_loss = bid_price * bet_size

    final_pnls = []
    max_drawdowns = []
    bust_count = 0  # How many sims went below -50% of initial capital

    initial_capital = bet_size * 10  # Assume 10x bet_size bankroll

    for _ in range(n_simulations):
        pnl = 0
        peak = 0
        max_dd = 0
        busted = False

        for _ in range(n_markets):
            if random.random() < win_rate:
                pnl += profit_per_win
            else:
                pnl -= loss_per_loss

            if pnl > peak:
                peak = pnl
            dd = peak - pnl
            if dd > max_dd:
                max_dd = dd

            if pnl < -initial_capital * 0.5:
                busted = True

        final_pnls.append(pnl)
        max_drawdowns.append(max_dd)
        if busted:
            bust_count += 1

    final_pnls.sort()
    max_drawdowns.sort()

    return {
        "n_simulations": n_simulations,
        "n_markets": n_markets,
        "bid_price": bid_price,
        "bet_size": bet_size,
        "assumed_win_rate": win_rate,
        "mean_pnl": sum(final_pnls) / len(final_pnls),
        "median_pnl": final_pnls[len(final_pnls)//2],
        "pnl_5th_pct": final_pnls[int(len(final_pnls)*0.05)],
        "pnl_95th_pct": final_pnls[int(len(final_pnls)*0.95)],
        "worst_pnl": final_pnls[0],
        "best_pnl": final_pnls[-1],
        "mean_max_dd": sum(max_drawdowns) / len(max_drawdowns),
        "worst_max_dd": max_drawdowns[-1],
        "bust_rate": bust_count / n_simulations * 100,
    }


def print_analysis(analysis):
    """Print market data analysis."""
    print(f"\n{'='*60}")
    print(f"MARKET DATA ANALYSIS ({analysis['total']} resolved markets)")
    print(f"{'='*60}")

    print(f"\nOutcome Distribution:")
    print(f"  Up wins:   {analysis['up_wins']} ({analysis['up_rate']:.1f}%)")
    print(f"  Down wins: {analysis['down_wins']} ({100-analysis['up_rate']:.1f}%)")

    print(f"\nMomentum Analysis:")
    mom = analysis["momentum"]
    print(f"  P(Up | prev=Up):     {mom['p_up_given_up']:.1f}% ({mom['up_after_up']} / {mom['up_after_up']+mom['down_after_up']})")
    print(f"  P(Down | prev=Down): {mom['p_down_given_down']:.1f}% ({mom['down_after_down']} / {mom['up_after_down']+mom['down_after_down']})")
    print(f"  -> {'Momentum exists!' if mom['p_up_given_up'] > 55 else 'No significant momentum (close to 50/50)'}")

    print(f"\nStreak Analysis (after N consecutive same-direction wins):")
    for n, s in analysis["streaks"].items():
        if s["total_samples"] > 0:
            print(f"  After {n} in a row: continues {s['continuation_rate']:.1f}% ({s['continues']}/{s['total_samples']})")

    print(f"\nRun Lengths:")
    print(f"  Max consecutive Up:   {analysis['max_up_run']}")
    print(f"  Max consecutive Down: {analysis['max_down_run']}")
    print(f"  Avg run length:       {analysis['avg_run_length']:.1f}")

    print(f"\nVolume:")
    print(f"  Average:  ${analysis['avg_volume']:,.0f}")
    print(f"  Median:   ${analysis['median_volume']:,.0f}")


def print_monte_carlo(results_by_wr, bid_price, bet_size, n_markets):
    """Print Monte Carlo results table."""
    print(f"\n{'='*100}")
    print(f"MONTE CARLO SIMULATION (bid=${bid_price}, bet=${bet_size}, {n_markets} trades, 10000 sims each)")
    print(f"{'='*100}")
    print(f"{'WR%':>5} {'BreakEven':>10} {'MeanPnL':>10} {'MedianPnL':>10} {'5th%':>10} {'95th%':>10} {'AvgDD':>8} {'WorstDD':>8} {'Bust%':>6} {'Verdict':>10}")
    print(f"{'-'*100}")

    breakeven_wr = bid_price

    for wr, r in sorted(results_by_wr.items()):
        verdict = "PROFIT" if r["mean_pnl"] > 0 else "LOSS"
        edge_sign = "+" if wr > breakeven_wr else "-"

        print(f"{wr*100:>5.0f}% {breakeven_wr*100:>9.0f}% ${r['mean_pnl']:>9.2f} ${r['median_pnl']:>9.2f} "
              f"${r['pnl_5th_pct']:>9.2f} ${r['pnl_95th_pct']:>9.2f} "
              f"${r['mean_max_dd']:>7.2f} ${r['worst_max_dd']:>7.2f} "
              f"{r['bust_rate']:>5.1f}% {verdict:>10}")


def main():
    parser = argparse.ArgumentParser(description="Backtest BTC Up/Down 5m strategy")
    parser.add_argument("--data", type=str, default="backtest/data.json", help="Input data file")
    parser.add_argument("--bet-size", type=float, default=10.0, help="Bet size in USD")
    parser.add_argument("--report", type=str, default="backtest/report.json", help="Output report file")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = os.path.join(project_root, args.data)
    report_path = os.path.join(project_root, args.report)

    if not os.path.exists(data_path):
        print(f"Data file not found: {data_path}")
        print("Run '.venv/bin/python3 backtest/collect.py' first.")
        sys.exit(1)

    print("=== BTC Up/Down 5m Backtest ===")
    markets = load_data(data_path)
    resolved = [m for m in markets if m.get("winner")]

    print(f"Markets loaded: {len(markets)} total, {len(resolved)} resolved")

    # Phase 1: Market Data Analysis
    analysis = analyze_market_data(markets)
    print_analysis(analysis)

    # Phase 2: Mathematical Edge Analysis
    print(f"\n{'='*60}")
    print(f"MATHEMATICAL EDGE ANALYSIS")
    print(f"{'='*60}")

    for bp in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        breakeven = bp * 100
        profit_per_win = (1.0 - bp) * args.bet_size
        loss_per_loss = bp * args.bet_size
        print(f"\n  bid_price=${bp:.2f}:")
        print(f"    Win: +${profit_per_win:.2f}  |  Lose: -${loss_per_loss:.2f}")
        print(f"    Breakeven win rate: {breakeven:.0f}%")
        print(f"    Risk/Reward ratio: {bp/(1-bp):.1f}:1")

        # What if momentum gives us 52% accuracy?
        momentum_wr = analysis["momentum"]["p_up_given_up"] / 100
        if momentum_wr > 0.5:
            expected_pnl = (momentum_wr * profit_per_win) - ((1-momentum_wr) * loss_per_loss)
            print(f"    With {momentum_wr*100:.1f}% momentum WR: expected PnL/trade = ${expected_pnl:+.3f} ({'PROFIT' if expected_pnl > 0 else 'LOSS'})")

    # Phase 3: Monte Carlo Simulation
    n_markets_sim = min(len(resolved), 500)  # Simulate 500 trades

    for bp in [0.70, 0.80, 0.85, 0.90]:
        print(f"\n--- Monte Carlo for bid_price=${bp:.2f} ---")
        win_rates = {}
        for wr_pct in range(50, 100, 5):
            wr = wr_pct / 100
            result = monte_carlo_simulation(
                n_markets=n_markets_sim,
                bid_price=bp,
                bet_size=args.bet_size,
                win_rate=wr,
                n_simulations=10000,
            )
            win_rates[wr] = result

        print_monte_carlo(win_rates, bp, args.bet_size, n_markets_sim)

    # Phase 4: Verdict
    momentum_wr = analysis["momentum"]["p_up_given_up"] / 100
    streak_3_cont = analysis["streaks"].get(3, {}).get("continuation_rate", 50) / 100

    print(f"\n{'='*60}")
    print(f"VERDICT")
    print(f"{'='*60}")
    print(f"\nData-driven findings from {len(resolved)} markets:")
    print(f"  1. Base win rate: {analysis['up_rate']:.1f}% (essentially a coin flip)")
    print(f"  2. Momentum (P(Up|Up)): {analysis['momentum']['p_up_given_up']:.1f}%")
    print(f"  3. After 3-streak continuation: {streak_3_cont*100:.1f}%")
    print(f"  4. Max losing streak: {analysis['max_down_run']} (important for bankroll)")

    if momentum_wr > 0.52:
        print(f"\n  MOMENTUM DETECTED ({momentum_wr*100:.1f}%)")
        for bp in [0.55, 0.60, 0.65, 0.70]:
            expected = (momentum_wr * (1-bp) - (1-momentum_wr) * bp) * args.bet_size
            if expected > 0:
                print(f"    bid_price=${bp:.2f}: expected ${expected:+.3f}/trade -> PROFITABLE")
        print(f"\n  -> Lower bid_price (0.55-0.70) combined with momentum signal may have edge.")
        print(f"     BUT: the bot currently uses 'price > threshold' as signal, not momentum.")
        print(f"     RECOMMENDATION: Add momentum tracking to the signal logic.")
    else:
        print(f"\n  NO SIGNIFICANT MOMENTUM ({momentum_wr*100:.1f}%)")
        print(f"  The market appears efficient at 5-minute intervals.")
        print(f"  The current signal ('price above threshold') has NO statistical edge")
        print(f"  because price reflects the crowd's best guess, which is ~50/50 correct.")
        print(f"\n  RECOMMENDATION:")
        print(f"    1. Do NOT trade with the current strategy as-is")
        print(f"    2. Consider adding external BTC price feed (Binance) for true momentum")
        print(f"    3. Lower bid_price to 0.55-0.65 to improve risk/reward IF you find a signal")

    # Save report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_summary": {
            "total_markets": len(resolved),
            "up_wins": analysis["up_wins"],
            "down_wins": analysis["down_wins"],
            "up_rate_pct": round(analysis["up_rate"], 2),
        },
        "momentum": analysis["momentum"],
        "streaks": analysis["streaks"],
        "verdict": {
            "momentum_wr": round(momentum_wr, 4),
            "has_edge": momentum_wr > 0.52,
            "recommendation": "momentum_signal" if momentum_wr > 0.52 else "do_not_trade",
        },
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
