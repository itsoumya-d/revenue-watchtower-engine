import pytest
from watchtower.installment_engine import (
    InstallmentStatus,
    apply_repayment,
    create_installment_schedule,
    evaluate_delinquencies,
)


def test_zero_apr_pay_in_four_exact_penny_balance():
    # 10001 cents ($100.01) divided across 4 installments cannot be evenly split by 4.
    plan = create_installment_schedule(
        plan_id="plan_bnpl_100",
        principal_cents=10001,
        num_installments=4,
        frequency_days=14,
        apr_bps=0,
        start_date_iso="2026-11-01",
    )
    assert len(plan.schedule) == 4
    # Check remainder distribution: 10001 = 2500 * 4 + 1 -> first installment gets 2501, rest 2500
    assert plan.schedule[0].principal_cents == 2501
    assert plan.schedule[1].principal_cents == 2500
    assert plan.schedule[2].principal_cents == 2500
    assert plan.schedule[3].principal_cents == 2500
    assert sum(item.principal_cents for item in plan.schedule) == 10001
    assert plan.outstanding_principal_cents == 10001


def test_repayment_waterfall_and_idempotency():
    plan = create_installment_schedule(
        plan_id="plan_wf_200",
        principal_cents=20000,
        num_installments=4,
        frequency_days=14,
        apr_bps=1200,  # 12% APR
        start_date_iso="2026-11-01",
    )

    # First payment of 5100 cents
    res1 = apply_repayment(plan, amount_cents=5100, idempotency_key="pay_tx_001")
    assert res1.interest_allocated_cents > 0
    assert res1.principal_allocated_cents > 0
    assert res1.unallocated_cents == 0
    assert not res1.plan_completed

    # Duplicate payment rejection
    with pytest.raises(ValueError, match="Duplicate payment attempt"):
        apply_repayment(plan, amount_cents=5100, idempotency_key="pay_tx_001")

    # Pay remaining balance in full
    remaining = plan.outstanding_total_cents
    res2 = apply_repayment(plan, amount_cents=remaining, idempotency_key="pay_tx_002")
    assert res2.plan_completed
    assert plan.is_fully_paid
    assert all(item.status == InstallmentStatus.PAID for item in plan.schedule)


def test_delinquency_lifecycle_transitions():
    plan = create_installment_schedule(
        plan_id="plan_delinquent_test",
        principal_cents=40000,
        num_installments=4,
        frequency_days=14,
        apr_bps=0,
        start_date_iso="2026-10-01",
    )
    # Schedule dates:
    # item 1: 2026-10-15
    # item 2: 2026-10-29
    # item 3: 2026-11-12
    # item 4: 2026-11-26

    # As of 2026-11-20:
    # item 1 (due 10-15): 36 days past due -> OVERDUE
    # item 2 (due 10-29): 22 days past due -> OVERDUE
    # item 3 (due 11-12): 8 days past due (grace <= 10) -> DUE
    # item 4 (due 11-26): in future -> SCHEDULED
    overdue = evaluate_delinquencies(plan, as_of_date_iso="2026-11-20", grace_period_days=10)
    assert overdue == [1, 2]
    assert plan.schedule[0].status == InstallmentStatus.OVERDUE
    assert plan.schedule[1].status == InstallmentStatus.OVERDUE
    assert plan.schedule[2].status == InstallmentStatus.DUE
    assert plan.schedule[3].status == InstallmentStatus.SCHEDULED
