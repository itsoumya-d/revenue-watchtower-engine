from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

ALLOWED_FIELDS = frozenset({"acv_cents", "discount_bps", "billing_term", "payment_terms_days", "region"})
ALLOWED_OPS = frozenset({"gt", "gte", "lt", "lte", "eq", "in"})
ALLOWED_TERMS = frozenset({"monthly", "quarterly", "annual", "multi_year"})


@dataclass(frozen=True)
class Condition:
    field: str
    op: Literal["gt", "gte", "lt", "lte", "eq", "in"]
    value: int | str | list[str]


@dataclass(frozen=True)
class ApprovalRule:
    rule_id: str
    description: str
    conditions: tuple[Condition, ...]
    approvers: tuple[str, ...]
    priority: int = 100


@dataclass(frozen=True)
class ApprovalPolicy:
    policy_id: str
    rules: tuple[ApprovalRule, ...]
    version_hash: str


@dataclass(frozen=True)
class DealContext:
    deal_id: str
    acv_cents: int
    discount_bps: int
    billing_term: str
    payment_terms_days: int
    region: str = "UK"


@dataclass
class ApprovalTrace:
    deal_id: str
    policy_version_hash: str
    matched_rule_ids: list[str] = field(default_factory=list)
    required_approvers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class RuleValidationError(ValueError):
    """Raised when an LLM-proposed approval AST violates safety or type invariants."""


def _validate_condition(raw: dict[str, Any]) -> Condition:
    field_name = raw.get("field")
    op = raw.get("op")
    value = raw.get("value")
    if field_name not in ALLOWED_FIELDS:
        raise RuleValidationError(f"Unsupported condition field: {field_name!r}")
    if op not in ALLOWED_OPS:
        raise RuleValidationError(f"Unsupported operator: {op!r}")

    if field_name in {"acv_cents", "discount_bps", "payment_terms_days"}:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuleValidationError(f"Numeric field {field_name} requires non-negative integer, got {value!r}")
        if field_name == "discount_bps" and value > 10_000:
            raise RuleValidationError("discount_bps cannot exceed 10000 (100%)")
    elif field_name == "billing_term":
        if op == "in":
            if not isinstance(value, list) or not all(v in ALLOWED_TERMS for v in value):
                raise RuleValidationError(f"Invalid billing_term list: {value!r}")
        elif value not in ALLOWED_TERMS:
            raise RuleValidationError(f"Invalid billing_term value: {value!r}")
    elif not isinstance(value, str) or not value.strip():
        raise RuleValidationError(f"String condition field {field_name} must be non-empty")

    return Condition(field=field_name, op=op, value=value)


def compile_rule_from_untrusted_llm(policy_id: str, raw_payload: dict[str, Any]) -> ApprovalPolicy:
    """Validate LLM-parsed natural-language rules into a deterministic, hashed policy AST."""
    raw_rules = raw_payload.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RuleValidationError("Policy must declare a non-empty list of rules")

    compiled: list[ApprovalRule] = []
    seen_ids: set[str] = set()
    for item in raw_rules:
        rid = str(item.get("rule_id", "")).strip()
        if not rid or rid in seen_ids:
            raise RuleValidationError(f"Duplicate or missing rule_id: {rid!r}")
        seen_ids.add(rid)

        raw_conds = item.get("conditions", [])
        if not isinstance(raw_conds, list) or not raw_conds:
            raise RuleValidationError(f"Rule {rid} must contain at least one condition")
        conds = tuple(_validate_condition(c) for c in raw_conds)

        approvers = item.get("approvers", [])
        if not isinstance(approvers, list) or not approvers or not all(isinstance(a, str) and a.strip() for a in approvers):
            raise RuleValidationError(f"Rule {rid} must declare non-empty approver roles")

        deduped_approvers = tuple(dict.fromkeys(a.strip() for a in approvers))
        priority = int(item.get("priority", 100))
        compiled.append(
            ApprovalRule(
                rule_id=rid,
                description=str(item.get("description", rid)),
                conditions=conds,
                approvers=deduped_approvers,
                priority=priority,
            )
        )

    compiled.sort(key=lambda r: (r.priority, r.rule_id))
    canonical = json.dumps(
        [
            {
                "rule_id": r.rule_id,
                "priority": r.priority,
                "conditions": [{"field": c.field, "op": c.op, "value": c.value} for c in r.conditions],
                "approvers": list(r.approvers),
            }
            for r in compiled
        ],
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return ApprovalPolicy(policy_id=policy_id, rules=tuple(compiled), version_hash=digest)


def _matches(cond: Condition, ctx: DealContext) -> bool:
    actual = getattr(ctx, cond.field)
    if cond.op == "gt":
        return actual > cond.value
    if cond.op == "gte":
        return actual >= cond.value
    if cond.op == "lt":
        return actual < cond.value
    if cond.op == "lte":
        return actual <= cond.value
    if cond.op == "eq":
        return actual == cond.value
    if cond.op == "in":
        return actual in cond.value
    return False


def evaluate_approval_policy(policy: ApprovalPolicy, deal: DealContext) -> ApprovalTrace:
    """Evaluate a validated approval DAG against an exact integer-cents deal quote."""
    trace = ApprovalTrace(deal_id=deal.deal_id, policy_version_hash=policy.version_hash)
    ordered_approvers: list[str] = []

    for rule in policy.rules:
        if all(_matches(cond, deal) for cond in rule.conditions):
            trace.matched_rule_ids.append(rule.rule_id)
            trace.reasons.append(rule.description)
            for approver in rule.approvers:
                if approver not in ordered_approvers:
                    ordered_approvers.append(approver)

    trace.required_approvers = ordered_approvers
    return trace
