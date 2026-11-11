import assert from "node:assert/strict";
import test from "node:test";
import { buildIdempotencyKey, formatMinorUnits } from "../src/client.ts";

test("formats minor units accurately without floating point drift", () => {
  assert.equal(formatMinorUnits(12_500_005, "GBP"), "£125,000.05");
  assert.equal(formatMinorUnits(100_000, "USD"), "$1,000.00");
  assert.equal(buildIdempotencyKey("inv_42", "ESCALATE_14D", "2026-11-11"), "inv_42:ESCALATE_14D:2026-11-11");
});
