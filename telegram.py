"""Telegram notification module for Polymarket bot."""

import requests
from datetime import datetime, timezone, timedelta


class TelegramNotifier:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)

    def send(self, message):
        """Send a Telegram message. Fails silently to not disrupt trading."""
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }, timeout=5)
            return resp.ok
        except Exception:
            return False

    def signal_found(self, slug, side, up_price, down_price, duration, bid_price, time_remaining, mode):
        self.send(
            f"🎯 <b>Signal Found</b>\n"
            f"Market: <code>{slug}</code>\n"
            f"Side: <b>{side}</b>\n"
            f"Price: Up ${up_price:.3f} / Down ${down_price:.3f}\n"
            f"Duration: {duration}s above ${bid_price}\n"
            f"Time left: {time_remaining}s\n"
            f"Mode: {mode}"
        )

    def trade_placed(self, trade_id, slug, side, entry_price, bet_size, time_remaining, mode, order_id=None, filled_size=None):
        lines = [f"{'📝' if mode == 'Paper' else '✅'} <b>Trade Placed</b> ({mode})"]
        if order_id:
            lines.append(f"Order ID: <code>{order_id}</code>")
        if trade_id is not None:
            lines.append(f"Trade ID: <b>#{trade_id}</b>")
        lines.append(f"Market: <code>{slug}</code>")
        lines.append(f"Side: <b>{side}</b>")
        lines.append(f"Entry: ${entry_price:.3f}")
        size_str = f"${bet_size:.2f}"
        if filled_size is not None:
            size_str += f" (filled: {filled_size})"
        lines.append(f"Size: {size_str}")
        lines.append(f"Time left: {time_remaining}s")
        self.send("\n".join(lines))

    def trade_closed_resolved(self, trade_id, slug, side, entry_price, exit_price, pnl, won, suffix=""):
        emoji = "🎉" if won else "💸"
        result = "WON" if won else "LOST"
        reason = f"Resolved{f' ({suffix})' if suffix else ''}"
        self.send(
            f"{emoji} <b>Trade Closed</b> — {result}\n"
            f"Trade ID: <b>#{trade_id}</b>\n"
            f"Market: <code>{slug}</code>\n"
            f"Side: <b>{side}</b>\n"
            f"Entry: ${entry_price:.3f} → Exit: ${exit_price:.1f}\n"
            f"P&L: <b>${pnl:+.2f}</b>\n"
            f"Reason: {reason}"
        )

    def trade_closed_unresolved(self, trade_id, slug, side, entry_price):
        self.send(
            f"⚠️ <b>Trade Closed</b> — Unresolved\n"
            f"Trade ID: <b>#{trade_id}</b>\n"
            f"Market: <code>{slug}</code>\n"
            f"Side: <b>{side}</b>\n"
            f"Entry: ${entry_price:.3f} → Exit: $0.50\n"
            f"Reason: Could not resolve after ~25 min"
        )

    def trade_closed_stop_loss(self, slug, side, entry_price, exit_price, loss_pct, pnl, mode, trade_id=None):
        lines = [f"🛑 <b>Trade Closed</b> — Stop Loss ({mode})"]
        if trade_id:
            lines.append(f"Trade ID: <b>#{trade_id}</b>")
        lines.append(f"Market: <code>{slug}</code>")
        lines.append(f"Side: <b>{side}</b>")
        lines.append(f"Entry: ${entry_price:.3f} → Exit: ${exit_price:.3f}")
        lines.append(f"Loss: {loss_pct:.1f}%")
        lines.append(f"P&L: <b>${pnl:+.2f}</b>")
        self.send("\n".join(lines))

    def trade_summary(self, trades, period_label, bid_price=None):
        """Build and send a trade summary for the given period."""
        if not trades:
            self.send(f"📊 <b>{period_label} Summary</b>\n\nNo trades in this period.")
            return

        closed = [t for t in trades if t["status"] == "closed"]
        open_trades = [t for t in trades if t["status"] == "open"]
        wins = [t for t in closed if (t.get("pnl") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl") or 0) < 0]
        breakeven = [t for t in closed if (t.get("pnl") or 0) == 0]
        total_pnl = sum(t.get("pnl", 0) for t in closed)
        win_rate = len(wins) / len(closed) * 100 if closed else 0

        lines = [f"📊 <b>{period_label} Summary</b>", ""]
        lines.append(f"Total: {len(trades)} trades ({len(closed)} closed, {len(open_trades)} open)")
        lines.append(f"Wins: {len(wins)} | Losses: {len(losses)} | Even: {len(breakeven)}")
        lines.append(f"Win Rate: <b>{win_rate:.1f}%</b>")
        lines.append(f"Total P&L: <b>${total_pnl:+.2f}</b>")

        if wins:
            avg_win = sum(t["pnl"] for t in wins) / len(wins)
            lines.append(f"Avg Win: ${avg_win:+.2f}")
        if losses:
            avg_loss = sum(t["pnl"] for t in losses) / len(losses)
            lines.append(f"Avg Loss: ${avg_loss:+.2f}")

        if bid_price and closed:
            breakeven_wr = bid_price * 100
            edge = win_rate - breakeven_wr
            edge_str = f"+{edge:.1f}% PROFITABLE" if edge > 0 else f"{edge:.1f}% NOT profitable"
            lines.append(f"\nBreakeven WR: {breakeven_wr:.0f}% | Edge: {edge_str}")

        # Last 5 trades
        if closed:
            lines.append("")
            lines.append("Recent trades:")
            for t in closed[-5:]:
                result = "W" if (t.get("pnl") or 0) > 0 else "L"
                lines.append(
                    f"  #{t['id']} {result} {t['side']} "
                    f"${t['entry_price']:.2f}→${t.get('exit_price', 0):.2f} "
                    f"P&L ${t.get('pnl', 0):+.2f}"
                )

        self.send("\n".join(lines))
