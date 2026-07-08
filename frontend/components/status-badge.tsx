import type { ReactNode } from "react";

export function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "accent" | "neutral" | "success" | "warning" | "error";
}) {
  return <span className={`status-badge status-badge-${tone}`}>{children}</span>;
}
