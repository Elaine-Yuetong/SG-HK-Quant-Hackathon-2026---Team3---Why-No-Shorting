# QUBO-Enhanced Adaptive Trading Bot

## Team3-Why No Shorting | HKU Quant Hackathon 2026

A multi‑layer quantitative trading system that combines **per‑coin strategy optimization**, **QUBO portfolio selection**, **dynamic time filtering**, and **adaptive risk management** to achieve robust performance across diverse market conditions.

---

## 📌 Overview

This bot is designed for the Roostoo trading competition. Instead of using a one‑size‑fits‑all strategy, it selects the best‑performing strategy for each coin based on 90‑day backtest results, dynamically adjusts trading intensity by hour using historical performance, optimizes the portfolio with QUBO (Quadratic Unconstrained Binary Optimization), and protects capital with multiple risk layers.

---

## 🏗️ System Architecture

```
         Layer 1: 5 Base Strategies
Dual MA | MACD | RSI | Bollinger Bands | Volume MA
                     ↓
    Layer 2: Per‑Coin Strategy Selection
Each coin uses its best strategy from 90‑day backtest
                     ↓
        Layer 3: Dynamic Time Filter
Combines 90‑day + 7‑day data → hourly position weights
                     ↓
     Layer 4: QUBO Portfolio Optimization
Selects optimal coin set: maximize return, minimize correlation
                     ↓
          Layer 5: Risk Management
Trailing stop | Daily loss limit | Total loss limit | Drawdown protection
                     ↓
                 Execution
```

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           QUBO Trading Bot                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │
│  │   Layer 1       │    │   Layer 2       │    │   Layer 3       │          │
│  │   5 Base        │───▶│   Per-Coin      │───▶│   Dynamic       │          │
│  │   Strategies    │    │   Strategy      │    │   Time Filter   │          │
│  │                 │    │   Selection     │    │                 │          │
│  │ • Dual MA       │    │                 │    │ 90-day + 7-day  │          │
│  │ • MACD          │    │ Each coin uses  │    │ hourly returns  │          │
│  │ • RSI           │    │ its best from   │    │ → dynamic       │          │
│  │ • Bollinger     │    │ 90-day backtest │    │   position size │          │
│  │ • Volume MA     │    │                 │    │                 │          │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘          │
│           │                      │                      │                   │
│           ▼                      ▼                      ▼                   │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    Layer 4: QUBO Optimization                   │        │
│  │  H = –∑αᵢxᵢ + λ·∑ρᵢⱼxᵢxⱼ + P·(∑xᵢ – n)²                       │        │
│  │  Maximize return │ Minimize correlation │ Exactly n coins       │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                      │                                      │
│                                      ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                    Layer 5: Risk Management                     │        │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │        │
│  │  │Trailing Stop │ │Daily Loss    │ │Total Loss    │            │        │
│  │  │10% from peak │ │5% → pause    │ │15% → kill    │            │        │
│  │  └──────────────┘ └──────────────┘ └──────────────┘            │        │
│  │  ┌──────────────┐ ┌──────────────┐                              │        │
│  │  │Drawdown      │ │Cooldown      │                              │        │
│  │  │10% → halve   │ │2h after kill│                              │        │
│  │  └──────────────┘ └──────────────┘                              │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                      │                                      │
│                                      ▼                                      │
│                          ┌─────────────────────┐                           │
│                          │     Execution       │                           │
│                          │  Roostoo API v3     │                           │
│                          │  MARKET orders      │                           │
│                          └─────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Key Innovations

### 1. Per‑Coin Strategy Selection
Not all coins behave the same. We backtested 5 strategies on 66 coins over 90 days and assigned each coin the strategy that gave the best risk‑adjusted return.

| Coin | Best Strategy | Parameters | 90‑Day Return | Trades | Risk Level |
|------|---------------|------------|---------------|--------|------------|
| XPL/USD | Dual MA | [10,20] | +125.03% | 7,250 | High |
| PENGU/USD | Dual MA | [10,20] | +124.51% | 7,148 | High |
| PUMP/USD | Dual MA | [10,20] | +106.07% | 7,224 | High |
| STO/USD | Dual MA | [25,30] | +66.22% | 6,587 | Medium |
| VIRTUAL/USD | Dual MA | [10,20] | +38.28% | 7,258 | Medium |
| TAO/USD | Dual MA | [40,150] | +37.28% | 1,095 | Medium |
| ZEC/USD | Dual MA | [25,120] | +37.12% | 1,478 | Medium |
| TRX/USD | Dual MA | [40,200] | +26.06% | 859 | Low |
| BTC/USD | Dual MA | [40,120] | +2.35% | 1,296 | Low |
| PAXG/USD | Dual MA | [5,40] | +25.07% | 5,132 | Low |
| FLOKI/USD | MACD | [5,20,12] | +566.49% | 13,520 | High |
| ETH/USD | MACD | [5,30,10] | +69.39% | 13,702 | Medium |
| BNB/USD | MACD | [15,20,9] | +111.27% | 9,922 | Medium |
| HBAR/USD | MACD | [10,20,15] | +133.66% | 9,683 | Medium |
| 1000CHEEMS/USD | RSI | [7,30,70] | +122.51% | 3,425 | High |
| WIF/USD | RSI | [7,30,70] | +1796.59% | 2,943 | Extreme |
| EIGEN/USD | RSI | [7,30,70] | +2833.22% | 2,428 | Extreme |

**Key insight**: Dual MA works well for most coins (85% beat buy‑and‑hold), while RSI and MACD deliver explosive returns on specific high‑volatility coins. Each coin uses its own best strategy — no one‑size‑fits‑all.

