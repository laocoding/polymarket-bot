# Implementation Plan: Polymarket High-Frequency Trading Bot Upgrade

This document outlines the technical and strategic roadmap to upgrade `poly-cli.py` from a reactive scraper-based bot to a competitive, low-latency automated trading system.

## Phase 1: Core Engine Refactoring (Performance & Stability)
*Goal: Eliminate bottlenecks and switch to event-driven architecture.*

1.  **Switch to Asyncio:**
    * Replace the synchronous `while True` loop with a native `asyncio` event loop.
    * Use `aiohttp` for any remaining REST calls to prevent blocking the main thread.
2.  **WebSocket Integration (CLOB):**
    * Abandon the `curl` subprocess approach for price fetching.
    * Implement `ClobClient` WebSockets to receive real-time order book updates and trade events. This reduces latency from ~2000ms to <100ms.
3.  **Direct API Integration:**
    * Use the Polymarket Gamma API for market discovery and metadata instead of scraping HTML strings with Regex.

## Phase 2: Information Edge (Multi-Exchange Signals)
*Goal: Gain a predictive advantage by monitoring global market leaders.*

1.  **CEX Spot Feed (Binance/Bybit):**
    * Implement a dedicated WebSocket listener for `BTCUSDT` spot prices from Binance.
    * **The Logic:** Since Polymarket's BTC 5m markets resolve based on external spot prices, price movements often happen on Binance 100-500ms before they are reflected in Polymarket liquidity.
2.  **Cross-Exchange Arbitrage Signal:**
    * Trigger an entry when the Binance price moves significantly outside the "implied price" range currently trading on Polymarket.

## Phase 3: Quantitative Strategy & Risk Management
*Goal: Move beyond fixed-price bidding to probability-based execution.*

1.  **Dynamic Pricing Model:**
    * Instead of hardcoding a `0.90` bid, calculate the "Fair Value" of the contract based on current BTC volatility and time remaining (Theta).
2.  **Kelly Criterion Bet Sizing:**
    * Implement dynamic sizing: `Size = (WinProb * Odds - 1) / (Odds - 1)`.
    * Only bet large amounts when the Edge (Fair Value vs. Market Price) is high.
3.  **Execution Optimization:**
    * Use "Fill-or-Kill" (FOK) or "Immediate-or-Cancel" (IOC) orders to avoid being partially filled at bad prices during high volatility.

## Phase 4: Infrastructure & Low Latency
*Goal: Minimize the physical distance between the bot and the exchange.*

1.  **Server Colocation:**
    * Deploy the bot on a VPS in **AWS Tokyo (ap-northeast-1)** or **GCP Tokyo**. Most Polygon validators and exchange endpoints have high proximity here.
2.  **Dockerization:**
    * Containerize the bot for consistent environment deployment and easier scaling across multiple market pairs (e.g., ETH, SOL, BTC).
3.  **Health Monitoring:**
    * Integrate a Telegram/Discord webhook for critical errors (e.g., Low Gas, API disconnects, Stop-Loss triggers).

## Phase 5: Backtesting & Paper Trading Enhancements
1.  **High-Fidelity Ticks:**
    * Store ticks with 100ms granularity (including Binance vs. Polymarket spread) to identify exactly where the "Edge" was lost or gained.
2.  **Slippage Simulation:**
    * Improve the Paper Trading mode to account for liquidity depth—simulating that a $100 bet might move the price from $0.90 to $0.92.