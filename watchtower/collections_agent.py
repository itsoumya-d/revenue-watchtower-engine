from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CadenceStep:
    stage: Literal["REMINDER_7D", "ESCALATE_14D", "FINAL_NOTICE_30D"]
    min_days_overdue: int
    channel: Literal["email", "slack_csm", "legal_queue"]


@dataclass(frozen=True)
class InvoiceRecord:
    invoice_id: str
    customer_id: str
    amount_due_cents: int
    days_overdue: int
    disputed: bool = False
    payment_pending_settlement: bool = False
    already_dispatched_stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectionDecision:
    invoice_id: str
    customer_id: str
    action: Literal["DISPATCH", "SUPPRESS", "NOOP"]
    stage: str | None
    idempotency_key: str | None
    reason: str


DEFAULT_CADENCE: tuple[CadenceStep, ...] = (
    CadenceStep(stage="REMINDER_7D", min_days_overdue=7, channel="email"),
    CadenceStep(stage="ESCALATE_14D", min_days_overdue=14, channel="slack_csm"),
    CadenceStep(stage="FINAL_NOTICE_30D", min_days_overdue=30, channel="legal_queue"),
)


def plan_collections_actions(
    invoices: list[InvoiceRecord],
    cadence: tuple[CadenceStep, ...] = DEFAULT_CADENCE,
    schedule_epoch: str = "2026-11-11",
) -> list[CollectionDecision]:
    """Produce idempotent, dispute-safe collection actions without double-dunning."""
    ordered_steps = sorted(cadence, key=lambda s: s.min_days_overdue, reverse=True)
    decisions: list[CollectionDecision] = []

    for inv in invoices:
        if inv.amount_due_cents <= 0:
            decisions.append(
                CollectionDecision(
                    invoice_id=inv.invoice_id,
                    customer_id=inv.customer_id,
                    action="NOOP",
                    stage=None,
                    idempotency_key=None,
                    reason="zero_balance",
                )
            )
            continue

        if inv.disputed:
            decisions.append(
                CollectionDecision(
                    invoice_id=inv.invoice_id,
                    customer_id=inv.customer_id,
                    action="SUPPRESS",
                    stage=None,
                    idempotency_key=None,
                    reason="active_billing_dispute",
                )
            )
            continue

        if inv.payment_pending_settlement:
            decisions.append(
                CollectionDecision(
                    invoice_id=inv.invoice_id,
                    customer_id=inv.customer_id,
                    action="SUPPRESS",
                    stage=None,
                    idempotency_key=None,
                    reason="pending_ach_or_wire_settlement",
                )
            )
            continue

        target_step = next((step for step in ordered_steps if inv.days_overdue >= step.min_days_overdue), None)
        if target_step is None:
            decisions.append(
                CollectionDecision(
                    invoice_id=inv.invoice_id,
                    customer_id=inv.customer_id,
                    action="NOOP",
                    stage=None,
                    idempotency_key=None,
                    reason="within_grace_window",
                )
            )
            continue

        if target_step.stage in inv.already_dispatched_stages:
            decisions.append(
                CollectionDecision(
                    invoice_id=inv.invoice_id,
                    customer_id=inv.customer_id,
                    action="NOOP",
                    stage=target_step.stage,
                    idempotency_key=f"{inv.invoice_id}:{target_step.stage}:{schedule_epoch}",
                    reason="already_dispatched_idempotent_skip",
                )
            )
            continue

        decisions.append(
            CollectionDecision(
                invoice_id=inv.invoice_id,
                customer_id=inv.customer_id,
                action="DISPATCH",
                stage=target_step.stage,
                idempotency_key=f"{inv.invoice_id}:{target_step.stage}:{schedule_epoch}",
                reason=f"overdue_{inv.days_overdue}d_via_{target_step.channel}",
            )
        )

    return decisions
