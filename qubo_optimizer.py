"""
qubo_optimizer.py
QUBO (Quadratic Unconstrained Binary Optimization) for portfolio optimization.

Selects optimal coin combination from candidates to maximize return while 
minimizing correlation risk.

Mathematical Formulation:
H = -∑(α_i · x_i) + λ·∑(ρ_ij · x_i · x_j) + P·(∑x_i - n)²

Where:
- α_i = expected return of coin i
- ρ_ij = correlation between coin i and j
- n = target number of coins
- λ = risk aversion parameter
- P = penalty coefficient
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import json
import os

from loguru import logger

# Try to import QUBO libraries, fallback to greedy if not available
try:
    from pyqubo import Array, Binary, Constraint
    from dimod import SimulatedAnnealingSampler
    QUBO_AVAILABLE = True
except ImportError:
    QUBO_AVAILABLE = False
    logger.warning("pyqubo/dimod not available. Using greedy fallback.")


class QUBOPortfolioOptimizer:
    """
    QUBO-based portfolio optimizer for coin selection.
    """
    
    def __init__(
        self,
        risk_aversion: float = 1.3,
        penalty: float = 100.0,
        target_coins: int = 8,
        use_greedy_fallback: bool = True
    ):
        """
        Initialize QUBO optimizer.
        
        Args:
            risk_aversion: Lambda parameter (higher = more risk averse)
            penalty: Penalty for not meeting target count
            target_coins: Desired number of coins in portfolio
            use_greedy_fallback: Use greedy algorithm if QUBO fails
        """
        self.risk_aversion = risk_aversion
        self.penalty = penalty
        self.target_coins = target_coins
        self.use_greedy_fallback = use_greedy_fallback
        
    def calculate_correlation_matrix(
        self, 
        price_data: pd.DataFrame, 
        lookback_days: int = 30
    ) -> pd.DataFrame:
        """
        Calculate correlation matrix from historical price data.
        
        Args:
            price_data: DataFrame with closing prices for each coin
            lookback_days: Number of days to use for correlation
        
        Returns:
            Correlation matrix between coins
        """
        if price_data is None or price_data.empty:
            logger.warning("No price data for correlation calculation")
            return pd.DataFrame()
        
        # Use last N days
        if len(price_data) > lookback_days:
            price_data = price_data.iloc[-lookback_days:]
        
        # Calculate daily returns
        returns = price_data.pct_change().dropna()
        
        # Calculate correlation
        corr_matrix = returns.corr()
        
        logger.info(f"Calculated correlation matrix for {len(corr_matrix)} coins")
        return corr_matrix
    
    def build_qubo_hamiltonian(
        self,
        coins: List[str],
        expected_returns: Dict[str, float],
        correlation_matrix: pd.DataFrame,
        target_coins: int = None
    ) -> Tuple[object, List]:
        """
        Build QUBO Hamiltonian for portfolio optimization.
        
        Args:
            coins: List of coin names
            expected_returns: Dict of coin -> expected return
            correlation_matrix: Correlation matrix between coins
            target_coins: Target number of coins (uses self.target_coins if None)
        
        Returns:
            Hamiltonian object and binary variables list
        """
        if target_coins is None:
            target_coins = self.target_coins
        
        n = len(coins)
        
        # Create binary variables for each coin
        x = Array.create('x', shape=n, vartype='BINARY')
        
        # Normalize expected returns to [0, 1] range
        returns_list = [expected_returns.get(coin, 0.0) for coin in coins]
        max_return = max(returns_list) if returns_list else 1.0
        min_return = min(returns_list) if returns_list else 0.0
        range_return = max_return - min_return if max_return != min_return else 1.0
        
        normalized_returns = [
            (r - min_return) / range_return for r in returns_list
        ]
        
        # Term 1: Negative return (maximize return)
        # H1 = -∑ α_i · x_i
        return_term = -sum(normalized_returns[i] * x[i] for i in range(n))
        
        # Term 2: Risk (minimize correlation)
        # H2 = λ · ∑ ρ_ij · x_i · x_j (for i < j)
        risk_term = 0
        for i in range(n):
            for j in range(i + 1, n):
                coin_i = coins[i]
                coin_j = coins[j]
                
                if coin_i in correlation_matrix.index and coin_j in correlation_matrix.columns:
                    corr = correlation_matrix.loc[coin_i, coin_j]
                    if not pd.isna(corr):
                        risk_term += corr * x[i] * x[j]
        
        risk_term = self.risk_aversion * risk_term
        
        # Term 3: Cardinality constraint (exactly n coins)
        # H3 = P · (∑ x_i - n)²
        cardinality_term = self.penalty * (sum(x) - target_coins) ** 2
        
        # Total Hamiltonian
        H = return_term + risk_term + cardinality_term
        
        return H, x
    
    def solve_qubo(
        self,
        coins: List[str],
        expected_returns: Dict[str, float],
        correlation_matrix: pd.DataFrame,
        target_coins: int = None,
        num_reads: int = 500
    ) -> List[str]:
        """
        Solve QUBO using simulated annealing.
        
        Args:
            coins: List of candidate coins
            expected_returns: Dict of expected returns
            correlation_matrix: Correlation matrix
            target_coins: Target number of coins
            num_reads: Number of reads for simulated annealing
        
        Returns:
            List of selected coins
        """
        if not QUBO_AVAILABLE:
            logger.warning("QUBO libraries not available, using greedy fallback")
            return self._greedy_selection(coins, expected_returns, target_coins)
        
        try:
            # Build Hamiltonian
            H, x_vars = self.build_qubo_hamiltonian(
                coins, expected_returns, correlation_matrix, target_coins
            )
            
            # Compile to QUBO model
            model = H.compile()
            qubo, offset = model.to_qubo()
            
            # Solve with simulated annealing
            sampler = SimulatedAnnealingSampler()
            sampleset = sampler.sample_qubo(qubo, num_reads=num_reads)
            
            # Get best solution
            best_sample = sampleset.first.sample
            
            # Extract selected coins
            selected_coins = []
            for i, coin in enumerate(coins):
                var_name = f'x[{i}]'
                if best_sample.get(var_name, 0) == 1:
                    selected_coins.append(coin)
            
            logger.info(f"QUBO selected {len(selected_coins)} coins: {selected_coins}")
            
            # Adjust if not enough coins selected
            if len(selected_coins) < (target_coins or self.target_coins):
                logger.warning(f"Only {len(selected_coins)} coins selected, adding top performers")
                selected_coins = self._fill_to_target(
                    selected_coins, coins, expected_returns, target_coins
                )
            
            return selected_coins
            
        except Exception as e:
            logger.error(f"QUBO optimization failed: {e}")
            if self.use_greedy_fallback:
                return self._greedy_selection(coins, expected_returns, target_coins)
            return coins[:self.target_coins] if target_coins else coins[:8]
    
    def _greedy_selection(
        self,
        coins: List[str],
        expected_returns: Dict[str, float],
        target_coins: int = None
    ) -> List[str]:
        """
        Greedy selection based on expected returns (fallback when QUBO fails).
        """
        if target_coins is None:
            target_coins = self.target_coins
        
        # Sort coins by expected return
        sorted_coins = sorted(
            coins,
            key=lambda c: expected_returns.get(c, 0),
            reverse=True
        )
        
        selected = sorted_coins[:target_coins]
        logger.info(f"Greedy selected {len(selected)} coins: {selected}")
        return selected
    
    def _fill_to_target(
        self,
        selected: List[str],
        all_coins: List[str],
        expected_returns: Dict[str, float],
        target_coins: int = None
    ) -> List[str]:
        """
        Fill selected coins to target number using top performers.
        """
        if target_coins is None:
            target_coins = self.target_coins
        
        remaining = [c for c in all_coins if c not in selected]
        remaining_sorted = sorted(
            remaining,
            key=lambda c: expected_returns.get(c, 0),
            reverse=True
        )
        
        needed = target_coins - len(selected)
        selected.extend(remaining_sorted[:needed])
        
        return selected
    
    def calculate_portfolio_metrics(
        self,
        selected_coins: List[str],
        expected_returns: Dict[str, float],
        correlation_matrix: pd.DataFrame
    ) -> Dict:
        """
        Calculate portfolio metrics after selection.
        
        Returns:
            Dict with portfolio expected return, risk, diversification score
        """
        if not selected_coins:
            return {'expected_return': 0, 'portfolio_risk': 0, 'diversification': 0}
        
        # Expected return (average)
        returns = [expected_returns.get(c, 0) for c in selected_coins]
        avg_return = np.mean(returns)
        
        # Portfolio risk (average correlation)
        risks = []
        for i in range(len(selected_coins)):
            for j in range(i + 1, len(selected_coins)):
                coin_i = selected_coins[i]
                coin_j = selected_coins[j]
                
                if coin_i in correlation_matrix.index and coin_j in correlation_matrix.columns:
                    corr = correlation_matrix.loc[coin_i, coin_j]
                    if not pd.isna(corr):
                        risks.append(corr)
        
        avg_risk = np.mean(risks) if risks else 0.5
        
        # Diversification score (lower correlation = better)
        diversification = 1 - avg_risk
        
        return {
            'expected_return': avg_return,
            'portfolio_risk': avg_risk,
            'diversification': diversification,
            'n_coins': len(selected_coins)
        }


def run_qubo_optimization(
    candidate_coins: List[str],
    expected_returns: Dict[str, float],
    price_data: Optional[pd.DataFrame] = None,
    correlation_matrix: Optional[pd.DataFrame] = None,
    target_coins: int = 8,
    risk_aversion: float = 1.3
) -> Tuple[List[str], Dict]:
    """
    Main function to run QUBO portfolio optimization.
    
    Args:
        candidate_coins: List of coins to consider
        expected_returns: Dict of expected returns for each coin
        price_data: DataFrame with historical prices (optional if correlation_matrix provided)
        correlation_matrix: Pre-calculated correlation matrix (optional)
        target_coins: Desired number of coins
        risk_aversion: Risk aversion parameter
    
    Returns:
        Tuple of (selected_coins, metrics)
    """
    optimizer = QUBOPortfolioOptimizer(
        risk_aversion=risk_aversion,
        target_coins=target_coins
    )
    
    # Get correlation matrix
    if correlation_matrix is None and price_data is not None:
        correlation_matrix = optimizer.calculate_correlation_matrix(price_data)
    
    if correlation_matrix is None or correlation_matrix.empty:
        logger.warning("No correlation data available, using greedy selection only")
        selected = optimizer._greedy_selection(candidate_coins, expected_returns, target_coins)
        metrics = {'expected_return': np.mean([expected_returns.get(c, 0) for c in selected]), 
                   'portfolio_risk': 0.5, 'diversification': 0.5, 'n_coins': len(selected)}
        return selected, metrics
    
    # Ensure all candidate coins are in correlation matrix
    available_coins = [c for c in candidate_coins if c in correlation_matrix.index]
    if len(available_coins) < len(candidate_coins):
        logger.warning(f"Missing correlation data for {set(candidate_coins) - set(available_coins)}")
    
    if not available_coins:
        logger.error("No coins with correlation data")
        return [], {}
    
    # Run QUBO optimization
    selected = optimizer.solve_qubo(
        available_coins,
        expected_returns,
        correlation_matrix,
        target_coins
    )
    
    # Calculate metrics
    metrics = optimizer.calculate_portfolio_metrics(
        selected, expected_returns, correlation_matrix
    )
    
    logger.info(f"QUBO Optimization complete: {selected}")
    logger.info(f"Portfolio metrics: {metrics}")
    
    return selected, metrics


# ============================================================
# Simplified version for quick use
# ============================================================

def simple_portfolio_selection(
    coins: List[str],
    expected_returns: Dict[str, float],
    top_n: int = 8
) -> List[str]:
    """
    Simple top-N selection by expected return (no correlation).
    Use this as baseline or when QUBO libraries are not available.
    """
    sorted_coins = sorted(coins, key=lambda c: expected_returns.get(c, 0), reverse=True)
    return sorted_coins[:top_n]