"""Deterministic forecasting, optimization and backtesting for Aster.

Heavy optimization dependencies are loaded lazily so the data-only environment
can reuse factor calculations without importing CVXPY.
"""

__all__ = ["PortfolioOptimizer", "PortfolioProfile"]


def __getattr__(name: str):
    if name == "PortfolioOptimizer":
        from .optimizer import PortfolioOptimizer

        return PortfolioOptimizer
    if name == "PortfolioProfile":
        from .schemas import PortfolioProfile

        return PortfolioProfile
    raise AttributeError(name)
