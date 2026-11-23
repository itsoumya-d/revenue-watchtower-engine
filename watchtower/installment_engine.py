"""Installment schedule generator and repayment waterfall engine.

Enforces integer-cents precision with zero rounding drift, deterministic
amortisation schedules, idempotent repayment allocation, and delinquency lifecycle states.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import List, Set


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DEFAULTED = "DEFAULTED"


@dataclass
class InstallmentItem:
    sequence: int
    due_date_iso: str
    principal_cents: int
    interest_cents: int
    total_due_cents: int
    paid_principal_cents: int = 0
    paid_interest_cents: int = 0
    status: InstallmentStatus = InstallmentStatus.SCHEDULED

    @property
    def remaining_cents(self) -> int:
        return self.total_due_cents - (self.paid_principal_cents + self.paid_interest_cents)

    @property
    def remaining_principal_cents(self) -> int:
        return self.principal_cents - self.paid_principal_cents

    @property
    def remaining_interest_cents(self) -> int:
        return self.interest_cents - self.paid_interest_cents


@dataclass
class InstallmentPlan:
    plan_id: str
    total_principal_cents: int
    num_installments: int
    frequency_days: int
    apr_bps: int
    start_date_iso: str
    schedule: List[InstallmentItem] = field(default_factory=list)
    applied_idempotency_keys: Set[str] = field(default_factory=set)

    @property
    def is_fully_paid(self) -> bool:
        return all(item.remaining_cents == 0 for item in self.schedule)

    @property
    def outstanding_principal_cents(self) -> int:
        return sum(item.remaining_principal_cents for item in self.schedule)

    @property
    def outstanding_total_cents(self) -> int:
        return sum(item.remaining_cents for item in self.schedule)


@dataclass
class RepaymentResult:
    idempotency_key: str
    payment_cents: int
    principal_allocated_cents: int
    interest_allocated_cents: int
    unallocated_cents: int
    plan_completed: bool


def create_installment_schedule(
    plan_id: str,
    principal_cents: int,
    num_installments: int = 4,
    frequency_days: int = 14,
    apr_bps: int = 0,
    start_date_iso: str = "2026-11-23",
) -> InstallmentPlan:
    """Generate deterministic installment schedule with exact penny reconciliation."""
    if principal_cents <= 0 or num_installments < 1:
        raise ValueError("Invalid principal or installment count.")

    base_date = date.fromisoformat(start_date_iso)
    schedule: List[InstallmentItem] = []

    if apr_bps == 0:
        base_p = principal_cents // num_installments
        rem = principal_cents % num_installments
        for i in range(1, num_installments + 1):
            due = base_date + timedelta(days=i * frequency_days)
            p = base_p + (1 if i <= rem else 0)
            schedule.append(InstallmentItem(i, due.isoformat(), p, 0, p))
    else:
        periodic_rate = (apr_bps / 10000.0) * (frequency_days / 365.0)
        remaining_balance = principal_cents
        base_p = principal_cents // num_installments
        rem = principal_cents % num_installments
        for i in range(1, num_installments + 1):
            due = base_date + timedelta(days=i * frequency_days)
            p = base_p + (1 if i <= rem else 0)
            interest = round(remaining_balance * periodic_rate)
            schedule.append(InstallmentItem(i, due.isoformat(), p, interest, p + interest))
            remaining_balance -= p

    assert sum(item.principal_cents for item in schedule) == principal_cents
    return InstallmentPlan(
        plan_id=plan_id,
        total_principal_cents=principal_cents,
        num_installments=num_installments,
        frequency_days=frequency_days,
        apr_bps=apr_bps,
        start_date_iso=start_date_iso,
        schedule=schedule,
    )


def apply_repayment(
    plan: InstallmentPlan,
    amount_cents: int,
    idempotency_key: str,
) -> RepaymentResult:
    """Waterfall allocation: interest first, then principal in chronological order."""
    if idempotency_key in plan.applied_idempotency_keys:
        raise ValueError(f"Duplicate payment attempt: {idempotency_key}")
    if amount_cents <= 0:
        raise ValueError("Payment amount must be positive.")

    plan.applied_idempotency_keys.add(idempotency_key)
    rem = amount_cents
    allocated_interest = 0
    allocated_principal = 0

    # Interest allocation
    for item in plan.schedule:
        if rem <= 0:
            break
        i_due = item.remaining_interest_cents
        if i_due > 0:
            pay = min(rem, i_due)
            item.paid_interest_cents += pay
            allocated_interest += pay
            rem -= pay

    # Principal allocation
    for item in plan.schedule:
        if rem <= 0:
            break
        p_due = item.remaining_principal_cents
        if p_due > 0:
            pay = min(rem, p_due)
            item.paid_principal_cents += pay
            allocated_principal += pay
            rem -= pay

    for item in plan.schedule:
        if item.remaining_cents == 0:
            item.status = InstallmentStatus.PAID

    return RepaymentResult(
        idempotency_key=idempotency_key,
        payment_cents=amount_cents,
        principal_allocated_cents=allocated_principal,
        interest_allocated_cents=allocated_interest,
        unallocated_cents=rem,
        plan_completed=plan.is_fully_paid,
    )


def evaluate_delinquencies(
    plan: InstallmentPlan,
    as_of_date_iso: str,
    grace_period_days: int = 10,
) -> List[int]:
    """Evaluate installment statuses based on chronological due dates and grace period."""
    as_of = date.fromisoformat(as_of_date_iso)
    overdue_seqs: List[int] = []

    for item in plan.schedule:
        if item.remaining_cents == 0:
            item.status = InstallmentStatus.PAID
            continue
        dpd = (as_of - date.fromisoformat(item.due_date_iso)).days
        if dpd < 0:
            item.status = InstallmentStatus.SCHEDULED
        elif dpd <= grace_period_days:
            item.status = InstallmentStatus.DUE
        elif dpd < 90:
            item.status = InstallmentStatus.OVERDUE
            overdue_seqs.append(item.sequence)
        else:
            item.status = InstallmentStatus.DEFAULTED
            overdue_seqs.append(item.sequence)

    return overdue_seqs
