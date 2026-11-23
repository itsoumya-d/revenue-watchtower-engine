"""Multi-Currency FX Settlement and Cross-Border Conversion Waterfall Engine.

Computes exact integer minor-unit cross-border currency conversions, applies
basis-points spread margins, and executes deterministic multi-tier fee waterfalls
with strict balance conservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class FXQuote:
    base_currency: str
    target_currency: str
    rate: Decimal
    spread_bps: int  # Basis points (1 bps = 0.01%)
    quote_timestamp: int
    max_age_seconds: int = 60


@dataclass(frozen=True)
class FXSettlementResult:
    source_amount_cents: int
    target_gross_cents: int
    spread_fee_cents: int
    scheme_fee_cents: int
    interchange_fee_cents: int
    merchant_net_cents: int
    effective_rate: Decimal
    is_valid: bool
    rejection_reason: str | None = None


class FXSettlementEngine:
    """Deterministic multi-currency settlement and fee waterfall calculator."""

    def __init__(self, default_scheme_bps: int = 25, default_interchange_bps: int = 80):
        self.default_scheme_bps = default_scheme_bps
        self.default_interchange_bps = default_interchange_bps

    def convert_and_settle(
        self,
        amount_cents: int,
        quote: FXQuote,
        current_timestamp: int,
        scheme_bps: int | None = None,
        interchange_bps: int | None = None,
    ) -> FXSettlementResult:
        if amount_cents <= 0:
            return FXSettlementResult(
                source_amount_cents=amount_cents,
                target_gross_cents=0,
                spread_fee_cents=0,
                scheme_fee_cents=0,
                interchange_fee_cents=0,
                merchant_net_cents=0,
                effective_rate=Decimal("0.0"),
                is_valid=False,
                rejection_reason="Amount must be positive integer cents",
            )

        if current_timestamp - quote.quote_timestamp > quote.max_age_seconds:
            return FXSettlementResult(
                source_amount_cents=amount_cents,
                target_gross_cents=0,
                spread_fee_cents=0,
                scheme_fee_cents=0,
                interchange_fee_cents=0,
                merchant_net_cents=0,
                effective_rate=quote.rate,
                is_valid=False,
                rejection_reason="FX quote has expired",
            )

        # 1. Base conversion using exact Decimal arithmetic
        raw_target = (Decimal(amount_cents) * quote.rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        target_gross = int(raw_target)

        # 2. Compute fee waterfalls in target minor units
        s_bps = scheme_bps if scheme_bps is not None else self.default_scheme_bps
        i_bps = interchange_bps if interchange_bps is not None else self.default_interchange_bps

        spread_fee = int(
            (Decimal(target_gross) * Decimal(quote.spread_bps) / Decimal(10000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        scheme_fee = int(
            (Decimal(target_gross) * Decimal(s_bps) / Decimal(10000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        interchange_fee = int(
            (Decimal(target_gross) * Decimal(i_bps) / Decimal(10000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

        total_deductions = spread_fee + scheme_fee + interchange_fee
        merchant_net = target_gross - total_deductions

        effective_rate = (Decimal(merchant_net) / Decimal(amount_cents)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        return FXSettlementResult(
            source_amount_cents=amount_cents,
            target_gross_cents=target_gross,
            spread_fee_cents=spread_fee,
            scheme_fee_cents=scheme_fee,
            interchange_fee_cents=interchange_fee,
            merchant_net_cents=merchant_net,
            effective_rate=effective_rate,
            is_valid=True,
            rejection_reason=None,
        )
