#!/usr/bin/env python3
"""
Trading journal - logs every trade and provides performance reports.

Used by the bot to track live trades, and standalone to view reports.

Usage:
    # View journal report
    python backtest/journal.py [--file trades.json]
"""

import json
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path


JOURNAL_FILE = Path(__file__).parent.parent / "trades.json"


def load_journal(path=None):
    """Load trades from journal file."""
    filepath = Path(path) if path else JOURNAL_FILE
    if filepath.exists():
        with open(filepath, "r") as f:
            return json.load(f)
    return {"trades": [], "summary": {}}


def save_journal(journal, path=None):
    """Save trades to journal file."""
    filepath = Path(path) if path else JOURNAL_FILE
    with open(filepath, "w") as f:
        json.dump(journal, f, indent=2)


def log_trade(slug, side, entry_price, bet_size, order_id=None, token_id=None, path=None):
    """Log a new trade entry (called when order is placed)."""
    journal = load_journal(path)

    trade = {
        "id": len(journal["trades"]) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "slug": slug,
        "side": side,
        "entry_price": entry_price,
        "bet_size": bet_size,
        "order_id": order_id,
        "token_id": token_id,
        "status": "open",
        "exit_price": None,
        "pnl": None,
        "exit_reason": None,
        "exit_timestamp": None,
    }

    journal["trades"].append(trade)
    save_journal(journal, path)
    return trade["id"]


def close_trade(trade_id, exit_price, exit_reason="resolved", path=None):
    """Close an open trade (called on resolution or stop-loss)."""
    journal = load_journal(path)

    for trade in journal["trades"]:
        if trade["id"] == trade_id and trade["status"] == "open":
            trade["status"] = "closed"
            trade["exit_price"] = exit_price
            trade["exit_reason"] = exit_reason
            trade["exit_timestamp"] = datetime.now(timezone.utc).isoformat()

            # Calculate P&L
            if exit_price >= 0.99:  # Won
                trade["pnl"] = round((1.0 - trade["entry_price"]) * trade["bet_size"], 2)
            elif exit_price <= 0.01:  # Lost
                trade["pnl"] = round(-trade["entry_price"] * trade["bet_size"], 2)
            else:  # Partial (stop-loss)
                trade["pnl"] = round((exit_price - trade["entry_price"]) * trade["bet_size"], 2)

            save_journal(journal, path)
            return trade
    return None


def close_trade_by_slug(slug, exit_price, exit_reason="resolved", path=None):
    """Close the most recent open trade for a given market slug."""
    journal = load_journal(path)

    for trade in reversed(journal["trades"]):
        if trade["slug"] == slug and trade["status"] == "open":
            return close_trade(trade["id"], exit_price, exit_reason, path)
    return None


def get_open_trades(path=None):
    """Get all open trades."""
    journal = load_journal(path)
    return [t for t in journal["trades"] if t["status"] == "open"]


def print_report(path=None):
    """Print a performance report."""
    journal = load_journal(path)
    trades = journal["trades"]

    if not trades:
        print("No trades recorded yet.")
        return

    closed = [t for t in trades if t["status"] == "closed"]
    open_trades = [t for t in trades if t["status"] == "open"]

    print(f"\n{'='*60}")
    print(f"TRADING JOURNAL REPORT")
    print(f"{'='*60}")
    print(f"Total trades: {len(trades)}")
    print(f"Open: {len(open_trades)}")
    print(f"Closed: {len(closed)}")

    if closed:
        wins = [t for t in closed if t.get("pnl", 0) > 0]
        losses = [t for t in closed if t.get("pnl", 0) < 0]
        breakeven = [t for t in closed if t.get("pnl", 0) == 0]

        total_pnl = sum(t.get("pnl", 0) for t in closed)
        win_rate = len(wins) / len(closed) * 100

        print(f"\nWins: {len(wins)}")
        print(f"Losses: {len(losses)}")
        print(f"Breakeven: {len(breakeven)}")
        print(f"Win Rate: {win_rate:.1f}%")
        print(f"Total P&L: ${total_pnl:+.2f}")

        if wins:
            avg_win = sum(t["pnl"] for t in wins) / len(wins)
            print(f"Avg Win: ${avg_win:+.2f}")
        if losses:
            avg_loss = sum(t["pnl"] for t in losses) / len(losses)
            print(f"Avg Loss: ${avg_loss:+.2f}")

        avg_pnl = total_pnl / len(closed)
        print(f"Avg P&L/Trade: ${avg_pnl:+.3f}")

        # Max drawdown
        peak = 0
        max_dd = 0
        running = 0
        for t in closed:
            running += t.get("pnl", 0)
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd
        print(f"Max Drawdown: ${max_dd:.2f}")

        # By side
        print(f"\nBy Side:")
        for side in ["UP", "DOWN"]:
            side_trades = [t for t in closed if t.get("side", "").upper() == side]
            if side_trades:
                side_wins = sum(1 for t in side_trades if t.get("pnl", 0) > 0)
                side_pnl = sum(t.get("pnl", 0) for t in side_trades)
                print(f"  {side}: {len(side_trades)} trades, {side_wins} wins ({side_wins/len(side_trades)*100:.0f}%), P&L: ${side_pnl:+.2f}")

        # By exit reason
        print(f"\nBy Exit Reason:")
        reasons = set(t.get("exit_reason", "unknown") for t in closed)
        for reason in sorted(reasons):
            r_trades = [t for t in closed if t.get("exit_reason") == reason]
            r_pnl = sum(t.get("pnl", 0) for t in r_trades)
            print(f"  {reason}: {len(r_trades)} trades, P&L: ${r_pnl:+.2f}")

        # Recent trades
        print(f"\nRecent Trades (last 10):")
        print(f"  {'TIME':<20} {'SIDE':<5} {'ENTRY':>6} {'EXIT':>6} {'PNL':>8} {'REASON':<10} {'SLUG'}")
        for t in closed[-10:]:
            ts = t.get("timestamp", "")[:19]
            print(f"  {ts:<20} {t.get('side','?'):<5} ${t.get('entry_price',0):.2f} "
                  f"${t.get('exit_price',0):.2f} ${t.get('pnl',0):>+7.2f} "
                  f"{t.get('exit_reason',''):<10} {t.get('slug','')}")

    if open_trades:
        print(f"\nOpen Positions:")
        for t in open_trades:
            print(f"  {t.get('side','?')} @ ${t.get('entry_price',0):.2f} ({t.get('slug','')})")


def main():
    parser = argparse.ArgumentParser(description="Trading journal report")
    parser.add_argument("--file", type=str, default=None, help="Journal file path")
    args = parser.parse_args()

    print_report(args.file)


if __name__ == "__main__":
    main()
