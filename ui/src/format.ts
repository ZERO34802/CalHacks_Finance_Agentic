// Display-only formatting. Money arrives as Decimal strings; we never do arithmetic on it here.

export const money = (amount: string | null | undefined, currency?: string | null) => {
  if (amount == null) return "—";
  const s = Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${s} ${currency}` : s;
};

/** 18,600,000.00 -> "18.6M" */
export const compact = (amount: string | null | undefined) =>
  amount == null ? "—" : Number(amount).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const usd = (amount: string | null | undefined) =>
  amount == null ? "—" : Number(amount).toLocaleString("en-US", {
    style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1,
  });

export const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);

export const date = (iso: string | null | undefined) =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—";

export const titleCase = (slug: string) => slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
