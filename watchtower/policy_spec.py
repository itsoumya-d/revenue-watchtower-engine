from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PolicyProductSpec:
    product_id: str
    version: str
    base_premium_cents: int
    min_age: int
    max_age: int
    allowed_risk_tiers: tuple[str, ...]
    deductible_discounts_bps: dict[int, int]
    required_metadata_fields: tuple[str, ...]


@dataclass(frozen=True)
class CompiledPolicyProduct:
    spec: PolicyProductSpec
    sha256_fingerprint: str
    canonical_definition: str


@dataclass(frozen=True)
class PolicyEvaluationResult:
    approved: bool
    quote_premium_cents: int
    reasons: tuple[str, ...]
    audit_fingerprint: str


class PolicyProductCompiler:
    """
    Compiles declarative, versioned policy specifications into immutable execution blueprints.
    Guarantees deterministic underwriting rule execution and penny-exact integer cents calculations.
    """

    @staticmethod
    def compile(spec: PolicyProductSpec) -> CompiledPolicyProduct:
        if spec.base_premium_cents <= 0:
            raise ValueError("base_premium_cents must be strictly positive")
        if spec.min_age < 0 or spec.max_age < spec.min_age:
            raise ValueError(f"Invalid age bounds: [{spec.min_age}, {spec.max_age}]")
        if not spec.allowed_risk_tiers:
            raise ValueError("allowed_risk_tiers must not be empty")

        canonical_dict = {
            "base_premium_cents": spec.base_premium_cents,
            "deductible_discounts_bps": {str(k): v for k, v in sorted(spec.deductible_discounts_bps.items())},
            "max_age": spec.max_age,
            "min_age": spec.min_age,
            "product_id": spec.product_id,
            "required_metadata_fields": sorted(spec.required_metadata_fields),
            "risk_tiers": sorted(spec.allowed_risk_tiers),
            "version": spec.version,
        }
        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return CompiledPolicyProduct(
            spec=spec,
            sha256_fingerprint=fingerprint,
            canonical_definition=canonical_json,
        )

    @staticmethod
    def evaluate(
        compiled: CompiledPolicyProduct,
        applicant: Mapping[str, Any],
    ) -> PolicyEvaluationResult:
        reasons: list[str] = []
        spec = compiled.spec

        for field in spec.required_metadata_fields:
            if field not in applicant or applicant[field] is None:
                reasons.append(f"Missing required field: {field}")

        age = applicant.get("age")
        if age is None or not isinstance(age, int):
            reasons.append("Applicant age must be an integer")
        elif age < spec.min_age or age > spec.max_age:
            reasons.append(f"Age {age} outside allowed range [{spec.min_age}, {spec.max_age}]")

        risk_tier = applicant.get("risk_tier")
        if risk_tier not in spec.allowed_risk_tiers:
            reasons.append(f"Risk tier '{risk_tier}' is not permitted")

        deductible = applicant.get("deductible_cents", 0)
        discount_bps = spec.deductible_discounts_bps.get(deductible, 0)
        if deductible not in spec.deductible_discounts_bps:
            reasons.append(f"Invalid deductible: {deductible}")

        if reasons:
            return PolicyEvaluationResult(
                approved=False,
                quote_premium_cents=0,
                reasons=tuple(reasons),
                audit_fingerprint=compiled.sha256_fingerprint,
            )

        tier_multipliers = {
            "low": 10000,
            "standard": 11500,
            "elevated": 14000,
            "high": 17500,
        }
        mult_bps = tier_multipliers.get(str(risk_tier), 10000)

        intermediate_cents = (spec.base_premium_cents * mult_bps) // 10000
        discount_cents = (intermediate_cents * discount_bps) // 10000
        final_premium_cents = max(1, intermediate_cents - discount_cents)

        return PolicyEvaluationResult(
            approved=True,
            quote_premium_cents=final_premium_cents,
            reasons=("Eligible under canonical policy specifications",),
            audit_fingerprint=compiled.sha256_fingerprint,
        )
