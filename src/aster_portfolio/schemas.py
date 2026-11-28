"""Portfolio policy and result contracts."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioProfile(StrictModel):
    profile_id: str
    description: str
    stock_target: float = Field(gt=0.0, le=1.0)
    name_cap: float = Field(gt=0.0, le=0.03)
    max_gross: float = Field(default=1.60, gt=0.0, le=2.0)
    target_beta: float = Field(default=0.0, ge=-0.90, le=0.90)
    beta_tolerance: float = Field(default=0.20, gt=0.0, le=0.20)
    cash_buffer: float = Field(default=0.20, ge=0.0, lt=1.0)
    futures_margin_rate: float = Field(default=0.12, gt=0.0, le=1.0)
    risk_aversion: float = Field(default=4.0, gt=0.0)
    beta_penalty: float = Field(default=2.0, ge=0.0)
    stock_trade_cost: float = Field(default=0.0008, ge=0.0)
    futures_trade_cost: float = Field(default=0.0001, ge=0.0)
    max_one_way_turnover: float = Field(default=0.30, gt=0.0, le=2.0)
    covariance_shrinkage: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_budget(self) -> "PortfolioProfile":
        if self.stock_target > 1.0 - self.cash_buffer + 1e-12:
            raise ValueError("stock_target leaves less than the required cash buffer")
        if self.stock_target > self.max_gross:
            raise ValueError("stock_target exceeds max_gross")
        return self


class OptimizationDiagnostics(StrictModel):
    solver_status: str
    objective_value: float
    stock_weight: float
    futures_short_weight: float
    gross_exposure: float
    estimated_net_beta: float
    cash_weight: float
    margin_required: float
    one_way_turnover: float
    estimated_stock_cost: float
    estimated_futures_cost: float
    max_name_weight: float
    industry_exposures: dict[str, float] = Field(default_factory=dict)
    industry_active_exposures: dict[str, float] = Field(default_factory=dict)
    constraint_slack: dict[str, float]


class OptimizationResult(StrictModel):
    signal_date: date
    profile_id: str
    stock_weights: dict[str, float]
    futures_short_weight: float
    diagnostics: OptimizationDiagnostics


def demo_profiles() -> dict[str, PortfolioProfile]:
    """Showcase-only profiles with a wider beta range.

    They are deliberately kept out of :func:`default_profiles` so research
    Council packets and existing fixtures never see them.  The deterministic
    backtest resolves schedule profile IDs against :func:`approved_profiles`.
    """
    profiles = [
        PortfolioProfile(
            profile_id="demo_short",
            description="Showcase reenactment: maximum short-beta profile",
            stock_target=0.55,
            name_cap=0.03,
            max_gross=1.60,
            target_beta=-0.50,
            beta_tolerance=0.10,
            risk_aversion=6.0,
            beta_penalty=1.0,
            max_one_way_turnover=0.30,
        ),
        PortfolioProfile(
            profile_id="demo_neutral",
            description="Showcase reenactment: market-neutral profile",
            stock_target=0.65,
            name_cap=0.03,
            target_beta=0.0,
            beta_tolerance=0.08,
            risk_aversion=4.0,
            beta_penalty=1.0,
            max_one_way_turnover=0.25,
        ),
        PortfolioProfile(
            profile_id="demo_long",
            description="Showcase reenactment: maximum long-beta profile",
            stock_target=0.90,
            name_cap=0.03,
            max_gross=1.00,
            cash_buffer=0.08,
            target_beta=0.50,
            beta_tolerance=0.10,
            risk_aversion=2.0,
            beta_penalty=1.0,
            max_one_way_turnover=0.30,
        ),
        PortfolioProfile(
            profile_id="demo_short_small",
            description="Showcase reenactment: moderate short-beta profile",
            stock_target=0.70,
            name_cap=0.03,
            max_gross=1.55,
            target_beta=-0.30,
            beta_tolerance=0.08,
            risk_aversion=5.0,
            beta_penalty=1.5,
            max_one_way_turnover=0.25,
        ),
        PortfolioProfile(
            profile_id="demo_cash",
            description="Showcase reenactment: near-cash neutral profile",
            stock_target=0.10,
            name_cap=0.03,
            max_gross=0.20,
            cash_buffer=0.85,
            target_beta=0.0,
            beta_tolerance=0.05,
            risk_aversion=4.0,
            beta_penalty=2.0,
            max_one_way_turnover=0.10,
        ),
        PortfolioProfile(
            profile_id="demo_short_low",
            description="Showcase reenactment: low short-beta profile",
            stock_target=0.72,
            name_cap=0.03,
            max_gross=1.55,
            target_beta=-0.20,
            beta_tolerance=0.07,
            risk_aversion=6.0,
            beta_penalty=1.8,
            max_one_way_turnover=0.22,
        ),
        PortfolioProfile(
            profile_id="demo_long_low",
            description="Showcase reenactment: low long-beta profile",
            stock_target=0.78,
            name_cap=0.03,
            max_gross=1.00,
            cash_buffer=0.18,
            target_beta=0.20,
            beta_tolerance=0.07,
            risk_aversion=3.5,
            beta_penalty=1.8,
            max_one_way_turnover=0.22,
        ),
        PortfolioProfile(
            profile_id="demo_short_mid",
            description="Showcase reenactment: mid short-beta profile",
            stock_target=0.62,
            name_cap=0.03,
            max_gross=1.58,
            target_beta=-0.40,
            beta_tolerance=0.09,
            risk_aversion=5.5,
            beta_penalty=1.2,
            max_one_way_turnover=0.28,
        ),
        PortfolioProfile(
            profile_id="demo_long_mid",
            description="Showcase reenactment: mid long-beta profile",
            stock_target=0.86,
            name_cap=0.03,
            max_gross=1.00,
            cash_buffer=0.12,
            target_beta=0.40,
            beta_tolerance=0.09,
            risk_aversion=2.5,
            beta_penalty=1.2,
            max_one_way_turnover=0.28,
        ),
        PortfolioProfile(
            profile_id="demo_long_small",
            description="Showcase reenactment: moderate long-beta profile",
            stock_target=0.82,
            name_cap=0.03,
            max_gross=1.00,
            cash_buffer=0.15,
            target_beta=0.30,
            beta_tolerance=0.08,
            risk_aversion=3.0,
            beta_penalty=1.5,
            max_one_way_turnover=0.25,
        ),
    ]
    return {profile.profile_id: profile for profile in profiles}


def approved_profiles() -> dict[str, PortfolioProfile]:
    return {**default_profiles(), **demo_profiles()}


def default_profiles() -> dict[str, PortfolioProfile]:
    profiles = [
        PortfolioProfile(
            profile_id="defensive",
            description="Lower stock budget with a modest short-beta hedge",
            stock_target=0.65,
            name_cap=0.03,
            target_beta=-0.15,
            beta_tolerance=0.05,
            risk_aversion=8.0,
            beta_penalty=5.0,
            max_one_way_turnover=0.18,
        ),
        PortfolioProfile(
            profile_id="balanced",
            description="Default research profile under the design constraints",
            stock_target=0.75,
            name_cap=0.03,
            target_beta=0.0,
            beta_tolerance=0.08,
            risk_aversion=4.0,
            beta_penalty=3.0,
            max_one_way_turnover=0.25,
        ),
        PortfolioProfile(
            profile_id="opportunistic",
            description="Maximum approved stock budget with a mild long-beta tilt",
            stock_target=0.80,
            name_cap=0.03,
            target_beta=0.15,
            beta_tolerance=0.08,
            risk_aversion=2.0,
            beta_penalty=1.5,
            max_one_way_turnover=0.35,
        ),
    ]
    return {profile.profile_id: profile for profile in profiles}
