# revenue-watchtower-engine

Deterministic AI-assisted revenue operations engine built around auditability, integer-cents ledger safety, and zero double-dunning guarantees.

## Architecture

- **`watchtower/approval_compiler.py`** — Validates natural-language / LLM-proposed deal approval payloads against an allowlisted AST schema, rejecting arbitrary fields/types, hashing canonical rule versions (`SHA-256`), and emitting explainable `ApprovalTrace` routing decisions.
- **`watchtower/collections_agent.py`** — Autonomous overdue cadence scheduler (`7d -> 14d -> 30d`) with dispute suppression, pending-ACH settlement holds, and per-epoch idempotency keys.
- **`watchtower/billing_evals.py`** — Contract-intake eval harness enforcing line-item integer-cents reconciliation, expected SKU completeness, and valid revenue-recognition intervals (`service_end_iso > service_start_iso`).
- **`sql/001_idempotent_billing_ledger.sql`** — PostgreSQL schema with `UNIQUE (idempotency_key)` outbox guards, immutable SHA-256 rule snapshots, and signed minor-unit ledger postings.
- **`ts/src/client.ts`** — Strict TypeScript minor-unit currency formatter and client-side idempotency key builder.

## Running Checks

```bash
pytest -v
cd ts && npm install --no-package-lock && npm run build && npm test
```
