export function StatusBadge({ value }: { value?: string | null }) {
  const v = String(value || "NOT AVAILABLE").toUpperCase();
  let cls = "na";
  if (v === "PASS" || v === "AUTHORIZED" || v === "OK") cls = "pass";
  else if (v === "WARN" || v === "PREVIEW" || v.includes("WARN")) cls = "warn";
  else if (v === "BLOCK" || v === "DENIED" || v.includes("BLOCK")) cls = "block";
  return <span className={`badge ${cls}`}>{v}</span>;
}
