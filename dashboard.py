"""
dashboard.py
Flask dashboard for monitoring bot status on AWS EC2.
Shows:
- Real-time portfolio value
- Current positions
- Signal status per coin
- Risk status (kill switch, drawdown)
- Recent trades
- Performance charts
"""

import json
import os
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List, Optional

from flask import Flask, render_template_string, jsonify, request
from loguru import logger

# Import bot components (will be set by main.py)
_bot = None
_risk_manager = None
_state_manager = None
_executor = None

# ============================================================
# Flask App Setup
# ============================================================

app = Flask(__name__)

# Optional basic auth for EC2 (protect from public access)
VALID_USERS = {
    os.getenv('DASHBOARD_USER', 'admin'): os.getenv('DASHBOARD_PASSWORD', 'quant123')
}

def require_auth():
    """Optional authentication for dashboard"""
    if os.getenv('DASHBOARD_AUTH', 'true').lower() == 'true':
        auth = request.authorization
        if not auth or VALID_USERS.get(auth.username) != auth.password:
            return False
    return True

# ============================================================
# HTML Template
# ============================================================

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Trading Bot Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        /* Header */
        .header {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 20px 30px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }
        
        .header h1 {
            font-size: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .header h1 span {
            background: #3b82f6;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
        }
        
        .refresh-btn {
            background: #3b82f6;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        
        .refresh-btn:hover {
            background: #2563eb;
            transform: scale(1.02);
        }
        
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }
        
        .stat-card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 20px;
            transition: all 0.2s;
        }
        
        .stat-card:hover {
            border-color: #3b82f6;
            transform: translateY(-2px);
        }
        
        .stat-title {
            font-size: 14px;
            color: #94a3b8;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #f1f5f9;
        }
        
        .stat-sub {
            font-size: 12px;
            color: #64748b;
            margin-top: 8px;
        }
        
        .positive { color: #22c55e; }
        .negative { color: #ef4444; }
        
        /* Cards */
        .card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
        }
        
        .card h2 {
            font-size: 18px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }
        
        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th, td {
            text-align: left;
            padding: 12px 8px;
            border-bottom: 1px solid #334155;
        }
        
        th {
            color: #94a3b8;
            font-weight: 500;
            font-size: 12px;
        }
        
        .signal-buy {
            color: #22c55e;
            font-weight: bold;
        }
        
        .signal-sell {
            color: #ef4444;
            font-weight: bold;
        }
        
        .signal-hold {
            color: #f59e0b;
        }
        
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        }
        
        .badge-active { background: #22c55e20; color: #22c55e; }
        .badge-warning { background: #f59e0b20; color: #f59e0b; }
        .badge-danger { background: #ef444420; color: #ef4444; }
        
        .chart-container {
            height: 300px;
            margin-top: 16px;
        }
        
        .two-columns {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }
        
        @media (max-width: 768px) {
            .two-columns {
                grid-template-columns: 1fr;
            }
        }
        
        .footer {
            text-align: center;
            padding: 20px;
            color: #64748b;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>
                🤖 QUBO Trading Bot
                <span>LIVE</span>
            </h1>
            <button class="refresh-btn" onclick="loadAllData()">🔄 Refresh</button>
        </div>
        
        <!-- Stats Grid -->
        <div class="stats-grid" id="statsGrid">
            <div class="stat-card">
                <div class="stat-title">💰 Portfolio Value</div>
                <div class="stat-value" id="portfolioValue">--</div>
                <div class="stat-sub" id="portfolioChange">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">📈 Total Return</div>
                <div class="stat-value" id="totalReturn">--</div>
                <div class="stat-sub">Since start</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">🛡️ Risk Status</div>
                <div class="stat-value" id="riskStatus">--</div>
                <div class="stat-sub" id="riskReason">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">🔄 Active Signals</div>
                <div class="stat-value" id="activeSignals">--</div>
                <div class="stat-sub">Buy / Sell / Hold</div>
            </div>
        </div>
        
        <!-- Main Content -->
        <div class="two-columns">
            <div class="card">
                <h2>📊 Portfolio Performance</h2>
                <div class="chart-container">
                    <canvas id="performanceChart"></canvas>
                </div>
            </div>
            
            <div class="card">
                <h2>🎯 Current Positions</h2>
                <div style="overflow-x: auto;">
                    <table id="positionsTable">
                        <thead>
                            <tr><th>Coin</th><th>Quantity</th><th>Current Price</th><th>Value</th><th>Weight</th></tr>
                        </thead>
                        <tbody><tr><td colspan="5">Loading...</td></tr></tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>📡 Signal Status</h2>
            <div style="overflow-x: auto;">
                <table id="signalsTable">
                    <thead>
                        <tr><th>Coin</th><th>Strategy</th><th>Signal</th><th>Multiplier</th><th>Action</th></tr>
                    </thead>
                    <tbody><tr><td colspan="5">Loading...</td></tr></tbody>
                </table>
            </div>
        </div>
        
        <div class="card">
            <h2>🔄 Recent Trades</h2>
            <div style="overflow-x: auto;">
                <table id="tradesTable">
                    <thead>
                        <tr><th>Time</th><th>Coin</th><th>Action</th><th>Quantity</th><th>Price</th><th>Status</th></tr>
                    </thead>
                    <tbody><tr><td colspan="6">Loading...</td></tr></tbody>
                </table>
            </div>
        </div>
        
        <div class="footer">
            Last updated: <span id="lastUpdate">--</span> | 
            Iteration: <span id="iteration">--</span> |
            Total Trades: <span id="totalTrades">--</span>
        </div>
    </div>
    
    <script>
        let performanceChart;
        
        async function loadAllData() {
            try {
                const [portfolio, signals, trades, history] = await Promise.all([
                    fetch('/api/portfolio').then(r => r.json()),
                    fetch('/api/signals').then(r => r.json()),
                    fetch('/api/trades').then(r => r.json()),
                    fetch('/api/history').then(r => r.json())
                ]);
                
                updateStats(portfolio);
                updatePositions(portfolio);
                updateSignals(signals);
                updateTrades(trades);
                updateChart(history);
                
                document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
                document.getElementById('iteration').textContent = portfolio.iteration || '--';
                document.getElementById('totalTrades').textContent = portfolio.total_trades || '--';
            } catch (error) {
                console.error('Error loading data:', error);
            }
        }
        
        function updateStats(portfolio) {
            const value = portfolio.total_value || 0;
            const initial = portfolio.initial_capital || 1000000;
            const returnPct = ((value - initial) / initial * 100).toFixed(2);
            
            document.getElementById('portfolioValue').textContent = `$${value.toLocaleString()}`;
            document.getElementById('totalReturn').innerHTML = `${returnPct > 0 ? '+' : ''}${returnPct}%`;
            document.getElementById('totalReturn').className = returnPct >= 0 ? 'stat-value positive' : 'stat-value negative';
            
            const risk = portfolio.risk_status || 'ACTIVE';
            document.getElementById('riskStatus').innerHTML = `<span class="badge badge-${risk === 'ACTIVE' ? 'active' : (risk === 'WARNING' ? 'warning' : 'danger')}">${risk}</span>`;
            document.getElementById('riskReason').textContent = portfolio.risk_reason || 'OK';
            
            document.getElementById('activeSignals').textContent = `${portfolio.buy_signals || 0} / ${portfolio.sell_signals || 0} / ${portfolio.hold_signals || 0}`;
        }
        
        function updatePositions(portfolio) {
            const positions = portfolio.positions || [];
            const html = positions.map(p => `
                <tr>
                    <td>${p.coin}</td>
                    <td>${p.quantity.toFixed(6)}</td>
                    <td>$${p.price.toFixed(2)}</td>
                    <td>$${p.value.toLocaleString()}</td>
                    <td>${(p.weight * 100).toFixed(1)}%</td>
                </tr>
            `).join('');
            
            document.querySelector('#positionsTable tbody').innerHTML = html || '<tr><td colspan="5">No positions</td></tr>';
        }
        
        function updateSignals(signals) {
            const signalList = signals.signals || [];
            const html = signalList.map(s => {
                let signalClass = '';
                let signalText = '';
                if (s.signal > 0) { signalClass = 'signal-buy'; signalText = 'BUY'; }
                else if (s.signal < 0) { signalClass = 'signal-sell'; signalText = 'SELL'; }
                else { signalClass = 'signal-hold'; signalText = 'HOLD'; }
                
                return `
                    <tr>
                        <td>${s.coin}</td>
                        <td>${s.strategy}</td>
                        <td class="${signalClass}">${signalText}</td>
                        <td>${(s.multiplier * 100).toFixed(0)}%</td>
                        <td>${s.signal > 0 ? '✅' : (s.signal < 0 ? '🔴' : '⚪')}</td>
                    </tr>
                `;
            }).join('');
            
            document.querySelector('#signalsTable tbody').innerHTML = html || '<tr><td colspan="5">No signals</td></tr>';
        }
        
        function updateTrades(trades) {
            const tradeList = trades.trades || [];
            const html = tradeList.slice(0, 20).map(t => `
                <tr>
                    <td>${t.time || '--'}</td>
                    <td>${t.coin}</td>
                    <td class="${t.action === 'BUY' ? 'signal-buy' : 'signal-sell'}">${t.action}</td>
                    <td>${t.quantity.toFixed(6)}</td>
                    <td>$${t.price.toFixed(2)}</td>
                    <td>${t.success ? '✅' : '❌'}</td>
                </tr>
            `).join('');
            
            document.querySelector('#tradesTable tbody').innerHTML = html || '<tr><td colspan="6">No trades</td></tr>';
        }
        
        function updateChart(history) {
            const labels = history.labels || [];
            const values = history.values || [];
            
            if (performanceChart) performanceChart.destroy();
            
            const ctx = document.getElementById('performanceChart').getContext('2d');
            performanceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Portfolio Value',
                        data: values,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#e2e8f0' } }
                    },
                    scales: {
                        x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                        y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } }
                    }
                }
            });
        }
        
        // Auto-refresh every 10 seconds
        setInterval(loadAllData, 10000);
        document.addEventListener('DOMContentLoaded', loadAllData);
    </script>
