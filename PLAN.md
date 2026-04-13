# Poly-CLI Bot: Implementation Plan & Setup Guide

## Current State

Single-file Python CLI (`poly-cli.py`) that trades BTC Up/Down 5-minute markets on Polymarket.

**Strategy**: Buy the dominant side (Up or Down) when its price stays above a threshold (`bid_price`) for `min_duration` seconds, betting that the trend holds through market resolution.

**Core problem**: At default `bid_price=0.90`, the bot needs >90% win rate to break even. We don't know if the signal achieves that.

---

## Phase 1: Setup & Observe (Day 1)

### Prerequisites
- Python 3.8+
- A Polymarket account with a funded proxy wallet
- Your private key and funder (proxy) address

### Installation
```bash
pip install click py-clob-client web3 requests
```

### Configuration
```bash
# 1. Run setup wizard
python poly-cli.py setup
# Enter: private key, chain_id=137, signature_type=2 (proxy), funder address

# 2. Configure bot settings
python poly-cli.py btc-setup
# Suggested starting values:
#   Bid Price: 0.85
#   Min Duration: 8
#   Bet Size: 2.0
#   Auto Claim: y

# 3. Verify wallet connection
python poly-cli.py wallet-balance

# 4. Watch prices (no trading) - observe for at least 30 minutes
python poly-cli.py btc-watch
```

### Config Reference (config.json)
| Field | Recommended | Why |
|---|---|---|
| `bid_price` | 0.85 | Better risk/reward than 0.90 (risk $0.85 to win $0.15) |
| `bet_size` | 2.0 | Small while testing |
| `min_duration` | 8 | Longer confirmation reduces false signals |
| `stop_loss_percent` | 30 | Cut losses earlier than default 45% |
| `sl_min_duration` | 5 | Seconds before stop-loss executes |
| `time_buffer` | 30 | Skip orders if <30s left in market |
| `markets_before_pause` | 5 | Pause after 5 market rotations |
| `pause_duration_seconds` | 300 | 5-minute cooldown |
| `auto_claim` | true | Auto-collect winnings on-chain |

---

## Phase 2: Backtest (Day 2-3)

**Goal**: Answer "does this strategy have edge?" before risking real money.

### What to build
1. **Data collector** (`backtest/collect.py`)
   - Fetch historical BTC Up/Down 5m markets from Gamma API
   - Store: slug, timestamp, token prices over time, resolution outcome (Up/Down)
   - Target: at least 500-1000 resolved markets

2. **Backtester** (`backtest/simulate.py`)
   - Replay the signal logic against historical data
   - Simulate: would the bot have bought? At what price? Did it win?
   - Test across parameter ranges:
     - `bid_price`: 0.70, 0.75, 0.80, 0.85, 0.90, 0.95
     - `min_duration`: 2, 4, 6, 8, 10, 15
   - Output: win rate, total P&L, max drawdown, Sharpe ratio per parameter set

3. **Report** (`backtest/results.md`)
   - Which parameter combinations are profitable?
   - Is there a clear edge, or is it noise?

### Decision gate
- If **no parameter set** shows >breakeven win rate across 500+ trades -> strategy needs fundamental changes (Phase 4)
- If **some sets** are profitable -> proceed to Phase 3 with those parameters

---

## Phase 3: Live Testing with Small Bets (Day 4-7)

### What to build first (improvements before live trading)

1. **Trade logger** - Save every trade to `trades.json`:
   - timestamp, market slug, side (UP/DOWN), entry price, resolution, P&L
   - This is critical - without data you can't evaluate performance

2. **Fix known bugs**:
   - `title` variable can be undefined on first iteration (line 1055)
   - Duplicate imports inside `btc_watch_order` (lines 705-708)

3. **Replace `subprocess curl` with `requests`** - more reliable

### Run the bot
```bash
# Start with best parameters from backtest
python poly-cli.py btc-watch-order --bid-price 0.85 --bet-size 2.0 --stop-loss 30
```

### Track performance
- Review `trades.json` daily
- Compare live win rate to backtest predictions
- Stop if cumulative loss exceeds $50

---

## Phase 4: Strategy Improvements (After backtest data)

Only pursue these **after** Phase 2 confirms whether the base strategy has edge.

### High-impact improvements
1. **External BTC price signal** - Query Binance/CoinGecko for real BTC momentum. Combine with Polymarket odds for a stronger signal (e.g., only buy UP if BTC price is actually trending up on the exchange)

2. **Dynamic bid pricing** - Instead of fixed `bid_price`, adjust based on market conditions and time remaining

3. **Bankroll management** - Kelly criterion or fixed-fraction sizing based on estimated edge

4. **Multi-timeframe** - If 5m markets don't have edge, test 1m or 15m markets

### Lower-priority improvements
5. Replace plaintext private key with environment variable
6. Add Telegram/Discord notifications for trades
7. Web dashboard for monitoring

---

## Summary: What to do in order

```
1. Setup & observe     (30 min)   - install, configure, watch prices
2. Backtest            (1-2 days) - build data collector + simulator
3. Evaluate results    (1 hour)   - decide if strategy has edge
4. Live test (small)   (3-5 days) - $2 bets, track everything
5. Improve or abandon  (ongoing)  - based on real data, not guessing
```

**The single most important rule: never scale up bet size until you have data proving the strategy works.**