### 2. Data-Driven Strategy Design

Rather than guessing which strategy works best, we let the data decide.

We backtested **5 strategies × 66 coins × all parameter combinations** over 90 days of 1‑minute data — over **20,000 individual backtests**. This rigorous approach revealed:

- **Dual MA is the most consistent**: 85% of coins beat buy‑and‑hold, with average loss of only -0.84% in a -26% market.
- **MACD and RSI are explosive but selective**: They deliver 100–2800% returns on specific coins (FLOKI, 1000CHEEMS, WIF, EIGEN), but underperform on most others.
- **No universal strategy exists**: A one‑size‑fits‑all approach would have lost money. Each coin needs its own.

The final configuration (17 coins, each with its best strategy) is not an opinion — it’s the direct output of exhaustive backtesting.

### 3. Dynamic Time Filter
Instead of fixed US/Asia session rules, we compute **hourly returns** using both **90‑day long‑term** and **7‑day short‑term** data. The final weight for each hour is a dynamic combination:

- High volatility → lower weight
- Stable positive returns → higher weight

This allows the bot to **automatically adapt** to changing market micro‑structures.

### 4. QUBO Portfolio Optimization
We formulate portfolio selection as a QUBO problem:

H = –∑(αᵢ·xᵢ) + λ·∑(ρᵢⱼ·xᵢ·xⱼ) + P·(∑xᵢ – n)²

- `αᵢ` = expected return of coin i
- `ρᵢⱼ` = correlation between coin i and j
- `n` = target number of coins
- `λ` = risk aversion

The optimizer selects a set of coins that **maximizes expected return while minimizing correlation** – mathematically ensuring diversification.

### 5. Trailing Stop Loss
Unlike a fixed stop loss, the trailing stop follows the highest price ever reached:

- Price rises → stop line rises
- Price falls → stop line stays
- Trigger when price drops 10% from peak

This locks in profits while still letting winners run.

### 6. Adaptive MA Periods
The Dual MA strategy dynamically adjusts its periods based on recent volatility:

- High volatility (`>2%`) → longer periods (filter noise)
- Low volatility (`<0.5%`) → shorter periods (react faster)

This makes the strategy **self‑adjusting** to changing market regimes.

### 6. Weighted Average Cost Stop Loss
When multiple entries occur, the stop loss is calculated on the **weighted average cost**, not just the last entry price. This prevents the stop line from being artificially lowered by adding positions at lower prices.


---


## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Elaine-Yuetong/SG-HK-Quant-Hackathon-2026---Team3---Why-No-Shorting.git
cd SG-HK-Quant-Hackathon-2026---Team3---Why-No-Shorting
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure API keys
Edit config.py and set your Roostoo API credentials:
```bash
ROOSTOO_API_KEY = "your_api_key"
ROOSTOO_SECRET_KEY = "your_secret_key"
```

### 4. Run the bot
```bash
python3 main.py
```
The dashboard will be available at http://localhost:8050.

### 5. Run with tmux (AWS EC2)
```bash
tmux
python3 main.py
# Ctrl+B then D to detach
```


## 🛡️ Risk Management Layers

| Layer | Description | Trigger | Action |
|-------|-------------|---------|--------|
| **Trailing Stop** | Price drops 10% from historical peak | `drawdown ≥ 10%` | Sell entire position |
| **Daily Loss Limit** | Loss exceeds 5% of day-start capital | `daily_loss > 5%` | Pause trading for 2 hours |
| **Total Loss Limit** | Loss exceeds 15% of initial capital | `total_loss > 15%` | Kill switch → stop all trading |
| **Drawdown Protection** | Portfolio drawdown from peak | `drawdown ≥ 10%` | Reduce position size by 50% |
| **Cooldown** | After kill switch activation | Auto‑trigger | No trading for 2 hours |

### How They Work Together

Price rises → Trailing stop moves up
↓
Price drops 10% from peak → Trailing stop triggers → Sell
↓
If daily loss >5% → Pause trading (cooldown)
↓
If total loss >15% → Kill switch (permanent stop)


This multi‑layer approach ensures:
- **Profit protection**: Trailing stop locks in gains
- **Risk control**: Daily and total loss limits prevent catastrophic drawdowns
- **Adaptive sizing**: Drawdown protection reduces exposure during unfavorable conditions
- **Cool‑down period**: Prevents emotional revenge trading after losses


## 📁 Project Structure

```
├── main.py                 # Main trading loop
├── bot_executor.py         # Order execution & portfolio rebalancing
├── strategies.py           # 5 base strategies + dynamic time filter
├── per_coin_config.py      # Per‑coin strategy configuration
├── qubo_optimizer.py       # QUBO portfolio optimization
├── risk_manager.py         # Multi‑layer risk management
├── time_weight.py          # Dynamic hourly weight calculation
├── dashboard.py            # Flask monitoring dashboard
├── config.py               # API keys and global settings
├── historical_data/        # 90‑day historical kline data
└── requirements.txt        # Python dependencies
```

## 👥 Team Contribution

| Member | Contribution |
|--------|--------------|
| Yuetong Wei(Elaine)| Main trading logic, strategy integration, QUBO optimization, risk management, dynamic time filter, dashboard, deployment, testing, documentation |
| Dorjderem Namsraijav | Data pipeline: `binance_symbols.py`, `config.py`, `download_history.py`, `roostoo_client.py` – fetching and validating historical data |



## 📅 Competition Period
First Round: March 14 – March 27, 2026

## 🙏 Acknowledgments
Roostoo for providing the trading API and competition platform

Binance for historical data access

Built with ❤️ for the HKU Web3 Quant Trading Hackathon 2026.