</body>
</html>
"""


# ============================================================
# Dashboard Data Provider
# ============================================================

class DashboardDataProvider:
    """Provides real-time data from bot components."""
    
    def __init__(self):
        self.bot = None
        self.risk_manager = None
        self.state_manager = None
        self.executor = None
        self.performance_history: List[Dict] = []
        self.trade_history: List[Dict] = []
    
    def set_bot(self, bot):
        self.bot = bot
    
    def set_risk_manager(self, rm):
        self.risk_manager = rm
    
    def set_state_manager(self, sm):
        self.state_manager = sm
    
    def set_executor(self, ex):
        self.executor = ex
    
    def add_performance_point(self, value: float):
        self.performance_history.append({
            'timestamp': datetime.now(),
            'value': value
        })
        # Keep last 100 points
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]
    
    def add_trade(self, trade: Dict):
        self.trade_history.insert(0, trade)
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[:100]
    
    def get_portfolio_data(self) -> Dict:
        """Get current portfolio data."""
        try:
            from bot_executor import get_current_portfolio, get_current_prices
            
            holdings, cash = get_current_portfolio()
            all_coins = list(holdings.keys())
            prices = get_current_prices(all_coins)
            
            total_value = cash
            positions = []
            
            for coin, qty in holdings.items():
                if coin in prices:
                    price = prices[coin]
                    value = qty * price
                    total_value += value
                    positions.append({
                        'coin': coin,
                        'quantity': qty,
                        'price': price,
                        'value': value,
                        'weight': 0  # will calculate after total
                    })
            
            # Calculate weights
            for p in positions:
                p['weight'] = p['value'] / total_value if total_value > 0 else 0
            
            # Get risk status
            risk_status = 'ACTIVE'
            risk_reason = 'OK'
            if self.risk_manager:
                if self.risk_manager.is_killed:
                    risk_status = 'KILLED'
                    risk_reason = self.risk_manager.kill_reason or 'Unknown'
                elif self.risk_manager.cooldown_until and datetime.now() < self.risk_manager.cooldown_until:
                    risk_status = 'COOLDOWN'
                    risk_reason = f"Until {self.risk_manager.cooldown_until.strftime('%H:%M')}"
            
            return {
                'total_value': total_value,
                'initial_capital': self.risk_manager.initial_capital if self.risk_manager else 1_000_000,
                'cash': cash,
                'positions': positions,
                'risk_status': risk_status,
                'risk_reason': risk_reason,
                'iteration': self.state_manager.state.get('iteration_count', 0) if self.state_manager else 0,
                'total_trades': self.state_manager.state.get('total_trades', 0) if self.state_manager else 0,
                'buy_signals': 0,
                'sell_signals': 0,
                'hold_signals': 0
            }
        except Exception as e:
            logger.error(f"Error getting portfolio data: {e}")
            return {'total_value': 0, 'positions': [], 'error': str(e)}
    
    def get_signals_data(self) -> Dict:
        """Get current signals."""
        signals = []
        buy_count = sell_count = hold_count = 0
        
        if self.state_manager:
            last_signals = self.state_manager.state.get('last_signals', {})
            for coin, (signal, mult) in last_signals.items():
                strategy = 'dual_ma'  # Default
                if coin in COIN_STRATEGY_CONFIG:
                    strategy = COIN_STRATEGY_CONFIG[coin].get('strategy', 'dual_ma')
                
                signals.append({
                    'coin': coin,
                    'strategy': strategy,
                    'signal': signal,
                    'multiplier': mult
                })
                
                if signal > 0:
                    buy_count += 1
                elif signal < 0:
                    sell_count += 1
                else:
                    hold_count += 1
        
        return {
            'signals': signals,
            'buy_count': buy_count,
            'sell_count': sell_count,
            'hold_count': hold_count
        }
    
    def get_trades_data(self) -> Dict:
        """Get recent trades."""
        return {'trades': self.trade_history[:50]}
    
    def get_history_data(self) -> Dict:
        """Get performance history for chart."""
        return {
            'labels': [h['timestamp'].strftime('%H:%M') for h in self.performance_history[-50:]],
            'values': [h['value'] for h in self.performance_history[-50:]]
        }


# ============================================================
# Flask Routes
# ============================================================

_data_provider = DashboardDataProvider()

@app.route('/')
def index():
    if not require_auth():
        return 'Unauthorized', 401
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route('/api/portfolio')
def api_portfolio():
    return jsonify(_data_provider.get_portfolio_data())

@app.route('/api/signals')
def api_signals():
    return jsonify(_data_provider.get_signals_data())

@app.route('/api/trades')
def api_trades():
    return jsonify(_data_provider.get_trades_data())

@app.route('/api/history')
def api_history():
    return jsonify(_data_provider.get_history_data())

@app.route('/api/health')
def api_health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0'
    })


# ============================================================
# Start Function
# ============================================================

def start_dashboard(
    bot=None,
    risk_manager=None,
    state_manager=None,
    executor=None,
    host: str = '0.0.0.0',
    port: int = 8050,
    debug: bool = False
):
    """
    Start the dashboard server.
    Call this from main.py in a separate thread.
    
    Usage:
        from dashboard import start_dashboard
        import threading
        dashboard_thread = threading.Thread(
            target=start_dashboard,
            args=(bot, risk_manager, state_manager, executor),
            daemon=True
        )
        dashboard_thread.start()
    """
    global _bot, _risk_manager, _state_manager, _executor
    
    _data_provider.set_bot(bot)
    _data_provider.set_risk_manager(risk_manager)
    _data_provider.set_state_manager(state_manager)
    _data_provider.set_executor(executor)
    
    logger.info(f"🚀 Starting dashboard on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


# ============================================================
# Testing
# ============================================================

if __name__ == "__main__":
    # Mock data for testing
    class MockRiskManager:
        initial_capital = 1_000_000
        is_killed = False
        cooldown_until = None
    
    class MockStateManager:
        def __init__(self):
            self.state = {
                'iteration_count': 42,
                'total_trades': 156,
                'last_signals': {
                    'BTC': [1, 0.8],
                    'ETH': [0, 1.0],
                    'SOL': [-1, 0.5]
                }
            }
    
    _data_provider.set_risk_manager(MockRiskManager())
    _data_provider.set_state_manager(MockStateManager())
    
    # Add mock history
    for i in range(30):
        _data_provider.add_performance_point(1_000_000 + i * 5000)
    
    start_dashboard(debug=True)