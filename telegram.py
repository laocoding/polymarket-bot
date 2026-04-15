"""Telegram notification module for Polymarket bot."""

import requests
import threading
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


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
        cost = entry_price * bet_size
        lines.append(f"Cost: ${cost:.2f} ({bet_size:.1f} tokens)")
        if filled_size is not None:
            lines.append(f"Filled: {filled_size}")
        lines.append(f"Time left: {time_remaining}s")
        self.send("\n".join(lines))

    def trade_closed_resolved(self, trade_id, slug, side, entry_price, exit_price, pnl, won, bet_size=None, suffix=""):
        emoji = "🎉" if won else "💸"
        result = "WON" if won else "LOST"
        reason = f"Resolved{f' ({suffix})' if suffix else ''}"
        lines = [
            f"{emoji} <b>Trade Closed</b> — {result}",
            f"Trade ID: <b>#{trade_id}</b>",
            f"Market: <code>{slug}</code>",
            f"Side: <b>{side}</b>",
            f"Entry: ${entry_price:.3f} → Exit: ${exit_price:.1f}",
        ]
        if bet_size is not None:
            cost = entry_price * bet_size
            revenue = exit_price * bet_size
            lines.append(f"Cost: ${cost:.2f} → Returned: ${revenue:.2f}")
        lines.append(f"P&L: <b>${pnl:+.2f}</b>")
        lines.append(f"Reason: {reason}")
        self.send("\n".join(lines))

    def trade_closed_unresolved(self, trade_id, slug, side, entry_price):
        self.send(
            f"⚠️ <b>Trade Closed</b> — Unresolved\n"
            f"Trade ID: <b>#{trade_id}</b>\n"
            f"Market: <code>{slug}</code>\n"
            f"Side: <b>{side}</b>\n"
            f"Entry: ${entry_price:.3f} → Exit: $0.50\n"
            f"Reason: Could not resolve after ~25 min"
        )

    def trade_closed_stop_loss(self, slug, side, entry_price, exit_price, loss_pct, pnl, mode, trade_id=None, bet_size=None):
        lines = [f"🛑 <b>Trade Closed</b> — Stop Loss ({mode})"]
        if trade_id:
            lines.append(f"Trade ID: <b>#{trade_id}</b>")
        lines.append(f"Market: <code>{slug}</code>")
        lines.append(f"Side: <b>{side}</b>")
        lines.append(f"Entry: ${entry_price:.3f} → Exit: ${exit_price:.3f}")
        if bet_size is not None:
            cost = entry_price * bet_size
            revenue = exit_price * bet_size
            lines.append(f"Cost: ${cost:.2f} → Returned: ${revenue:.2f}")
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

        total_cost = sum(t.get("cost", t.get("entry_price", 0) * t.get("bet_size", 0)) for t in closed)
        total_revenue = sum(t.get("revenue", t.get("exit_price", 0) * t.get("bet_size", 0)) for t in closed)

        lines = [f"📊 <b>{period_label} Summary</b>", ""]
        lines.append(f"Total: {len(trades)} trades ({len(closed)} closed, {len(open_trades)} open)")
        lines.append(f"Wins: {len(wins)} | Losses: {len(losses)} | Even: {len(breakeven)}")
        lines.append(f"Win Rate: <b>{win_rate:.1f}%</b>")
        lines.append(f"Invested: ${total_cost:.2f} → Returned: ${total_revenue:.2f}")
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
                t_cost = t.get("cost", t.get("entry_price", 0) * t.get("bet_size", 0))
                t_rev = t.get("revenue", t.get("exit_price", 0) * t.get("bet_size", 0))
                lines.append(
                    f"  #{t['id']} {result} {t['side']} "
                    f"${t_cost:.2f}→${t_rev:.2f} "
                    f"P&L ${t.get('pnl', 0):+.2f}"
                )

        self.send("\n".join(lines))


class TelegramCommandHandler:
    """Listens for Telegram bot commands via long polling and responds."""

    def __init__(self, notifier: TelegramNotifier, trades_file: Path, bid_price: float = 0.6):
        self.notifier = notifier
        self.trades_file = trades_file
        self.bid_price = bid_price
        self._offset = 0
        self._running = False
        self._thread = None
        self._extra_trades = []  # in-memory trades not yet saved to file

    def set_live_trades(self, trades_list):
        """Point to the in-memory trades list for up-to-date data."""
        self._extra_trades = trades_list

    def _load_trades(self):
        all_trades = list(self._extra_trades)
        try:
            if self.trades_file.exists():
                with open(self.trades_file, 'r') as f:
                    saved = json.load(f).get("trades", [])
                mem_ids = {t["id"] for t in all_trades}
                for t in saved:
                    if t["id"] not in mem_ids:
                        all_trades.append(t)
        except Exception:
            pass
        return all_trades

    def _handle_command(self, text):
        text = text.strip().lower()
        if text in ("/summary", "/today"):
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            all_trades = self._load_trades()
            today_trades = [t for t in all_trades if t.get("timestamp", "")[:10] == today_str]
            self.notifier.trade_summary(today_trades, f"Today ({today_str})", bid_price=self.bid_price)
        elif text == "/stats":
            all_trades = self._load_trades()
            self.notifier.trade_summary(all_trades, "All Time", bid_price=self.bid_price)
        elif text == "/open":
            all_trades = self._load_trades()
            open_trades = [t for t in all_trades if t.get("status") == "open"]
            if not open_trades:
                self.notifier.send("No open trades.")
            else:
                lines = [f"📂 <b>Open Trades ({len(open_trades)})</b>", ""]
                for t in open_trades:
                    lines.append(
                        f"  #{t['id']} {t['side']} <code>{t['slug']}</code> "
                        f"@ ${t['entry_price']:.3f}"
                    )
                self.notifier.send("\n".join(lines))
        elif text == "/help":
            self.notifier.send(
                "🤖 <b>Bot Commands</b>\n\n"
                "/summary — Today's trade summary\n"
                "/stats — All-time trade summary\n"
                "/open — List open trades\n"
                "/help — Show this help"
            )

    def _poll_loop(self):
        url = f"https://api.telegram.org/bot{self.notifier.bot_token}/getUpdates"
        while self._running:
            try:
                resp = requests.get(url, params={
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": '["message"]',
                }, timeout=35)
                if not resp.ok:
                    time.sleep(5)
                    continue
                updates = resp.json().get("result", [])
                for update in updates:
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text = msg.get("text", "")
                    if chat_id == self.notifier.chat_id and text.startswith("/"):
                        self._handle_command(text)
            except Exception:
                time.sleep(5)

    def start(self):
        if not self.notifier.enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
