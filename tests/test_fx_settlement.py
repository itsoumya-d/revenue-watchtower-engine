"""Unit tests for Multi-Currency FX Settlement and Conversion Waterfall Engine."""

from decimal import Decimal
from watchtower.fx_settlement import (
    FXQuote,
    FXSettlementEngine,
)


def test_standard_eur_to_usd_conversion_waterfall():
    engine = FXSettlementEngine(default_scheme_bps=20, default_interchange_bps=80)
    quote = FXQuote(
        base_currency="EUR",
        target_currency="USD",
        rate=Decimal("1.0850"),
        spread_bps=100,  # 1.00%
        quote_timestamp=1000,
        max_age_seconds=60,
    )

    result = engine.convert_and_settle(
        amount_cents=10000,  # €100.00
        quote=quote,
        current_timestamp=1020,
    )

    assert result.is_valid is True
    assert result.source_amount_cents == 10000
    assert result.target_gross_cents == 10850  # $108.50
    assert result.spread_fee_cents == 109     # 1% of 10850 = 108.5 -> 109
    assert result.scheme_fee_cents == 22      # 0.2% of 10850 = 21.7 -> 22
    assert result.interchange_fee_cents == 87 # 0.8% of 10850 = 86.8 -> 87

    # Exact conservation assertion
    deductions = result.spread_fee_cents + result.scheme_fee_cents + result.interchange_fee_cents
    assert result.merchant_net_cents + deductions == result.target_gross_cents
    assert result.merchant_net_cents == 10632  # $106.32


def test_expired_quote_rejects_settlement():
    engine = FXSettlementEngine()
    quote = FXQuote(
        base_currency="EUR",
        target_currency="SGD",
        rate=Decimal("1.4500"),
        spread_bps=150,
        quote_timestamp=1000,
        max_age_seconds=30,
    )

    result = engine.convert_and_settle(
        amount_cents=5000,
        quote=quote,
        current_timestamp=1035,  # 35s > 30s
    )

    assert result.is_valid is False
    assert result.rejection_reason == "FX quote has expired"
    assert result.target_gross_cents == 0


def test_invalid_negative_amount_rejects_cleanly():
    engine = FXSettlementEngine()
    quote = FXQuote(
        base_currency="EUR",
        target_currency="USD",
        rate=Decimal("1.0800"),
        spread_bps=100,
        quote_timestamp=1000,
    )

    result = engine.convert_and_settle(
        amount_cents=-500,
        quote=quote,
        current_timestamp=1010,
    )

    assert result.is_valid is False
    assert "positive integer" in (result.rejection_reason or "")
