# Polycli - Polymarket Python CLI

A comprehensive command-line interface for interacting with Polymarket, built using `py-clob-client`.

## Features

- **Wallet Management**: Check balances (POL, USDC), view open orders, and trade history.
- **Market Data**: Fetch real-time prices, market details, and volume.
- **BTC Trading Bot**: Automated trading bot for BTC Up/Down 5-minute markets with:
  - Real-time price monitoring
  - Configurable bid thresholds and bet sizes
  - Stop-loss protection
  - Auto-claiming of winning tokens
- **Configuration**: Easy setup wizard for wallet and bot settings.

## Installation

### Prerequisites
- Python 3.8+
- `pip`

### Install Dependencies
```bash
pip install click py-clob-client web3 requests
```

## Configuration

Run the setup wizard to configure your wallet and bot settings:
```bash
python poly-cli.py setup
```

This will create a `config.json` file with the following structure:

```json
{
  "private_key": "YOUR_PRIVATE_KEY",
  "chain_id": 137,
  "signature_type": 2,
  "funder": "YOUR_FUNDER_ADDRESS",
  "host": "https://clob.polymarket.com",
  "rpc": "https://polygon.drpc.org",
  "wallet_address": "YOUR_WALLET_ADDRESS",
  "bot_settings": {
    "check_interval": 60,
    "min_balance": 10,
    "max_bet_size": 100
  },
  "btc_watch_order": {
    "bid_price": 0.9,
    "min_duration": 5,
    "bet_size": 10.0,
    "auto_claim": false
  },
  "stop_loss_percent": 45,
  "time_buffer": 15
}
```

### Configuration Fields
| Field | Description |
|-------|-------------|
| `private_key` | Your wallet's private key (0x...) |
| `chain_id` | Polygon Chain ID (137) |
| `signature_type` | 0=EOA, 1=Magic/Email, 2=Proxy |
| `funder` | Proxy wallet address (if applicable) |
| `host` | Polymarket CLOB API endpoint |
| `rpc` | Polygon RPC endpoint for on-chain data |
| `bid_price` | Price threshold for placing orders |
| `bet_size` | Amount in USD to bet per trade |
| `stop_loss_percent` | Percentage loss to trigger stop-loss sell |

## Usage

### Wallet & Balance
Check your wallet balances and recent trades:
```bash
python poly-cli.py wallet-balance
```

### Market Data
View top markets or specific market prices:
```bash
# Top 10 markets
python poly-cli.py markets

# Specific market by slug
python poly-cli.py markets btc-updown-5m-1698765432
```

### BTC Trading Bot
Run the automated BTC Up/Down trading bot:
```bash
python poly-cli.py btc-watch-order
```

**Options:**
- `--bid-price`: Override bid price threshold
- `--bet-size`: Override bet size in USD
- `--stop-loss`: Override stop-loss percentage

### Setup
Configure your wallet and bot settings:
```bash
python poly-cli.py setup
```

### Show Config
View current configuration (hides private key):
```bash
python poly-cli.py show-config
```

## Disclaimer
⚠️ **Use at your own risk.** This tool interacts with real financial markets. Ensure you understand the risks before using real funds.

## License
MIT
