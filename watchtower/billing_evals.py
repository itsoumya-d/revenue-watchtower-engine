from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContractLineItem:
    sku: str
    amount_cents: int
    billing_frequency: str
    service_start_iso: str
    service_end_iso: str


@dataclass(frozen=True)
class ContractExtraction:
    contract_id: str
    total_contract_cents: int
    currency: str
    line_items: tuple[ContractLineItem, ...]


@dataclass(frozen=True)
class ContractEvalCase:
    case_id: str
    expected_total_cents: int
    expected_skus: frozenset[str]
    predicted: ContractExtraction


@dataclass
class ContractEvalReport:
    total_cases: int
    passed_cases: int
    invariant_violations: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed_cases / self.total_cases if self.total_cases else 0.0


def evaluate_contract_extractions(cases: list[ContractEvalCase]) -> ContractEvalReport:
    """Enforce zero arithmetic or date-range drift across LLM contract extractions."""
    violations: list[str] = []
    passed = 0

    for case in cases:
        ext = case.predicted
        case_errors: list[str] = []

        line_sum = sum(li.amount_cents for li in ext.line_items)
        if line_sum != ext.total_contract_cents:
            case_errors.append(f"{case.case_id}:line_sum({line_sum})!=total({ext.total_contract_cents})")
        if ext.total_contract_cents != case.expected_total_cents:
            case_errors.append(f"{case.case_id}:expected({case.expected_total_cents})!=got({ext.total_contract_cents})")

        predicted_skus = {li.sku for li in ext.line_items}
        if predicted_skus != case.expected_skus:
            case_errors.append(f"{case.case_id}:sku_mismatch({sorted(predicted_skus)}!={sorted(case.expected_skus)})")

        for li in ext.line_items:
            if li.service_end_iso <= li.service_start_iso:
                case_errors.append(f"{case.case_id}:invalid_revrec_window({li.sku})")

        if case_errors:
            violations.extend(case_errors)
        else:
            passed += 1

    return ContractEvalReport(total_cases=len(cases), passed_cases=passed, invariant_violations=violations)
