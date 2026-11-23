from __future__ import annotations

import pytest
from watchtower.policy_spec import (
    PolicyProductCompiler,
    PolicyProductSpec,
)


@pytest.fixture
def sample_spec() -> PolicyProductSpec:
    return PolicyProductSpec(
        product_id="commercial-cyber-risk",
        version="1.4.0",
        base_premium_cents=100000,  # $1,000.00 base
        min_age=18,
        max_age=70,
        allowed_risk_tiers=("low", "standard", "elevated"),
        deductible_discounts_bps={
            50000: 250,   # $500 deductible -> 2.5% discount
            100000: 500,  # $1000 deductible -> 5.0% discount
            250000: 1200, # $2500 deductible -> 12.0% discount
        },
        required_metadata_fields=("tax_id", "industry_code"),
    )


def test_compiler_generates_stable_sha256_fingerprint(sample_spec: PolicyProductSpec):
    compiled1 = PolicyProductCompiler.compile(sample_spec)
    compiled2 = PolicyProductCompiler.compile(sample_spec)

    assert len(compiled1.sha256_fingerprint) == 64
    assert compiled1.sha256_fingerprint == compiled2.sha256_fingerprint
    assert "commercial-cyber-risk" in compiled1.canonical_definition


def test_compiler_rejects_invalid_spec_bounds():
    with pytest.raises(ValueError, match="strictly positive"):
        PolicyProductCompiler.compile(
            PolicyProductSpec(
                product_id="bad",
                version="1.0.0",
                base_premium_cents=0,
                min_age=18,
                max_age=65,
                allowed_risk_tiers=("standard",),
                deductible_discounts_bps={1000: 100},
                required_metadata_fields=(),
            )
        )

    with pytest.raises(ValueError, match="Invalid age bounds"):
        PolicyProductCompiler.compile(
            PolicyProductSpec(
                product_id="bad-age",
                version="1.0.0",
                base_premium_cents=5000,
                min_age=70,
                max_age=20,
                allowed_risk_tiers=("standard",),
                deductible_discounts_bps={1000: 100},
                required_metadata_fields=(),
            )
        )


def test_policy_evaluation_approved_calculation(sample_spec: PolicyProductSpec):
    compiled = PolicyProductCompiler.compile(sample_spec)
    applicant = {
        "age": 35,
        "risk_tier": "standard",  # multiplier 11500 bps (1.15x) -> 115,000 cents
        "deductible_cents": 100000,  # 500 bps discount (5%) -> discount 5,750 cents -> 109,250 cents
        "tax_id": "DE123456789",
        "industry_code": "IT_SERVICES",
    }
    decision = PolicyProductCompiler.evaluate(compiled, applicant)

    assert decision.approved is True
    assert decision.quote_premium_cents == 109250
    assert decision.audit_fingerprint == compiled.sha256_fingerprint
    assert "Eligible under canonical" in decision.reasons[0]


def test_policy_evaluation_rejects_out_of_bounds_age(sample_spec: PolicyProductSpec):
    compiled = PolicyProductCompiler.compile(sample_spec)
    applicant = {
        "age": 16,
        "risk_tier": "standard",
        "deductible_cents": 50000,
        "tax_id": "DE123456789",
        "industry_code": "IT_SERVICES",
    }
    decision = PolicyProductCompiler.evaluate(compiled, applicant)

    assert decision.approved is False
    assert decision.quote_premium_cents == 0
    assert any("outside allowed range" in r for r in decision.reasons)


def test_policy_evaluation_rejects_missing_metadata(sample_spec: PolicyProductSpec):
    compiled = PolicyProductCompiler.compile(sample_spec)
    applicant = {
        "age": 30,
        "risk_tier": "low",
        "deductible_cents": 50000,
        "tax_id": "DE123456789",
        # missing industry_code
    }
    decision = PolicyProductCompiler.evaluate(compiled, applicant)

    assert decision.approved is False
    assert any("Missing required field: industry_code" in r for r in decision.reasons)
