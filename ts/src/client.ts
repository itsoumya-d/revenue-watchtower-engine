export interface InvoiceSummary {
  invoiceId: string;
  currency: "GBP" | "USD" | "EUR";
  minorUnits: number;
}

export function formatMinorUnits(minorUnits: number, currency: "GBP" | "USD" | "EUR"): string {
  const symbol = currency === "GBP" ? "£" : currency === "EUR" ? "€" : "$";
  const sign = minorUnits < 0 ? "-" : "";
  const abs = Math.abs(minorUnits);
  const whole = Math.floor(abs / 100);
  const frac = String(abs % 100).padStart(2, "0");
  return `${sign}${symbol}${whole.toLocaleString("en-US")}.${frac}`;
}

export function buildIdempotencyKey(invoiceId: string, stage: string, epochIsoDate: string): string {
  if (!invoiceId.trim() || !stage.trim() || !/^\d{4}-\d{2}-\d{2}$/.test(epochIsoDate)) {
    throw new Error("Invalid idempotency key component");
  }
  return `${invoiceId.trim()}:${stage.trim()}:${epochIsoDate}`;
}
