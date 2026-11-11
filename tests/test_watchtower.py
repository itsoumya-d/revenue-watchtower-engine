import pytest

from watchtower.approval_compiler import (
    DealContext,
    RuleValidationError,
    compile_rule_from_untrusted_llm,
    evaluate_approval_policy,
)
from watchtower.billing_evals import (
    ContractEvalCase,
    ContractExtraction,
    ContractLineItem,
    evaluate_contract_extractions,
)
from watchtower.collections_agent import InvoiceRecord, plan_collections_actions


def test_untrusted_llm_approval_compiler_and_audit_trace():
    llm_json = {
        "rules": [
            {
                "rule_id": "vp-100k-annual",
                "description": "Require VP Sales approval for deals >= $100k with annual terms",
                "priority": 10,
                "conditions": [
                    {"field": "acv_cents", "op": "gte", "value": 10_000_000},
                    {"field": "billing_term", "op": "eq", "value": "annual"},
                ],
                "approvers": ["VP_SALES", "FINANCE_DESK"],
            },
            {
                "rule_id": "cfo-heavy-discount",
                "description": "Escalate >20% discount to CFO",
                "priority": 20,
                "conditions": [{"field": "discount_bps", "op": "gt", "value": 2000}],
                "approvers": ["CFO"],
            },
        ]
    }
    policy = compile_rule_from_untrusted_llm("pol_rev_01", llm_json)
    deal = DealContext(
        deal_id="deal_acme_01",
        acv_cents=12_500_000,
        discount_bps=2500,
        billing_term="annual",
        payment_terms_days=30,
    )
    trace = evaluate_approval_policy(policy, deal)
    assert trace.matched_rule_ids == ["vp-100k-annual", "cfo-heavy-discount"]
    assert trace.required_approvers == ["VP_SALES", "FINANCE_DESK", "CFO"]
    assert len(trace.policy_version_hash) == 64

    with pytest.raises(RuleValidationError):
        compile_rule_from_untrusted_llm(
            "bad",
            {"rules": [{"rule_id": "x", "conditions": [{"field": "__class__", "op": "eq", "value": "x"}], "approvers": ["VP"]}]},
        )


def test_collections_agent_respects_disputes_settlements_and_idempotency():
    decisions = plan_collections_actions(
        [
            InvoiceRecord("inv_1", "cust_a", 500_000, days_overdue=8),
            InvoiceRecord("inv_2", "cust_b", 500_000, days_overdue=16, already_dispatched_stages=("REMINDER_7D", "ESCALATE_14D")),
            InvoiceRecord("inv_3", "cust_c", 900_000, days_overdue=22, disputed=True),
            InvoiceRecord("inv_4", "cust_d", 250_000, days_overdue=19, payment_pending_settlement=True),
            InvoiceRecord("inv_5", "cust_e", 300_000, days_overdue=15),
        ],
        schedule_epoch="2026-11-11",
    )
    by_id = {d.invoice_id: d for d in decisions}
    assert by_id["inv_1"].action == "DISPATCH"
    assert by_id["inv_1"].stage == "REMINDER_7D"
    assert by_id["inv_1"].idempotency_key == "inv_1:REMINDER_7D:2026-11-11"
    assert by_id["inv_2"].action == "NOOP"
    assert by_id["inv_2"].reason == "already_dispatched_idempotent_skip"
    assert by_id["inv_3"].action == "SUPPRESS"
    assert by_id["inv_4"].action == "SUPPRESS"
    assert by_id["inv_5"].action == "DISPATCH"
    assert by_id["inv_5"].stage == "ESCALATE_14D"


def test_contract_intake_eval_harness_flags_arithmetic_or_revrec_drift():
    good = ContractEvalCase(
        case_id="good_case",
        expected_total_cents=1_200_000,
        expected_skus=frozenset({"PLATFORM", "USAGE"}),
        predicted=ContractExtraction(
            contract_id="c1",
            total_contract_cents=1_200_000,
            currency="GBP",
            line_items=(
                ContractLineItem("PLATFORM", 1_000_000, "annual", "2026-01-01", "2026-12-31"),
                ContractLineItem("USAGE", 200_000, "monthly", "2026-01-01", "2026-12-31"),
            ),
        ),
    )
    bad = ContractEvalCase(
        case_id="bad_math",
        expected_total_cents=1_000_000,
        expected_skus=frozenset({"PLATFORM"}),
        predicted=ContractExtraction(
            contract_id="c2",
            total_contract_cents=1_000_000,
            currency="USD",
            line_items=(ContractLineItem("PLATFORM", 900_000, "annual", "2026-06-01", "2026-01-01"),),
        ),
    )
    report = evaluate_contract_extractions([good, bad])
    assert report.passed_cases == 1
    assert report.pass_rate == 0.5
    assert any("line_sum(900000)!=total(1000000)" in v for v in report.invariant_violations)
    assert any("invalid_revrec_window" in v for v in report.invariant_violations)
