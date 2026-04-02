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
        result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', '-H', 'Accept: text/html', 'https://polymarket.com/crypto'], capture_output=True, text=True, timeout=15)
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
        
        if not current_slug:
            current_slug = f"btc-updown-5m-{unique_ts[-1]}"
        
        # Get token IDs from market page
        result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, timeout=15)
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
        result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', '-H', 'Accept: text/html', 'https://polymarket.com/crypto'], capture_output=True, text=True, timeout=15)
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
        
        if not current_slug:
            current_slug = f"btc-updown-5m-{unique_ts[-1]}"
        
        # Get token IDs
        result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, timeout=15)
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
                result = subprocess.run(['curl', '-s', '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', '-H', 'Accept: text/html', 'https://polymarket.com/crypto'], capture_output=True, text=True, timeout=30)
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
                
                if not current_slug:
                    current_slug = f"btc-updown-5m-{unique_ts[-1]}"
                
                # Get token IDs
                result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, timeout=30)
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
def btc_watch_order(bid_price, min_duration, bet_size, auto_claim, stop_loss):
    """Watch BTC prices and place bid when conditions are met
    
    Options can be set via config.json or command line
    """
    import subprocess
    import re
    from datetime import datetime, timezone
    import time
    
    # Load config for default values
    config = load_config()
    btc_config = config.get('btc_watch_order', {})
    
    # Use command line args if provided, otherwise use config
    bid_price = bid_price if bid_price is not None else btc_config.get('bid_price', 0.9)
    min_duration = min_duration if min_duration is not None else btc_config.get('min_duration', 5)
    bet_size = bet_size if bet_size is not None else btc_config.get('bet_size', 10.0)
    auto_claim = auto_claim if auto_claim is not None else btc_config.get('auto_claim', False)
    stop_loss_percent = stop_loss if stop_loss is not None else btc_config.get('stop_loss_percent', 45)
    sl_min_duration = config.get('sl_min_duration', 5)  # Read from root level
    time_buffer = btc_config.get('time_buffer', 15)
    import subprocess
    import re
    from datetime import datetime, timezone
    import time
    
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
        
        click.echo(f"📊 Watching BTC Up/Down with auto-order... (Press Ctrl+C to stop)")
        click.echo(f"   Bid threshold: > ${bid_price} for {min_duration} seconds")
        click.echo(f"   Bet size: ${bet_size}")
        click.echo(f"   Auto-claim: {'Enabled' if auto_claim else 'Disabled'}")
        click.echo("-" * 60)
        
        # Initialize client
        config = load_config()
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
                     f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, timeout=15)
        
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
        # Stop loss tracking
        entry_price = None
        entry_side = None
        entry_market_slug = None  # Track which market we bought in
        sl_active_duration = 0  # Track how long stop loss has been triggered
        
        try:
            while True:
                now = datetime.now(timezone.utc)
                current_ts = int(now.timestamp())
                
                # Calculate current market timestamp directly (no website needed!)
                base_ts = (current_ts // 300) * 300  # Round down to 5 minutes
                current_slug = f'btc-updown-5m-{base_ts}'
                
                # Debug: print market change
                if last_displayed_slug and current_slug != last_displayed_slug:
                    print(f"\n🔄 Market: {last_displayed_slug} → {current_slug}")
                    last_displayed_slug = current_slug  # Update after printing
                
                # Try to get market data from website
                result = subprocess.run(
                    ['curl', '-s', 
                     '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                     '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                     '-H', 'Accept-Language: en-US,en;q=0.5',
                     '-H', 'Connection: keep-alive',
                     '-H', 'Upgrade-Insecure-Requests: 1',
                     f'https://polymarket.com/event/{current_slug}'],
                    capture_output=True, text=True, timeout=30
                )
                
                # If website returns checkpoint, try Gamma API as fallback
                use_clob_fallback = 'checkpoint' in result.stdout.lower() or 'vercel' in result.stdout.lower()
                
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
                            import json as json_module
                            prices = json_module.loads(outcome_prices)
                            
                            # Use lastTradePrice or bestBid/bestAsk for real prices
                            last_price = market_data.get('lastTradePrice')
                            best_bid = market_data.get('bestBid')
                            best_ask = market_data.get('bestAsk')
                            
                            # Get token IDs for CLOB prices
                            clob_token_ids = market_data.get('clobTokenIds', '[]')
                            token_ids = json_module.loads(clob_token_ids) if clob_token_ids else []
                            
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
                        click.echo(f"   ⚠️ Gamma API error: {e}")
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
                if order_placed and bought_token and last_displayed_slug:
                    if current_slug != last_displayed_slug:
                        # New market - check if old market resolved
                        click.echo(f"\n🔄 Market changed from {last_displayed_slug} to {current_slug}")
                        
                        # Check if there's an unfilled order from previous market
                        if order_placed and bought_token:
                            try:
                                # Get open orders
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
                        
                        # Check if we won
                        if auto_claim:
                            try:
                                # Get condition ID from market
                                condition_match = re.search(r'"conditionId":"([^"]+)"', html)
                                if condition_match:
                                    condition_id = condition_match.group(1)
                                    click.echo(f"   Condition ID: {condition_id[:20]}...")
                                    
                                    # Check if market is resolved first
                                    # Get the closed status from market
                                    import json
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
                                            
                                            # Determine winning outcome
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
                                        # Get wallet and config
                                        config = load_config()
                                        rpc_url = config.get('rpc', 'https://polygon.drpc.org')
                                        
                                        # Use correct wallet derived from private key
                                        from eth_account import Account
                                        account = Account.from_key(config.get('private_key'))
                                        wallet = account.address
                                        private_key = config.get('private_key')
                                        
                                        # Try to claim
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
                        current_slug = current_slug  # Already updated
                
                # Get token IDs and prices
                if not use_gamma_prices:
                    result = subprocess.run(['curl', '-s', f'https://polymarket.com/event/{current_slug}'], capture_output=True, text=True, timeout=30)
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
                # Get title (if not set from gamma)
                if not title:
                    title_match = re.search(r'"title"\s*:\s*"([^"]+)', html)
                    title = title_match.group(1) if title_match else current_slug
                timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                
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
                    if down_high_duration >= min_duration:
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
                        # Market changed - reset position tracking (don't check stop loss on old market)
                        click.echo(f"   🔄 Market changed from {entry_market_slug} to {current_slug} - resetting position")
                        order_placed = False
                        entry_price = None
                        entry_side = None
                        bought_token = None
                        entry_market_slug = None
                    elif current_slug != last_displayed_slug:
                        # Market slug updated but same as entry - update display
                        last_displayed_slug = current_slug
                    else:
                        # Check if market is already resolved (won or lost)
                        market_result = subprocess.run(
                            ['curl', '-s', f'https://polymarket.com/event/{current_slug}'],
                            capture_output=True, text=True, timeout=30
                        )
                        html = market_result.stdout
                        
                        closed_match = re.search(r'"closed":(true|false)', html)
                        price_match = re.search(r'"outcomePrices"\s*:\s*\[([^\]]+)\]', html)
                        
                        if closed_match and price_match:
                            is_closed = closed_match.group(1) == 'true'
                            prices = [p.strip().strip('"') for p in price_match.group(1).split(',')]
                            
                            if is_closed:
                                # Market resolved - check outcome
                                won = False
                                if entry_side == "UP" and prices[0] == "1":
                                    won = True
                                elif entry_side == "DOWN" and prices[1] == "1":
                                    won = True
                                
                                if won:
                                    click.echo(f"   🎉 Market resolved: {entry_side} WON!")
                                else:
                                    click.echo(f"   💸 Market resolved: We LOST")
                                # Reset position
                                order_placed = False
                                entry_price = None
                                entry_side = None
                                bought_token = None
                            else:
                                # Market not resolved - check stop loss
                                loss_pct = 0
                                if entry_side == "UP":
                                    loss_pct = (entry_price - up_price) / entry_price * 100
                                elif entry_side == "DOWN":
                                    loss_pct = (entry_price - down_price) / entry_price * 100
                                
                                if loss_pct >= stop_loss_percent:
                                    # Stop loss triggered - check duration
                                    sl_active_duration += 1
                                    
                                    if sl_active_duration >= sl_min_duration:
                                        # ตรวจสอบก่อนว่ามี position จริงหรือไม่
                                        has_pos, pos_size = has_filled_position(client, bought_token, bet_size)
                                        
                                        if not has_pos:
                                            click.echo(f"   ⚠️ No filled position found - skipping stop loss sell")
                                            order_placed = False
                                            entry_price = None
                                            entry_side = None
                                            bought_token = None
                                            sl_active_duration = 0
                                        else:
                                            click.echo(f"   🛑 STOP LOSS: {loss_pct:.1f}% loss for {sl_active_duration}s - Selling {entry_side} (position: {pos_size})!")
                                        
                                        # Sell at market price (FOK)
                                        try:
                                            if entry_side == "UP":
                                                sell_token = token_ids[0]  # UP token
                                                sell_price = up_price
                                            else:
                                                sell_token = token_ids[1]  # DOWN token
                                                sell_price = down_price
                                            
                                            # Create market order (FOK)
                                            from py_clob_client.clob_types import MarketOrderArgs
                                            order_args = MarketOrderArgs(
                                                token_id=sell_token,
                                                amount=float(bet_size),
                                                side="SELL",
                                                price=float(sell_price),
                                                order_type="FOK"
                                            )
                                            order_result = client.create_market_order(order_args)
                                            
                                            # Check result
                                            if order_result:
                                                click.echo(f"   ✅ SOLD at market price: ${sell_price:.3f}")
                                            else:
                                                click.echo(f"   ⚠️ Order result: {order_result}")
                                        except Exception as e:
                                            click.echo(f"   ❌ Sell failed: {e}")
                                        
                                        # Reset after stop loss
                                        order_placed = False
                                        entry_price = None
                                        entry_side = None
                                        bought_token = None
                                        sl_active_duration = 0
                                    else:
                                        # Still in grace period - just show warning
                                        if sl_active_duration == 1:
                                            click.echo(f"   ⚠️ STOP LOSS WARNING: {loss_pct:.1f}% loss - monitoring ({sl_active_duration}/{sl_min_duration}s)")
                                else:
                                    # Reset duration if not in stop loss zone
                                    sl_active_duration = 0
                
                # Display
                status = ""
                if buy_side == "UP" and not order_placed:
                    status = "🔔 UP signal!"
                elif buy_side == "DOWN" and not order_placed:
                    status = "🔔 DOWN signal!"
                
                # When market changes, reset status
                if current_slug != last_displayed_slug:
                    last_displayed_slug = current_slug
                    status = ""  # Reset status when market changes
                
                click.echo(f"[{timestamp}] {title}")
                click.echo(f"   Up: ${up_price:.3f}  |  Down: ${down_price:.3f} {status}")
                
                # Calculate time remaining in current market
                time_remaining = (base_ts + 300) - int(time.time())
                
                # Place order if conditions met (but not if market about to end)
                if should_buy and buy_side and not order_placed:
                    # Skip if market ending soon
                    if time_remaining <= time_buffer:
                        click.echo(f"   ⏭️ Skipping - market ends in {time_remaining}s (< {time_buffer}s)")
                        should_buy = False
                    
                    if not should_buy:
                        continue
                    
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
                            # รอเช็คว่า order fill จริงหรือไม่ (รอสักครู่)
                            time.sleep(2)
                            
                            # ตรวจสอบว่า order fill แล้วหรือยัง
                            has_pos, pos_size = has_filled_position(client, token_id, bet_size)
                            
                            if has_pos:
                                order_placed = True
                                bought_token = token_id
                                # Record entry price for stop loss
                                entry_price = bid_price
                                entry_side = buy_side
                                entry_market_slug = current_slug  # Track which market we bought in
                                click.echo(f"   ✅ ORDER PLACED & FILLED: {buy_side} @ ${bid_price} (${bet_size}) [Size: {pos_size}]")
                                click.echo(f"   📋 Order ID: {result.get('orderID', 'N/A')[:20]}...")
                            else:
                                order_placed = False
                                bought_token = None
                                entry_price = None
                                entry_side = None
                                click.echo(f"   ⚠️ Order placed but NOT FILLED - will retry on next signal")
                        else:
                            order_placed = False  # Reset if failed
                            bought_token = None
                            entry_price = None
                            entry_side = None
                            click.echo(f"   ❌ Order failed: {result.get('errorMsg', 'Unknown error')}")
                            
                    except Exception as e:
                        click.echo(f"   ❌ Order error: {e}")
                    
                    # Reset after placing order
                    up_high_duration = 0
                    down_high_duration = 0
                
                time.sleep(2)
                
        except KeyboardInterrupt:
            click.echo("\n🛑 Stopped")
            
    except ImportError:
        click.echo("❌ py-clob-client not installed. Run: pip install py-clob-client")
    except Exception as e:
        click.echo(f"❌ Error: {e}")

if __name__ == "__main__":
    cli()
