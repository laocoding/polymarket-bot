#!/usr/bin/env python3
"""
Polycli - Polymarket Python CLI
Main entry point using py-clob-client
"""

import click
import json
import os
import sys
import requests
from pathlib import Path
from eth_account import Account

CONFIG_FILE = Path(__file__).parent / "config.json"

# Default config
DEFAULT_CONFIG = {
    "private_key": "",
    "chain_id": 137,
    "signature_type": 0,
    "funder": "",
    "host": "https://clob.polymarket.com",
    "rpc": "https://polygon.drpc.org",
    "wallet_address": "",
    "bot_settings": {
        "enabled": False,
        "check_interval": 60,
        "min_balance": 10,
        "max_bet_size": 100
    }
}

def load_config():
    """Load config from file"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save config to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_wallet_address(private_key):
    """Derive wallet address from private key"""
    try:
        acct = Account.from_key(private_key)
        return acct.address
    except:
        return "Invalid key"

# Contract addresses
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# CTF ABI for redeem
CTF_REDEEM_ABI = '''
[{"inputs":[{"name":"collateralToken","type":"address"},{"name":"parentCollectionId","type":"bytes32"},{"name":"conditionId","type":"bytes32"},{"name":"indexSets","type":"uint256[]"}],"name":"redeemPositions","outputs":[{"name":"","type":"uint256"}],"state":"nonpayable","type":"function"}]
'''

def auto_claim_tokens(condition_id, wallet_address, rpc_url, private_key):
    """Auto-claim winning tokens using web3"""
    try:
        from web3 import Web3
        
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            return {"success": False, "error": "Not connected to RPC"}
        
        # Get account
        account = w3.eth.account.from_key(private_key)
        
        # Full ABI for CTF contract redeem function
        ctf_abi = [
            {"inputs":[{"name":"collateralToken","type":"address"},{"name":"parentCollectionId","type":"bytes32"},{"name":"conditionId","type":"bytes32"},{"name":"indexSets","type":"uint256[]"}],"name":"redeemPositions","outputs":[],"state":"nonpayable","type":"function"}
        ]
        
        contract = w3.eth.contract(address=CTF_ADDRESS, abi=ctf_abi)
        
        # Build transaction - use web3 v7 style
        parent_collection = bytes(32)
        index_sets = [1, 2]
        
        # Build the transaction using the contract function
        tx = contract.functions.redeemPositions(
            USDC_ADDRESS,
            parent_collection,
            condition_id,
            index_sets
        ).build_transaction({
            'from': wallet_address,
            'nonce': w3.eth.get_transaction_count(wallet_address),
            'gas': 200000,
            'gasPrice': w3.eth.gas_price,
            'chainId': 137
        })
        
        # Sign and send
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        return {
            "success": True,
            "tx_hash": tx_hash.hex(),
            "block_number": receipt.blockNumber
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@click.group()
def cli():
    """Polycli - Polymarket Python CLI"""
    pass

@cli.command()
def wallet_balance():
    """Check wallet balance"""
    config = load_config()
    
    if not config.get("private_key"):
        click.echo("❌ No private key configured. Run 'polycli setup' first.")
        return
    
    wallet_addr = config.get("wallet_address", "")
    if not wallet_addr:
        wallet_addr = get_wallet_address(config["private_key"])
    
    click.echo(f"🔹 Wallet Address: {wallet_addr}")
    click.echo(f"🔗 Chain ID: {config.get('chain_id', 137)}")
    click.echo(f"🔐 Signature Type: {config.get('signature_type', 0)}")
    click.echo(f"📍 Funder: {config.get('funder', 'N/A')}")
    click.echo("")
    
    try:
        from py_clob_client.client import ClobClient
        
        client = ClobClient(
            config.get("host", "https://clob.polymarket.com"),
            key=config["private_key"],
            chain_id=config.get("chain_id", 137),
            signature_type=config.get("signature_type", 0),
            funder=config.get("funder", "")
        )
        
        # Create API creds if needed
        try:
            creds = client.create_or_derive_api_creds()
            client.set_api_creds(creds)
        except:
            pass
        
        # Get collateral address
        col_addr = client.get_collateral_address()
        click.echo(f"💵 USDC Contract: {col_addr}")
        
        # Get orders
        orders = client.get_orders()
        click.echo(f"📋 Open Orders: {len(orders)}")
        
        # Get trades
        trades = client.get_trades()
        click.echo(f"💱 Total Trades: {len(trades)}")
        
        if trades:
            click.echo("\n📊 Recent Trades:")
            # Get market names
            market_cache = {}
            for t in trades[:20]:
                mid = t.get("market", "")
                if mid and mid not in market_cache:
                    try:
                        market = client.get_market(mid)
                        # Get full market name without truncation
                        market_cache[mid] = market.get("question", "Unknown")
                    except:
                        market_cache[mid] = "Unknown"
            
            for t in trades[:10]:
                side = "🟢 BUY" if t.get("side") == "BUY" else "🔴 SELL"
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                mid = t.get("market", "")
                market_name = market_cache.get(mid, "Unknown")
                outcome = t.get("outcome", "")
                # Show full market name (no truncation)
                click.echo(f"   {side} {size:.2f} @ ${price} | {market_name} [{outcome}]")
        
        # Get on-chain balance via RPC
        rpc = config.get("rpc", "https://polygon.drpc.org")
        if rpc:
            click.echo(f"\n🌐 On-chain Balance (via {rpc.split('//')[-1]}):")
            try:
                from web3 import Web3
                w3 = Web3(Web3.HTTPProvider(rpc))
                if w3.is_connected():
                    # Check funder wallet (proxy wallet)
                    wallet = config.get("funder", wallet_addr)
                    
                    # POL balance
                    pol_bal = w3.eth.get_balance(wallet)
                    click.echo(f"   POL: {pol_bal / 1e18:.4f}")
                    
                    # USDC balance
                    usdc_addr = client.get_collateral_address()
                    usdc_abi = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]'
                    contract = w3.eth.contract(address=usdc_addr, abi=usdc_abi)
                    usdc_bal = contract.functions.balanceOf(wallet).call()
                    click.echo(f"   USDC: {usdc_bal / 1e6:.2f}")
                else:
                    click.echo("   ❌ Not connected to RPC")
            except Exception as e:
                click.echo(f"   ⚠️ Error: {e}")
        
    except Exception as e:
        click.echo(f"⚠️ Error: {e}")

@cli.command()
def setup():
    """Setup configuration"""
    config = load_config()
    
    click.echo("⚙️ Polycli Setup")
    click.echo("=" * 40)
    
    # Private key
    private_key = click.prompt("Private Key (0x...)", 
                               default=config.get("private_key", ""),
                               hide_input=True)
    config["private_key"] = private_key
    
    # Derive wallet address
    if private_key:
        wallet_addr = get_wallet_address(private_key)
        click.echo(f"📍 Wallet Address: {wallet_addr}")
        config["wallet_address"] = wallet_addr
    
    # Chain ID
    chain_id = click.prompt("Chain ID (137 = Polygon)", 
                           default=config.get("chain_id", 137),
                           type=int)
    config["chain_id"] = chain_id
    
    # Signature type
    sig_type = click.prompt("Signature Type (0=EOA, 1=Email/Magic, 2=Proxy)",
                           default=config.get("signature_type", 0),
                           type=int)
    config["signature_type"] = sig_type
    
    # Funder address (for email/Magic wallets)
    funder = click.prompt("Funder Address (optional, for proxy wallets)",
                         default=config.get("funder", ""))
    config["funder"] = funder
    
    # Bot settings
    click.echo("\n🤖 Bot Settings:")
    check_interval = click.prompt("Check Interval (seconds)",
                                  default=config.get("bot_settings", {}).get("check_interval", 60),
                                  type=int)
    min_balance = click.prompt("Min Balance ($)",
                               default=config.get("bot_settings", {}).get("min_balance", 10),
                               type=float)
    max_bet_size = click.prompt("Max Bet Size ($)",
                               default=config.get("bot_settings", {}).get("max_bet_size", 100),
                               type=float)
    
    config["bot_settings"] = {
        "enabled": config.get("bot_settings", {}).get("enabled", False),
        "check_interval": check_interval,
        "min_balance": min_balance,
        "max_bet_size": max_bet_size
    }
    
    save_config(config)
    click.echo("\n✅ Configuration saved!")

@cli.command()
def show_config():
    """Show current configuration"""
    config = load_config()
    
    # Hide private key in output
    safe_config = config.copy()
    if safe_config.get("private_key"):
        safe_config["private_key"] = safe_config["private_key"][:10] + "..." + safe_config["private_key"][-4:]
    if safe_config.get("funder"):
        safe_config["funder"] = safe_config["funder"][:8] + "..." + safe_config["funder"][-4:]
    
    click.echo("⚙️ Current Configuration:")
    click.echo(json.dumps(safe_config, indent=2))

@cli.command()
def btc_setup():
    """Setup BTC watch-order settings"""
    config = load_config()
    
    click.echo("⚙️ BTC Watch Order Setup")
    click.echo("=" * 40)
    
    btc_config = config.get('btc_watch_order', {})
    
    # Bid price
    bid_price = click.prompt("Bid Price Threshold ($)", 
                             default=btc_config.get('bid_price', 0.9),
                             type=float)
    
    # Min duration
    min_duration = click.prompt("Min Duration (seconds)", 
                                default=btc_config.get('min_duration', 5),
                                type=int)
    
    # Bet size
    bet_size = click.prompt("Bet Size ($)", 
                           default=btc_config.get('bet_size', 10.0),
                           type=float)
    
    # Auto claim
    auto_claim = click.prompt("Auto Claim? (y/n)", 
                             default='y' if btc_config.get('auto_claim', False) else 'n')
    auto_claim = auto_claim.lower() in ['y', 'yes']
    
    # Save
    config['btc_watch_order'] = {
        'bid_price': bid_price,
        'min_duration': min_duration,
        'bet_size': bet_size,
        'auto_claim': auto_claim
    }
    save_config(config)
    
    click.echo("\n✅ BTC Watch Order settings saved!")
    click.echo(f"   Bid Price: ${bid_price}")
    click.echo(f"   Min Duration: {min_duration}s")
    click.echo(f"   Bet Size: ${bet_size}")
    click.echo(f"   Auto Claim: {auto_claim}")

@cli.command()
@click.argument('slug', required=False)
@click.option('--limit', '-l', default=10, help='Number of markets to show')
def markets(slug, limit):
    """Get market prices (by slug or top markets)"""
    import requests
    
    # Try to get market by slug first
    if slug:
        # Try Gamma API
        try:
            resp = requests.get(
                
                f'https://gamma-api.polymarket.com/markets',
                headers={"Accept-Encoding": "none"}, params={'eventSlug': slug},
                timeout=30
            )
            if resp.status_code == 200 and resp.json():
                data = resp.json()
                m = data[0]
                question = m.get('question', 'Unknown')
                volume = m.get('volume', 0)
                tokens = m.get('tokens', [])
                
                click.echo(f"\n📊 Market: {question}")
                click.echo(f"   Volume: ${volume}")
                if tokens:
                    for t in tokens:
                        outcome = t.get('outcome', '?')
                        price = float(t.get('price', 0))
                        click.echo(f"   {outcome}: {price*100:.1f}%")
                return
        except Exception as e:
            click.echo(f"Gamma API error: {e}")
    
    # Otherwise get top markets
    try:
        from py_clob_client.client import ClobClient
        client = ClobClient('https://clob.polymarket.com')
        markets_data = client.get_simplified_markets()
        
        click.echo(f"\n📈 Top {limit} Markets:")
        for m in markets_data.get('data', [])[:limit]:
            q = m.get('question', 'Unknown')[:45]
            vol = m.get('volume', 0)
            tokens = m.get('tokens', [])
            if tokens:
                prices = '/'.join([f"{float(t.get('price', 0))*100:.0f}%" for t in tokens])
                click.echo(f"   ${vol:,.0f} | {q}... [{prices}]")
    except Exception as e:
        click.echo(f"Error: {e}")

@cli.command()
@click.argument('url_or_slug')
def market_price(url_or_slug):
    """Get price for a specific market (URL or slug)"""
    import requests
    import re
    
    # Extract slug from URL or use directly
    slug = url_or_slug
    if 'polymarket.com/' in url_or_slug:
        match = re.search(r'polymarket\.com/[^/]+/([^?]+)', url_or_slug)
        if match:
            slug = match.group(1)
    
    click.echo(f"Fetching: https://polymarket.com/event/{slug}")
    
    # Fetch the market page
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        resp = requests.get(
                
            f'https://polymarket.com/event/{slug}',
            headers=headers,
            timeout=15
        )
        
        if resp.status_code != 200:
            click.echo(f"❌ Error: HTTP {resp.status_code}")
            return
        
        html = resp.text
        
        # Extract outcome prices
        price_match = re.search(r'"outcomePrices"\s*:\s*\[([^\]]+)\]', html)
        if price_match:
            prices_str = price_match.group(1)
            prices = [p.strip().strip('"') for p in prices_str.split(',')]
            
            click.echo(f"\n📊 Prices:")
            for i, p in enumerate(prices):
                pct = float(p) * 100
                label = "Yes/Up" if i == 0 else "No/Down"
                click.echo(f"   {label}: {pct:.1f}% (${p})")
            
            # Try to get market title
            title_match = re.search(r'"title"\s*:\s*"([^"]+)', html)
            if title_match:
                click.echo(f"\n   Title: {title_match.group(1)}")
            
            return
        
        click.echo("❌ Could not find price data")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")

@cli.command()
def btc_price():
    """Get BTC Up/Down prices using CLOB API"""
    import subprocess
    import re
    from datetime import datetime, timezone
    
    try:
        from py_clob_client.client import ClobClient
        
        now = datetime.now(timezone.utc)
        current_ts = int(now.timestamp())
        
        # Get market page to find token IDs
        result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', '-H', 'Accept: text/html', 'https://polymarket.com/crypto'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        html = result.stdout
        
        # Find all 5m timestamps
        matches = re.findall(r'btc-updown-5m-(\d+)', html)
        unique_ts = sorted(set(int(m) for m in matches), reverse=True)
        
        if not unique_ts:
            click.echo("❌ No BTC Up/Down markets found")
            return
        
        # Find current market
        current_slug = None
        for ts in unique_ts:
            if ts <= current_ts:
                current_slug = f"btc-updown-5m-{ts}"
                break

        if not current_slug:
            current_slug = f"btc-updown-5m-{unique_ts[-1]}"

        # Get token IDs from market page
        result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        html = result.stdout
        
        # Extract clobTokenIds
        clob_match = re.search(r'"clobTokenIds":\[([^\]]+)\]', html)
        if not clob_match:
            click.echo("❌ Could not find token IDs")
            return
        
        token_ids = [t.strip().strip('"') for t in clob_match.group(1).split(',')]
        if len(token_ids) < 2:
            click.echo("❌ Not enough token IDs found")
            return
        
        # Get prices from CLOB API
        client = ClobClient('https://clob.polymarket.com')
        
        price_up = client.get_last_trade_price(token_ids[0])
        price_down = client.get_last_trade_price(token_ids[1])
        
        up_price = float(price_up.get('price', 0))
        down_price = float(price_down.get('price', 0))
        
        # Get title
        title_match = re.search(r'"title"\s*:\s*"([^"]+)', html)
        title = title_match.group(1) if title_match else current_slug
        
        # Output
        click.echo(f"Market: {title}")
        click.echo(f"URL: https://polymarket.com/event/{current_slug}")
        click.echo(f"Up: ${up_price:.3f}")
        click.echo(f"Down: ${down_price:.3f}")
        
    except ImportError:
        click.echo("❌ py-clob-client not installed. Run: pip install py-clob-client")
    except Exception as e:
        click.echo(f"❌ Error: {e}")

@cli.command()
def btc_updown():
    """Get current BTC Up/Down 5m active market using CLOB API"""
    import subprocess
    import re
    from datetime import datetime, timezone
    
    try:
        from py_clob_client.client import ClobClient
        
        now = datetime.now(timezone.utc)
        current_ts = int(now.timestamp())
        
        # Get btc-updown page from crypto section
        result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', '-H', 'Accept: text/html', 'https://polymarket.com/crypto'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        html = result.stdout
        
        # Find all 5m timestamps
        matches = re.findall(r'btc-updown-5m-(\d+)', html)
        unique_ts = sorted(set(int(m) for m in matches), reverse=True)
        
        if not unique_ts:
            click.echo("❌ No BTC Up/Down markets found")
            return
        
        # Find current/most recent market
        current_slug = None
        for ts in unique_ts:
            if ts <= current_ts:
                current_slug = f"btc-updown-5m-{ts}"
                break

        if not current_slug:
            current_slug = f"btc-updown-5m-{unique_ts[-1]}"

        # Get token IDs
        result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        html = result.stdout
        
        clob_match = re.search(r'"clobTokenIds":\[([^\]]+)\]', html)
        if not clob_match:
            click.echo("❌ Could not find token IDs")
            return
        
        token_ids = [t.strip().strip('"') for t in clob_match.group(1).split(',')]
        
        # Get prices from CLOB API
        client = ClobClient('https://clob.polymarket.com')
        
        price_up = client.get_last_trade_price(token_ids[0])
        price_down = client.get_last_trade_price(token_ids[1])
        
        up_price = float(price_up.get('price', 0))
        down_price = float(price_down.get('price', 0))
        
        # Get title
        title_match = re.search(r'"title"\s*:\s*"([^"]+)', html)
        title = title_match.group(1) if title_match else current_slug
        
        click.echo(f"\n🔄 Getting current BTC Up/Down 5m market...")
        click.echo(f"\n📊 {title}")
        click.echo(f"   URL: https://polymarket.com/event/{current_slug}")
        click.echo(f"\n   Prices:")
        click.echo(f"   📈 Up: {up_price*100:.1f}% (${up_price:.3f})")
        click.echo(f"   📉 Down: {down_price*100:.1f}% (${down_price:.3f})")
        
    except ImportError:
        click.echo("❌ py-clob-client not installed. Run: pip install py-clob-client")
    except Exception as e:
        click.echo(f"❌ Error: {e}")

@cli.command()
def btc_watch():
    """Watch BTC Up/Down prices in real-time using CLOB API"""
    import subprocess
    import re
    from datetime import datetime, timezone
    import time
    
    try:
        from py_clob_client.client import ClobClient
        
        click.echo("📊 Watching BTC Up/Down prices... (Press Ctrl+C to stop)")
        click.echo("-" * 50)
        
        client = ClobClient('https://clob.polymarket.com')
        
        try:
            while True:
                now = datetime.now(timezone.utc)
                current_ts = int(now.timestamp())
                
                # Get timestamps from crypto page
                result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', '-H', 'Accept: text/html', 'https://polymarket.com/crypto'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                html = result.stdout
                
                matches = re.findall(r'btc-updown-5m-(\d+)', html)
                unique_ts = sorted(set(int(m) for m in matches), reverse=True)
                
                if not unique_ts:
                    click.echo("❌ No markets found")
                    time.sleep(2)
                    continue
                
                # Find current market
                current_slug = None
                for ts in unique_ts:
                    if ts <= current_ts:
                        current_slug = f"btc-updown-5m-{ts}"
                        break

                if not current_slug:
                    current_slug = f"btc-updown-5m-{unique_ts[-1]}"

                # Get token IDs
                result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                html = result.stdout
                
                clob_match = re.search(r'"clobTokenIds":\[([^\]]+)\]', html)
                if not clob_match:
                    click.echo("❌ Could not find token IDs")
                    time.sleep(2)
                    continue
                
                token_ids = [t.strip().strip('"') for t in clob_match.group(1).split(',')]
                if len(token_ids) < 2:
                    continue
                
                # Get prices from CLOB
                price_up = client.get_last_trade_price(token_ids[0])
                price_down = client.get_last_trade_price(token_ids[1])
                
                up_price = float(price_up.get('price', 0))
                down_price = float(price_down.get('price', 0))
                
                # Get title
                title_match = re.search(r'"title"\s*:\s*"([^"]+)', html)
                title = title_match.group(1) if title_match else current_slug
                timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                
                click.echo(f"[{timestamp}] {title}")
                click.echo(f"   Up: ${up_price:.3f}  |  Down: ${down_price:.3f}")
                
                time.sleep(2)
                
        except KeyboardInterrupt:
            click.echo("\n🛑 Stopped")
            
    except ImportError:
        click.echo("❌ py-clob-client not installed. Run: pip install py-clob-client")
    except Exception as e:
        click.echo(f"❌ Error: {e}")

@cli.command()
@click.option('--bid-price', default=None, type=float, help='Bid price threshold (default from config)')
@click.option('--min-duration', default=None, type=int, help='Seconds price must exceed threshold (default from config)')
@click.option('--bet-size', default=None, type=float, help='Bet size in USD (default from config)')
@click.option('--auto-claim', is_flag=True, default=None, help='Auto claim winnings after market resolves')
@click.option('--stop-loss', default=None, type=float, help='Stop loss percentage (default from config)')
@click.option('--paper', is_flag=True, default=False, help='Paper trading mode - simulate orders, save ticks & journal')
def btc_watch_order(bid_price, min_duration, bet_size, auto_claim, stop_loss, paper):
    """Watch BTC prices and place bid when conditions are met

    Options can be set via config.json or command line.
    Use --paper for paper trading (no real orders, saves data for analysis).
    """
    import subprocess
    import re
    import logging
    from datetime import datetime, timezone
    import time

    # Setup file logging - one file per day, auto-rotates at midnight
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
    bot_logger = logging.getLogger("bot")
    bot_logger.setLevel(logging.INFO)
    # Remove any stale handlers from previous runs
    bot_logger.handlers.clear()
    from logging.handlers import TimedRotatingFileHandler
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=30, encoding="utf-8"
    )
    file_handler.suffix = "%Y%m%d"
    file_handler.namer = lambda name: str(log_dir / f"bot_{name.split('.')[-1]}.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    bot_logger.addHandler(file_handler)

    def bot_log(msg, echo=True):
        """Log to file and optionally print to console."""
        bot_logger.info(msg)
        if echo:
            click.echo(msg)

    # Load config for default values
    config = load_config()

    # Telegram notification setup
    from telegram import TelegramNotifier, TelegramCommandHandler
    tg = TelegramNotifier(config.get('telegram_bot_token', ''), config.get('telegram_chat_id', ''))

    btc_config = config.get('btc_watch_order', {})

    # Use command line args if provided, otherwise use config
    bid_price = bid_price if bid_price is not None else btc_config.get('bid_price', 0.9)
    min_duration = min_duration if min_duration is not None else btc_config.get('min_duration', 5)
    bet_size = bet_size if bet_size is not None else btc_config.get('bet_size', 10.0)
    auto_claim = auto_claim if auto_claim is not None else btc_config.get('auto_claim', False)
    stop_loss_percent = stop_loss if stop_loss is not None else btc_config.get('stop_loss_percent', 0)
    sl_min_duration = config.get('sl_min_duration', 5)  # Read from root level
    time_buffer = btc_config.get('time_buffer', 15)

    # Paper trading: tick data and journal
    paper_tick_markets = {}  # slug -> {slug, start_ts, ticks, winner, resolved_at}
    paper_trades = []  # Simulated trades
    resolving_slugs = set()  # slugs with active background resolver threads
    paper_ticks_file = Path(__file__).parent / "backtest" / "ticks.json"
    paper_journal_file = Path(__file__).parent / "trades.json"

    def _query_gamma_markets(slug, closed=False):
        """Query Gamma /markets API. Returns (up_f, dn_f, is_resolved) or None."""
        import requests as _req
        try:
            url = f'https://gamma-api.polymarket.com/markets?slug={slug}'
            if closed:
                url += '&closed=true'
            resp = _req.get(url, timeout=10)
            if resp.status_code == 200 and resp.json():
                mdata = resp.json()[0]
                is_resolved = mdata.get('umaResolutionStatus') == 'resolved'
                op_raw = mdata.get('outcomePrices', '[]')
                op = json.loads(op_raw) if isinstance(op_raw, str) else op_raw
                if len(op) >= 2:
                    return float(op[0]), float(op[1]), is_resolved
        except Exception:
            pass
        return None

    def _query_gamma_events(slug):
        """Query Gamma /events API (fallback). Returns (up_f, dn_f, is_resolved) or None."""
        import requests as _req
        try:
            resp = _req.get(f'https://gamma-api.polymarket.com/events?slug={slug}', timeout=10)
            if resp.status_code == 200 and resp.json():
                markets = resp.json()[0].get('markets', [])
                for m in markets:
                    if m.get('slug') == slug:
                        is_resolved = m.get('umaResolutionStatus') == 'resolved'
                        op_raw = m.get('outcomePrices', '[]')
                        op = json.loads(op_raw) if isinstance(op_raw, str) else op_raw
                        if len(op) >= 2:
                            return float(op[0]), float(op[1]), is_resolved
        except Exception:
            pass
        return None

    # Load max existing trade ID and close stale open trades from previous sessions
    paper_next_id = 1
    if paper_journal_file.exists():
        try:
            with open(paper_journal_file, 'r') as f:
                _data = json.load(f)
                _trades = _data.get("trades", [])
                _ids = [t.get("id", 0) for t in _trades]
                if _ids:
                    paper_next_id = max(_ids) + 1
                # Identify orphaned open trades — they'll be resolved in background after startup
                _now_ts = int(datetime.now(timezone.utc).timestamp())
                for t in _trades:
                    if t.get("status") != "open":
                        continue
                    slug = t.get("slug", "")
                    try:
                        _market_end_ts = int(slug.split("-")[-1])
                    except (ValueError, IndexError):
                        _market_end_ts = 0
                    if _market_end_ts > 0 and _now_ts < _market_end_ts + 30:
                        click.echo(f"   ⏳ Orphan trade {t['id']} ({slug}) market still active, leaving open.")
                    else:
                        click.echo(f"   🔄 Orphan trade {t['id']} ({slug}) will be resolved in background...")
        except (json.JSONDecodeError, IOError):
            pass

    # Load any remaining open trades from previous session into paper_trades
    # so paper_close_trade() can find and close them (background resolver needs this)
    if paper_journal_file.exists():
        try:
            with open(paper_journal_file, 'r') as f:
                _prev = json.load(f)
            for t in _prev.get("trades", []):
                if t.get("status") == "open":
                    paper_trades.append(t)
        except (json.JSONDecodeError, IOError):
            pass

    def save_tick(slug, up_price, down_price, now_ts):
        """Save a tick data point grouped by market slug (simulate.py compatible)."""
        if not paper:
            return
        start_ts = (now_ts // 300) * 300
        if slug not in paper_tick_markets:
            paper_tick_markets[slug] = {
                "slug": slug,
                "start_ts": start_ts,
                "ticks": [],
                "winner": None,
                "resolved_at": None,
            }
        paper_tick_markets[slug]["ticks"].append({
            "t": now_ts,
            "up": round(up_price, 4),
            "down": round(down_price, 4),
        })
        total_ticks = sum(len(m["ticks"]) for m in paper_tick_markets.values())
        if total_ticks % 30 == 0:
            flush_ticks()

    def flush_ticks():
        """Write tick markets to file in live_collector.py format."""
        if not paper_tick_markets:
            return
        paper_ticks_file.parent.mkdir(parents=True, exist_ok=True)
        existing = {"markets": {}, "collection_started": None, "last_updated": None}
        if paper_ticks_file.exists():
            try:
                with open(paper_ticks_file, 'r') as f:
                    raw = json.load(f)
                if isinstance(raw, dict) and "markets" in raw:
                    existing = raw
                # else: old flat-list format — discard and start fresh
            except (json.JSONDecodeError, IOError):
                pass
        if not existing.get("collection_started"):
            existing["collection_started"] = datetime.now(timezone.utc).isoformat()
        # Merge current session markets into existing
        for slug, market in paper_tick_markets.items():
            if slug not in existing["markets"]:
                existing["markets"][slug] = {
                    "slug": market["slug"],
                    "start_ts": market["start_ts"],
                    "ticks": [],
                    "winner": None,
                    "resolved_at": None,
                }
            existing_ts = {t["t"] for t in existing["markets"][slug]["ticks"]}
            for tick in market["ticks"]:
                if tick["t"] not in existing_ts:
                    existing["markets"][slug]["ticks"].append(tick)
            if market["winner"] and not existing["markets"][slug]["winner"]:
                existing["markets"][slug]["winner"] = market["winner"]
                existing["markets"][slug]["resolved_at"] = market["resolved_at"]
        existing["last_updated"] = datetime.now(timezone.utc).isoformat()
        tmp = str(paper_ticks_file) + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, str(paper_ticks_file))

    def resolve_tick_winner_background(slug):
        """Resolve winner for a no-trade market in a background thread (backtest data)."""
        import threading

        def _set_tick_winner(winner_str):
            if slug in paper_tick_markets:
                paper_tick_markets[slug]["winner"] = winner_str
                paper_tick_markets[slug]["resolved_at"] = int(datetime.now(timezone.utc).timestamp())
                flush_ticks()

        def _check_tick_data(data):
            if not data:
                return None
            up_f, dn_f, _resolved = data
            if up_f >= 0.99:
                return "Up"
            elif dn_f >= 0.99:
                return "Down"
            return None

        def _resolve():
            # Phase 1: /markets for 4 minutes (24 * 10s)
            for _retry in range(24):
                winner = _check_tick_data(_query_gamma_markets(slug, closed=False) or _query_gamma_markets(slug, closed=True))
                if winner:
                    _set_tick_winner(winner)
                    return
                time.sleep(10)

            # Phase 2: /events fallback for 3 minutes (18 * 10s)
            for _retry in range(18):
                winner = _check_tick_data(_query_gamma_events(slug))
                if winner:
                    _set_tick_winner(winner)
                    return
                time.sleep(10)

            # Phase 3: /markets final attempt for 3 minutes (18 * 10s)
            for _retry in range(18):
                winner = _check_tick_data(_query_gamma_markets(slug, closed=False) or _query_gamma_markets(slug, closed=True))
                if winner:
                    _set_tick_winner(winner)
                    return
                time.sleep(10)

        threading.Thread(target=_resolve, daemon=True).start()

    def resolve_trade_background(slug, resolve_side, resolve_entry_price):
        """Resolve a paper trade in a background thread — does not block the main loop."""
        import threading

        # Prevent duplicate resolvers for the same slug
        if slug in resolving_slugs:
            bot_log(f"   ℹ️ Resolver already running for {slug}, skipping", echo=False)
            return
        resolving_slugs.add(slug)

        def _check_winner(data):
            if not data:
                return None
            up_f, dn_f, is_resolved = data
            if up_f >= 0.99:
                winner = "UP"
            elif dn_f >= 0.99:
                winner = "DOWN"
            else:
                winner = None
            if winner and (is_resolved or up_f >= 0.99 or dn_f >= 0.99):
                return winner
            return None

        def _close_resolved(winner, source_label=""):
            """Close a resolved trade, log it, and send Telegram notification."""
            won = (resolve_side == winner)
            exit_price = 1.0 if won else 0.0
            trade = paper_close_trade(slug, exit_price, "resolved")
            if trade is None:
                # Already closed (stop-loss or duplicate resolver)
                return
            pnl = ((1.0 - resolve_entry_price) if won else (-resolve_entry_price)) * bet_size
            result_emoji = "🎉 WON" if won else "💸 LOST"
            suffix = f" ({source_label})" if source_label else ""
            bot_log(f"   📝 PAPER RESULT [{slug}]{suffix}: {result_emoji} | {resolve_side} | P&L: ${pnl:+.2f}")
            tg.trade_closed_resolved(trade["id"], slug, resolve_side, resolve_entry_price, exit_price, pnl, won, source_label)

        def _resolve():
            try:
                # Phase 1: try /markets for 15 minutes (90 * 10s)
                for _retry in range(90):
                    data = _query_gamma_markets(slug, closed=False) or _query_gamma_markets(slug, closed=True)
                    winner = _check_winner(data)
                    if winner:
                        _close_resolved(winner)
                        return
                    time.sleep(10)

                # Phase 2: /markets failed — try /events for 5 minutes (30 * 10s)
                bot_log(f"   🔄 /markets failed for {slug}, trying /events fallback...")
                for _retry in range(30):
                    data = _query_gamma_events(slug)
                    winner = _check_winner(data)
                    if winner:
                        _close_resolved(winner, "via events")
                        return
                    time.sleep(10)

                # Phase 3: last attempt — /markets one more time (30 * 10s)
                bot_log(f"   🔄 /events failed for {slug}, final /markets attempt...")
                for _retry in range(30):
                    data = _query_gamma_markets(slug, closed=False) or _query_gamma_markets(slug, closed=True)
                    winner = _check_winner(data)
                    if winner:
                        _close_resolved(winner, "final")
                        return
                    time.sleep(10)

                # All phases exhausted (~25 min total) — close as unresolved
                trade = paper_close_trade(slug, 0.5, "unresolved")
                if trade:
                    bot_log(f"   ⚠️ Could not resolve {slug} after all retries — closed as unresolved")
                    tg.trade_closed_unresolved(trade["id"], slug, resolve_side, resolve_entry_price)
            finally:
                resolving_slugs.discard(slug)

        threading.Thread(target=_resolve, daemon=True).start()

    def paper_log_trade(slug, side, entry_price, bet_size, token_id=None):
        """Log a simulated trade."""
        trade = {
            "id": paper_next_id + len(paper_trades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "slug": slug,
            "side": side,
            "entry_price": entry_price,
            "bet_size": bet_size,
            "token_id": token_id,
            "order_id": None,
            "status": "open",
            "exit_price": None,
            "exit_timestamp": None,
            "pnl": None,
            "exit_reason": None,
            "mode": "paper",
        }
        paper_trades.append(trade)
        save_journal()
        return trade["id"]

    def paper_close_trade(slug, exit_price, exit_reason="resolved"):
        """Close a simulated trade."""
        for trade in reversed(paper_trades):
            if trade["slug"] == slug and trade["status"] == "open":
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_reason"] = exit_reason
                trade["exit_timestamp"] = datetime.now(timezone.utc).isoformat()
                if exit_price >= 0.99:  # Won
                    trade["pnl"] = round((1.0 - trade["entry_price"]) * trade["bet_size"], 2)
                elif exit_price <= 0.01:  # Lost
                    trade["pnl"] = round(-trade["entry_price"] * trade["bet_size"], 2)
                else:  # Stop-loss
                    trade["pnl"] = round((exit_price - trade["entry_price"]) * trade["bet_size"], 2)
                save_journal()
                # Update winner in tick markets for backtest data
                if exit_reason == "resolved" and slug in paper_tick_markets:
                    if exit_price >= 0.99:
                        paper_tick_markets[slug]["winner"] = "Up" if trade["side"] == "UP" else "Down"
                    elif exit_price <= 0.01:
                        paper_tick_markets[slug]["winner"] = "Down" if trade["side"] == "UP" else "Up"
                    paper_tick_markets[slug]["resolved_at"] = int(datetime.now(timezone.utc).timestamp())
                    flush_ticks()
                return trade
        return None

    def save_journal():
        """Save paper trades to journal file."""
        # Load existing trades from previous sessions (different IDs)
        existing_trades = []
        current_ids = {t["id"] for t in paper_trades}
        if paper_journal_file.exists():
            try:
                with open(paper_journal_file, 'r') as f:
                    data = json.load(f)
                    existing_trades = [t for t in data.get("trades", []) if t.get("id") not in current_ids]
            except (json.JSONDecodeError, IOError):
                pass
        all_trades = existing_trades + paper_trades
        with open(paper_journal_file, 'w') as f:
            json.dump({"trades": all_trades, "mode": "paper"}, f, indent=2)

    def print_paper_summary():
        """Print paper trading performance summary."""
        if not paper_trades:
            click.echo("\n📋 No paper trades recorded.")
            return

        closed = [t for t in paper_trades if t["status"] == "closed"]
        open_trades = [t for t in paper_trades if t["status"] == "open"]

        click.echo(f"\n{'='*60}")
        click.echo(f"📋 PAPER TRADING SUMMARY")
        click.echo(f"{'='*60}")
        click.echo(f"Total trades: {len(paper_trades)} (Closed: {len(closed)}, Open: {len(open_trades)})")
        total_ticks = sum(len(m["ticks"]) for m in paper_tick_markets.values())
        click.echo(f"Ticks collected: {total_ticks}")

        if closed:
            wins = [t for t in closed if (t.get("pnl") or 0) > 0]
            losses = [t for t in closed if (t.get("pnl") or 0) < 0]
            total_pnl = sum(t.get("pnl", 0) for t in closed)
            win_rate = len(wins) / len(closed) * 100 if closed else 0

            click.echo(f"\nWins: {len(wins)}  Losses: {len(losses)}")
            click.echo(f"Win Rate: {win_rate:.1f}%")
            click.echo(f"Total P&L: ${total_pnl:+.2f}")

            if wins:
                click.echo(f"Avg Win: ${sum(t['pnl'] for t in wins)/len(wins):+.2f}")
            if losses:
                click.echo(f"Avg Loss: ${sum(t['pnl'] for t in losses)/len(losses):+.2f}")

            # Breakeven analysis
            breakeven_wr = bid_price * 100
            click.echo(f"\nBreakeven WR needed: {breakeven_wr:.0f}%")
            click.echo(f"Actual WR: {win_rate:.1f}%")
            if win_rate > breakeven_wr:
                click.echo(f"Edge: +{win_rate - breakeven_wr:.1f}% -> PROFITABLE signal")
            else:
                click.echo(f"Edge: {win_rate - breakeven_wr:.1f}% -> NOT profitable")

            click.echo(f"\nTrades:")
            for t in closed[-10:]:
                result = "W" if (t.get("pnl") or 0) > 0 else "L"
                click.echo(f"  {result} {t['side']:>4} @ ${t['entry_price']:.2f} "
                          f"-> exit ${t.get('exit_price', 0):.2f} "
                          f"P&L=${t.get('pnl', 0):+.2f} ({t.get('exit_reason', '')})")

        click.echo(f"\nData saved to:")
        click.echo(f"  Ticks: {paper_ticks_file}")
        click.echo(f"  Journal: {paper_journal_file}")

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL
        
        def has_filled_position(client, token_id, bet_size):
            """ตรวจสอบว่ามี position จริงๆ หรือไม่ (order fill แล้ว)"""
            try:
                # วิธี 1: เช็คจาก positions
                positions = client.get_positions()
                for pos in positions:
                    if pos.get('asset_id') == token_id or pos.get('token_id') == token_id:
                        size = float(pos.get('size', 0) or pos.get('quantity', 0))
                        if size > 0:
                            return True, size
                
                # วิธี 2: เช็คจาก orders ที่ fill แล้ว
                orders = client.get_orders()
                for order in orders:
                    if order.get('token_id') == token_id:
                        status = order.get('status', '')
                        filled_size = float(order.get('filled_size', 0) or order.get('size', 0))
                        if filled_size > 0 and status in ['FILLED', 'PARTIAL_FILLED']:
                            return True, filled_size
                
                return False, 0
            except Exception as e:
                # ถ้าเช็คไม่ได้ ให้ถือว่ามี position (ปลอดภัย)
                return True, float(bet_size)
        
        mode_label = "📝 PAPER MODE" if paper else "💰 LIVE MODE"
        bot_log(f"📊 Watching BTC Up/Down with auto-order... (Press Ctrl+C to stop)")
        bot_log(f"   Mode: {mode_label}")
        bot_log(f"   Bid threshold: > ${bid_price} for {min_duration} seconds")
        bot_log(f"   Bet size: ${bet_size}")
        sl_status = f"{stop_loss_percent}% (min duration: {sl_min_duration}s)" if stop_loss_percent > 0 else "disabled"
        bot_log(f"   Stop loss: {sl_status}")
        bot_log(f"   Auto-claim: {'Enabled' if auto_claim else 'Disabled'}")
        bot_log(f"   Log file: {log_file}")
        click.echo("-" * 60)

        # Background Telegram summary scheduler (4h + daily)
        import threading

        def _summary_scheduler():
            """Send periodic trade summaries via Telegram."""
            from datetime import timedelta
            FOUR_HOURS = 4 * 3600
            last_4h_send = time.time()
            last_daily_date = datetime.now(timezone.utc).date()

            def _load_all_trades():
                """Load all trades from journal file + in-memory list."""
                all_trades = list(paper_trades)
                try:
                    if paper_journal_file.exists():
                        with open(paper_journal_file, 'r') as f:
                            saved = json.load(f).get("trades", [])
                        mem_ids = {t["id"] for t in all_trades}
                        for t in saved:
                            if t["id"] not in mem_ids:
                                all_trades.append(t)
                except Exception:
                    pass
                return all_trades

            while True:
                time.sleep(60)  # check every minute
                now = time.time()
                now_utc = datetime.now(timezone.utc)

                # --- 4-hour summary ---
                if now - last_4h_send >= FOUR_HOURS:
                    last_4h_send = now
                    cutoff_iso = (now_utc - timedelta(hours=4)).isoformat()
                    all_trades = _load_all_trades()
                    recent = [t for t in all_trades if t.get("timestamp", "") >= cutoff_iso]
                    tg.trade_summary(recent, "4-Hour", bid_price=bid_price)
                    bot_log("📊 Sent 4-hour Telegram summary", echo=False)

                # --- Daily summary at midnight UTC ---
                today = now_utc.date()
                if today != last_daily_date:
                    yesterday = last_daily_date
                    last_daily_date = today
                    yesterday_str = yesterday.isoformat()
                    all_trades = _load_all_trades()
                    day_trades = [t for t in all_trades if t.get("timestamp", "")[:10] == yesterday_str]
                    tg.trade_summary(day_trades, f"Daily ({yesterday_str})", bid_price=bid_price)
                    bot_log(f"📊 Sent daily Telegram summary for {yesterday_str}", echo=False)

        threading.Thread(target=_summary_scheduler, daemon=True).start()
        bot_log("📊 Telegram summary scheduler started (4h + daily)", echo=False)

        # Start Telegram command listener (responds to /summary, /stats, /open, /help)
        tg_cmd = TelegramCommandHandler(tg, paper_journal_file, bid_price=bid_price)
        tg_cmd.set_live_trades(paper_trades)
        tg_cmd.start()
        if tg.enabled:
            bot_log("🤖 Telegram command listener started", echo=False)

        # Kick off background resolvers for orphaned open trades from previous sessions
        _now_ts = int(datetime.now(timezone.utc).timestamp())
        for _ot in list(paper_trades):
            if _ot.get("status") != "open":
                continue
            _ot_slug = _ot.get("slug", "")
            try:
                _ot_end_ts = int(_ot_slug.split("-")[-1])
            except (ValueError, IndexError):
                _ot_end_ts = 0
            if _ot_end_ts > 0 and _now_ts >= _ot_end_ts + 30:
                bot_log(f"   🔄 Starting background resolver for orphan trade {_ot['id']} ({_ot_slug})")
                resolve_trade_background(_ot_slug, _ot.get("side", "UP"), _ot.get("entry_price", 0.5))
        
        # Initialize client
        config = load_config()
        if paper and not config.get("private_key"):
            # Paper mode: read-only client for price data
            client = ClobClient(config.get("host", "https://clob.polymarket.com"))
            click.echo("📝 Paper mode: read-only client (no private key needed)")
        else:
            client = ClobClient(
                config.get("host", "https://clob.polymarket.com"),
                key=config["private_key"],
                chain_id=config.get("chain_id", 137),
                signature_type=config.get("signature_type", 0),
                funder=config.get("funder", "")
            )
            # Create API creds
            try:
                creds = client.create_or_derive_api_creds()
                client.set_api_creds(creds)
                click.echo("✅ API credentials ready")
            except Exception as e:
                click.echo(f"⚠️ API creds error: {e}")
        
        # Get first market info
        click.echo("🔄 Loading market info...")
        now = datetime.now(timezone.utc)
        current_ts = int(now.timestamp())
        base_ts = (current_ts // 300) * 300
        current_slug = f'btc-updown-5m-{base_ts}'
        click.echo(f"   Market: {current_slug}")
        
        result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 
                     '-H', 'Accept: text/html', 
                     f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        
        # Check for Vercel checkpoint
        if 'checkpoint' in result.stdout.lower() or 'vercel' in result.stdout.lower():
            click.echo(f"   ⚠️ Vercel checkpoint detected - using CLOB API fallback")
            # Skip initial curl load, will use CLOB in loop
            result = None
        
        if result:
            click.echo(f"   ✅ Market data loaded ({len(result.stdout)} bytes)")
        
        # Initialize tracking variables
        up_high_duration = 0
        down_high_duration = 0
        last_up_price = 0
        last_down_price = 0
        order_placed = False
        bought_token = None
        last_displayed_slug = None
        use_gamma_prices = False  # Flag to use Gamma API prices
        title = ""  # Initialize title to avoid NameError
        token_ids = []  # Initialize token_ids
        # Stop loss tracking
        entry_price = None
        entry_side = None
        entry_market_slug = None  # Track which market we bought in
        sl_active_duration = 0  # Track how long stop loss has been triggered
        traded_slugs = set()  # Markets already traded this session — one trade per market
        # Restore state from any open trade carried over from previous session
        for _t in paper_trades:
            if _t.get("status") == "open":
                traded_slugs.add(_t["slug"])
                # Restore tracking vars so had_position=True and resolution fires correctly
                entry_price = _t.get("entry_price")
                entry_side = _t.get("side")
                entry_market_slug = _t.get("slug")
                order_placed = True
                break  # only one open trade expected per session
        
        try:
            while True:
                now = datetime.now(timezone.utc)
                current_ts = int(now.timestamp())
                
                # Calculate current market timestamp directly (no website needed!)
                base_ts = (current_ts // 300) * 300  # Round down to 5 minutes
                current_slug = f'btc-updown-5m-{base_ts}'
                
                # Debug: print market change (don't update slug yet if we have a position - resolution handler needs the old slug)
                if last_displayed_slug and current_slug != last_displayed_slug:
                    print(f"\n🔄 Market: {last_displayed_slug} → {current_slug}")
                    if not ((order_placed and bought_token) or entry_market_slug is not None):
                        # Paper mode: resolve winner for markets with no trade (backtest data completeness)
                        if (paper and last_displayed_slug in paper_tick_markets
                                and not paper_tick_markets[last_displayed_slug].get("winner")):
                            resolve_tick_winner_background(last_displayed_slug)
                        last_displayed_slug = current_slug
                        up_high_duration = 0
                        down_high_duration = 0
                
                # Try to get market data from website
                try:
                    result = subprocess.run(
                        ['curl', '-s',
                         '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                         '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                         '-H', 'Accept-Language: en-US,en;q=0.5',
                         '-H', 'Connection: keep-alive',
                         '-H', 'Upgrade-Insecure-Requests: 1',
                         f'https://polymarket.com/event/{current_slug}'],
                        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
                    )
                except subprocess.TimeoutExpired:
                    result = None

                # If website returns checkpoint or timed out, try Gamma API as fallback
                use_clob_fallback = result is None or 'checkpoint' in result.stdout.lower() or 'vercel' in result.stdout.lower()
                
                if use_clob_fallback:
                    # Fallback: use Gamma API by slug
                    try:
                        import requests as req
                        # Add timestamp + random to prevent API caching
                        import time
                        import random
                        url = f"https://gamma-api.polymarket.com/markets?slug={current_slug}&t={int(time.time()*1000)}&r={random.randint(1000,9999)}"
                        resp = req.get(url, headers={"Accept-Encoding": "none"}, timeout=10)
                        if resp.status_code == 200 and resp.json():
                            market_data = resp.json()[0]
                            
                            # Get prices from outcomePrices
                            outcome_prices = market_data.get('outcomePrices', '[]')
                            if isinstance(outcome_prices, str):
                                prices = json.loads(outcome_prices)
                            else:
                                prices = outcome_prices if outcome_prices else []
                            
                            # Use lastTradePrice or bestBid/bestAsk for real prices
                            last_price = market_data.get('lastTradePrice')
                            best_bid = market_data.get('bestBid')
                            best_ask = market_data.get('bestAsk')
                            
                            # Get token IDs for CLOB prices
                            clob_token_ids = market_data.get('clobTokenIds', '[]')
                            if isinstance(clob_token_ids, str):
                                token_ids = json.loads(clob_token_ids) if clob_token_ids else []
                            else:
                                token_ids = clob_token_ids if clob_token_ids else []
                            
                            # Try CLOB first for real-time prices
                            use_clob_prices = False
                            if len(token_ids) >= 2:
                                try:
                                    p_up = client.get_last_trade_price(token_ids[0])
                                    p_down = client.get_last_trade_price(token_ids[1])
                                    if p_up and p_down:
                                        up_price_c = float(p_up.get('price', 0))
                                        down_price_c = float(p_down.get('price', 0))
                                        if up_price_c > 0.05 and up_price_c < 0.95:
                                            up_price = up_price_c
                                            down_price = down_price_c
                                            use_clob_prices = True
                                            click.echo(f"   ✅ CLOB: Up=${up_price:.3f}, Down=${down_price:.3f}")
                                except:
                                    pass
                            
                            # Fallback to Gamma bestBid/bestAsk
                            if not use_clob_prices:
                                if best_bid and best_ask:
                                    up_price = float(best_ask)
                                    down_price = float(best_bid)
                                elif last_price:
                                    mid = float(last_price)
                                    up_price = min(mid + 0.01, 0.99)
                                    down_price = max(mid - 0.01, 0.01)
                                else:
                                    up_price = float(prices[0]) if len(prices) > 0 else 0.5
                                    down_price = float(prices[1]) if len(prices) > 1 else 0.5
                                # Already printed above
                            
                            # Get condition ID and title for trading
                            condition_id = market_data.get('conditionId', '')
                            title = market_data.get('question', current_slug)
                            
                            click.echo(f"   ✅ Got prices from Gamma API: Up=${up_price:.3f}, Down=${down_price:.3f}")
                            
                            # Set flag to skip CLOB price fetch
                            use_gamma_prices = True
                            
                            # Continue with prices - html will be empty but we'll use prices
                            html = ""
                        else:
                            click.echo(f"   ⚠️ No market in Gamma for {current_slug}")
                            time.sleep(3)
                            continue
                    except Exception as e:
                        bot_log(f"   ⚠️ Gamma API error: {e}")
                        time.sleep(3)
                        continue
                else:
                    # Use website HTML for tokens and prices
                    html = result.stdout
                
                # Load pause config from config
                pause_config = btc_config.get('markets_before_pause', 5)
                pause_duration = btc_config.get('pause_duration_seconds', 300)
                
                # Track market changes for pause
                if last_displayed_slug and current_slug != last_displayed_slug:
                    market_change_count = getattr(btc_watch_order, 'market_change_count', 0) + 1
                    btc_watch_order.market_change_count = market_change_count
                    
                    # Check if we should pause
                    if market_change_count >= pause_config and not getattr(btc_watch_order, 'is_paused', False):
                        click.echo(f"\n⏸️ Pausing for {pause_duration}s after {pause_config} markets...")
                        time.sleep(pause_duration)
                        btc_watch_order.is_paused = True
                        btc_watch_order.market_change_count = 0
                        click.echo(f"▶️ Resuming...")
                
                # Check if market resolved (compare with last displayed)
                # Use entry_market_slug to detect we had a position, even if stop-loss already reset order_placed
                had_position = (order_placed and bought_token) or entry_market_slug is not None
                if had_position and last_displayed_slug and current_slug != last_displayed_slug:
                    # Save entry info before resolution check (stop-loss may have cleared these)
                    resolve_side = entry_side
                    resolve_entry_price = entry_price
                    # New market - check if old market resolved
                    bot_log(f"\n🔄 Market changed from {last_displayed_slug} to {current_slug}")

                    if paper:
                        # Check if trade was already closed by stop-loss
                        has_open_trade = any(
                            t["slug"] == last_displayed_slug and t["status"] == "open"
                            for t in paper_trades
                        )
                        if has_open_trade and resolve_side:
                            # Fire background resolution — main loop continues immediately
                            bot_log(f"   🔄 Resolving {last_displayed_slug} in background...")
                            resolve_trade_background(last_displayed_slug, resolve_side, resolve_entry_price)
                        elif not has_open_trade:
                            bot_log(f"   ℹ️ Trade already closed (stop-loss) for {last_displayed_slug}", echo=False)
                    else:
                        # Live mode: check unfilled orders
                        if order_placed and bought_token:
                            try:
                                open_orders = client.get_orders()
                                unfilled_orders = [o for o in open_orders if o.get('token_id') == bought_token]

                                if unfilled_orders:
                                    click.echo(f"⚠️ Found unfilled order, canceling...")
                                    for oo in unfilled_orders:
                                        order_id = oo.get('orderID')
                                        try:
                                            cancel_result = client.cancel(order_id)
                                            if cancel_result.get('success'):
                                                click.echo(f"   ✅ Canceled order: {order_id[:20]}...")
                                            else:
                                                click.echo(f"   ❌ Failed to cancel: {cancel_result.get('errorMsg', 'Unknown')}")
                                        except Exception as e:
                                            click.echo(f"   ❌ Cancel error: {e}")
                                else:
                                    click.echo(f"   ✅ Order was filled (no open orders)")
                            except Exception as e:
                                click.echo(f"⚠️ Check/cancel error: {e}")

                        # Check if we won (live mode auto-claim)
                        if auto_claim and not paper:
                            try:
                                condition_match = re.search(r'"conditionId":"([^"]+)"', html)
                                if condition_match:
                                    condition_id = condition_match.group(1)
                                    click.echo(f"   Condition ID: {condition_id[:20]}...")
                                    resp = requests.get(
                                        f'https://gamma-api.polymarket.com/markets?conditionId={condition_id}',
                                        timeout=30
                                    )
                                    market_resolved = False
                                    winning_outcome = None
                                    if resp.status_code == 200 and resp.json():
                                        market_data = resp.json()
                                        if market_data and len(market_data) > 0:
                                            market_resolved = market_data[0].get('resolved', False)
                                            outcome_prices = market_data[0].get('outcomePrices', [])
                                            if outcome_prices and len(outcome_prices) >= 2:
                                                if float(outcome_prices[0]) == 1.0:
                                                    winning_outcome = "Yes"
                                                elif float(outcome_prices[1]) == 1.0:
                                                    winning_outcome = "No"
                                    click.echo(f"   Market Resolved: {market_resolved}")
                                    click.echo(f"   Winning Outcome: {winning_outcome}")
                                    if not market_resolved:
                                        click.echo(f"   ⏳ Market not resolved yet, skipping claim...")
                                    else:
                                        config = load_config()
                                        rpc_url = config.get('rpc', 'https://polygon.drpc.org')
                                        from eth_account import Account
                                        account = Account.from_key(config.get('private_key'))
                                        wallet = account.address
                                        private_key = config.get('private_key')
                                        click.echo(f"🔄 Attempting auto-claim from {wallet[:10]}...")
                                        result = auto_claim_tokens(condition_id, wallet, rpc_url, private_key)
                                        if result.get('success'):
                                            click.echo(f"   ✅ Claimed! TX: {result.get('tx_hash', '')[:20]}...")
                                        else:
                                            click.echo(f"   ❌ Claim failed: {result.get('error', 'Unknown')}")
                                            click.echo(f"   💡 Please claim manually via Polymarket UI")
                                else:
                                    click.echo(f"⚠️ Could not find condition ID for claiming")
                            except Exception as e:
                                click.echo(f"⚠️ Auto-claim error: {e}")
                                click.echo(f"   💡 Please claim manually via Polymarket UI")
                        
                    # Reset for new market
                    order_placed = False
                    bought_token = None
                    entry_price = None
                    entry_side = None
                    entry_market_slug = None
                    last_displayed_slug = current_slug
                    up_high_duration = 0
                    down_high_duration = 0
                    sl_active_duration = 0
                
                # Get token IDs and prices
                if not use_gamma_prices:
                    result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                    html = result.stdout
                    
                    clob_match = re.search(r'"clobTokenIds":\[([^\]]+)\]', html)
                    if not clob_match:
                        time.sleep(2)
                        continue
                    
                    token_ids = [t.strip().strip('"') for t in clob_match.group(1).split(',')]
                    if len(token_ids) < 2:
                        time.sleep(2)
                        continue
                    
                    # Get prices from CLOB
                    price_up = client.get_last_trade_price(token_ids[0])
                    price_down = client.get_last_trade_price(token_ids[1])
                    
                    up_price = float(price_up.get('price', 0))
                    down_price = float(price_down.get('price', 0))
                else:
                    # Reset gamma flag for next iteration, title already set from gamma
                    use_gamma_prices = False
                
                # Get title (if not set from gamma)
                if not title:
                    title_match = re.search(r'"title"\s*:\s*"([^"]+)', html) if html else None
                    title = title_match.group(1) if title_match else current_slug
                timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")

                # Paper mode: save tick data
                save_tick(current_slug, up_price, down_price, current_ts)

                # Log every tick to file (not console - too noisy)
                bot_log(f"TICK {current_slug} | UP={up_price:.4f} DOWN={down_price:.4f} | up_dur={up_high_duration}s down_dur={down_high_duration}s | pos={'Y' if order_placed else 'N'}", echo=False)

                # Check conditions
                should_buy = False
                buy_side = None
                
                # Up price > bid_price for min_duration seconds
                if up_price > bid_price:
                    if last_up_price > bid_price:
                        up_high_duration += 2
                    else:
                        up_high_duration = 2
                    if up_high_duration >= min_duration:
                        should_buy = True
                        buy_side = "UP"
                else:
                    up_high_duration = 0
                
                # Down price > bid_price for min_duration seconds
                if down_price > bid_price:
                    if last_down_price > bid_price:
                        down_high_duration += 2
                    else:
                        down_high_duration = 2
                    if down_high_duration >= min_duration and not should_buy:
                        should_buy = True
                        buy_side = "DOWN"
                else:
                    down_high_duration = 0
                
                last_up_price = up_price
                last_down_price = down_price
                
                # Check stop loss if we have a real position (bought_token) AND same market
                # Only check if we're in the same market where we bought
                if (entry_price is not None and bought_token and order_placed and 
                    stop_loss_percent > 0):
                    
                    # FIRST: Check if we're still in the same market where we bought
                    if current_slug != entry_market_slug:
                        # Market changed - skip stop loss check (resolution handler will clean up)
                        pass
                    elif current_slug != last_displayed_slug:
                        # Market slug updated but same as entry - update display
                        last_displayed_slug = current_slug
                    else:
                        # Check stop loss on current price
                        loss_pct = 0
                        if entry_side == "UP":
                            loss_pct = (entry_price - up_price) / entry_price * 100
                        elif entry_side == "DOWN":
                            loss_pct = (entry_price - down_price) / entry_price * 100

                        if loss_pct >= stop_loss_percent:
                            sl_active_duration += 1

                            if sl_active_duration >= sl_min_duration:
                                if paper:
                                    # Paper mode: simulate stop-loss exit
                                    sell_price = up_price if entry_side == "UP" else down_price
                                    sl_trade = paper_close_trade(current_slug, sell_price, "stop_loss")
                                    pnl = (sell_price - entry_price) * bet_size
                                    bot_log(f"   📝 PAPER STOP LOSS: {loss_pct:.1f}% loss - {entry_side} sold @ ${sell_price:.3f} P&L: ${pnl:+.2f}")
                                    sl_trade_id = sl_trade["id"] if sl_trade else "?"
                                    tg.trade_closed_stop_loss(current_slug, entry_side, entry_price, sell_price, loss_pct, pnl, "Paper", trade_id=sl_trade_id)
                                    order_placed = False
                                    entry_price = None
                                    entry_side = None
                                    bought_token = None
                                    entry_market_slug = None
                                    sl_active_duration = 0
                                else:
                                    # Live mode: check position and sell
                                    has_pos, pos_size = has_filled_position(client, bought_token, bet_size)

                                    if not has_pos:
                                        click.echo(f"   ⚠️ No filled position found - skipping stop loss sell")
                                        order_placed = False
                                        entry_price = None
                                        entry_side = None
                                        bought_token = None
                                        sl_active_duration = 0
                                    else:
                                        bot_log(f"   🛑 STOP LOSS: {loss_pct:.1f}% loss for {sl_active_duration}s - Selling {entry_side} (position: {pos_size})!")

                                        # Sell at market price (FOK)
                                        try:
                                            if entry_side == "UP":
                                                sell_token = token_ids[0]
                                                sell_price = up_price
                                            else:
                                                sell_token = token_ids[1]
                                                sell_price = down_price

                                            from py_clob_client.clob_types import MarketOrderArgs
                                            order_args = MarketOrderArgs(
                                                token_id=sell_token,
                                                amount=float(bet_size),
                                                side="SELL",
                                                price=float(sell_price),
                                                order_type="FOK"
                                            )
                                            order_result = client.create_market_order(order_args)

                                            if order_result:
                                                click.echo(f"   ✅ SOLD at market price: ${sell_price:.3f}")
                                                sl_pnl = (sell_price - entry_price) * bet_size
                                                tg.trade_closed_stop_loss(current_slug, entry_side, entry_price, sell_price, loss_pct, sl_pnl, "Live")
                                            else:
                                                click.echo(f"   ⚠️ Order result: {order_result}")
                                        except Exception as e:
                                            click.echo(f"   ❌ Sell failed: {e}")

                                        order_placed = False
                                        entry_price = None
                                        entry_side = None
                                        bought_token = None
                                        sl_active_duration = 0
                            else:
                                if sl_active_duration == 1:
                                    bot_log(f"   ⚠️ STOP LOSS WARNING: {loss_pct:.1f}% loss - monitoring ({sl_active_duration}/{sl_min_duration}s)")
                        else:
                            sl_active_duration = 0
                
                # Display
                status = ""
                if buy_side == "UP" and not order_placed:
                    status = "🔔 UP signal!"
                elif buy_side == "DOWN" and not order_placed:
                    status = "🔔 DOWN signal!"
                
                # When market changes, reset status and title
                if current_slug != last_displayed_slug:
                    last_displayed_slug = current_slug
                    status = ""
                    title = ""
                
                click.echo(f"[{timestamp}] {title}")
                click.echo(f"   Up: ${up_price:.3f}  |  Down: ${down_price:.3f} {status}")
                
                # Calculate time remaining in current market
                time_remaining = (base_ts + 300) - int(time.time())
                
                # Place order if conditions met (but not if market about to end)
                if should_buy and buy_side and not order_placed and current_slug not in traded_slugs:
                    signal_duration = up_high_duration if buy_side == 'UP' else down_high_duration
                    bot_log(f"   🎯 SIGNAL: {buy_side} > ${bid_price} for {signal_duration}s | time_left={time_remaining}s")
                    tg.signal_found(current_slug, buy_side, up_price, down_price, signal_duration, bid_price, time_remaining, "Paper" if paper else "Live")
                    # Skip if market ending soon
                    if time_remaining <= time_buffer:
                        bot_log(f"   ⏭️ Skipping - market ends in {time_remaining}s (< {time_buffer}s)")
                        should_buy = False

                    if not should_buy:
                        continue

                    if paper:
                        # Paper trading: simulate the order
                        token_id = token_ids[0] if buy_side == "UP" else token_ids[1]
                        order_placed = True
                        bought_token = token_id
                        entry_price = bid_price
                        entry_side = buy_side
                        entry_market_slug = current_slug
                        traded_slugs.add(current_slug)
                        trade_id = paper_log_trade(current_slug, buy_side, bid_price, bet_size, token_id=token_id)
                        bot_log(f"   📝 PAPER ORDER: {buy_side} @ ${bid_price} (${bet_size})")
                        tg.trade_placed(trade_id, current_slug, buy_side, bid_price, bet_size, time_remaining, "Paper")
                    else:
                        # Live trading: place real order
                        try:
                            token_id = token_ids[0] if buy_side == "UP" else token_ids[1]
                            side = BUY  # Always BUY - whether UP or DOWN

                            order = OrderArgs(
                                token_id=token_id,
                                price=bid_price,
                                size=bet_size,
                                side=side
                            )

                            signed = client.create_order(order)
                            result = client.post_order(signed, OrderType.GTC)

                            if result.get('success'):
                                time.sleep(2)
                                has_pos, pos_size = has_filled_position(client, token_id, bet_size)

                                if has_pos:
                                    order_placed = True
                                    bought_token = token_id
                                    entry_price = bid_price
                                    entry_side = buy_side
                                    entry_market_slug = current_slug
                                    traded_slugs.add(current_slug)
                                    order_id = result.get('orderID', 'N/A')
                                    bot_log(f"   ✅ ORDER PLACED & FILLED: {buy_side} @ ${bid_price} (${bet_size}) [Size: {pos_size}]")
                                    click.echo(f"   📋 Order ID: {order_id[:20]}...")
                                    tg.trade_placed(None, current_slug, buy_side, bid_price, bet_size, time_remaining, "Live", order_id=order_id, filled_size=pos_size)
                                else:
                                    order_placed = False
                                    bought_token = None
                                    entry_price = None
                                    entry_side = None
                                    click.echo(f"   ⚠️ Order placed but NOT FILLED - will retry on next signal")
                            else:
                                order_placed = False
                                bought_token = None
                                entry_price = None
                                entry_side = None
                                bot_log(f"   ❌ Order failed: {result.get('errorMsg', 'Unknown error')}")

                        except Exception as e:
                            click.echo(f"   ❌ Order error: {e}")

                    # Reset after placing order
                    up_high_duration = 0
                    down_high_duration = 0

                time.sleep(2)

        except KeyboardInterrupt:
            # Flush any remaining tick data
            if paper:
                flush_ticks()
                for trade in paper_trades:
                    if trade["status"] == "open":
                        bot_log(f"   ⏳ Open trade {trade['slug']} {trade['side']} - will be resolved when market closes")
                print_paper_summary()
            bot_log("\n🛑 Stopped")

    except ImportError:
        click.echo("❌ py-clob-client not installed. Run: pip install py-clob-client")
    except Exception as e:
        if paper:
            flush_ticks()
            print_paper_summary()
        bot_log(f"❌ Error: {e}")

@cli.command()
def paper_report():
    """Show paper trading performance report"""
    journal_file = Path(__file__).parent / "trades.json"
    ticks_file = Path(__file__).parent / "backtest" / "ticks.json"

    if not journal_file.exists():
        click.echo("No trades.json found. Run 'btc-watch-order --paper' first.")
        return

    with open(journal_file, 'r') as f:
        data = json.load(f)

    trades = data.get("trades", [])
    if not trades:
        click.echo("No trades recorded yet.")
        return

    closed = [t for t in trades if t.get("status") == "closed"]
    open_trades = [t for t in trades if t.get("status") == "open"]

    click.echo(f"\n{'='*60}")
    click.echo(f"PAPER TRADING REPORT")
    click.echo(f"{'='*60}")
    click.echo(f"Total trades: {len(trades)} (Closed: {len(closed)}, Open: {len(open_trades)})")

    if closed:
        wins = [t for t in closed if (t.get("pnl") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl") or 0) < 0]
        total_pnl = sum(t.get("pnl", 0) for t in closed)
        win_rate = len(wins) / len(closed) * 100 if closed else 0

        click.echo(f"\nWins: {len(wins)}  |  Losses: {len(losses)}")
        click.echo(f"Win Rate: {win_rate:.1f}%")
        click.echo(f"Total P&L: ${total_pnl:+.2f}")

        if wins:
            click.echo(f"Avg Win: ${sum(t['pnl'] for t in wins)/len(wins):+.2f}")
        if losses:
            click.echo(f"Avg Loss: ${sum(t['pnl'] for t in losses)/len(losses):+.2f}")

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
        click.echo(f"Max Drawdown: ${max_dd:.2f}")

        # By side
        click.echo(f"\nBy Side:")
        for side in ["UP", "DOWN"]:
            side_trades = [t for t in closed if t.get("side", "").upper() == side]
            if side_trades:
                s_wins = sum(1 for t in side_trades if (t.get("pnl") or 0) > 0)
                s_pnl = sum(t.get("pnl", 0) for t in side_trades)
                click.echo(f"  {side}: {len(side_trades)} trades, {s_wins} wins "
                          f"({s_wins/len(side_trades)*100:.0f}%), P&L: ${s_pnl:+.2f}")

        click.echo(f"\nRecent Trades:")
        click.echo(f"  {'TIME':<20} {'SIDE':<5} {'ENTRY':>6} {'EXIT':>6} {'PNL':>8} {'REASON':<10}")
        for t in closed[-15:]:
            ts = t.get("timestamp", "")[:19]
            result = "W" if (t.get("pnl") or 0) > 0 else "L"
            click.echo(f"  {ts:<20} {result} {t.get('side','?'):<4} ${t.get('entry_price',0):.2f} "
                      f"${t.get('exit_price',0):.2f} ${t.get('pnl',0):>+7.2f} "
                      f"{t.get('exit_reason',''):<10}")

    # Tick stats
    if ticks_file.exists():
        with open(ticks_file, 'r') as f:
            ticks = json.load(f)
        click.echo(f"\nTick data: {len(ticks)} data points collected")


if __name__ == "__main__":
    cli()
