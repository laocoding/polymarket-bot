# Polycli

Python CLI for Polymarket using py-clob-client.

## Installation

```bash
pip install py-clob-client click
```

## Usage

```bash
# Setup configuration (first time)
python3 main.py setup

# Check wallet balance
python3 main.py wallet-balance

# Start bot
python3 main.py start-bot

# Stop bot
python3 main.py stop-bot

# Check bot status
python3 main.py bot-status

# Show config
python3 main.py show-config
```

## Config (config.json)

```json
{
  "private_key": "0x...",
  "chain_id": 137,
  "signature_type": 0,
  "funder": "",
  "wallet_address": "0x...",
  "bot_settings": {
    "enabled": false,
    "check_interval": 60,
    "min_balance": 10,
    "max_bet_size": 100
  }
}
```

## Signature Types

| Value | Type |
|-------|------|
| 0 | EOA (MetaMask, hardware wallet) |
| 1 | Email/Magic wallet |
| 2 | Browser wallet proxy |

## Requirements

- Python 3.9+
- py-clob-client
- click
