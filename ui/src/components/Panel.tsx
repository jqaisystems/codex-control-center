import type { PropsWithChildren, ReactNode } from "react";

type PanelProps = PropsWithChildren<{
  title: string;
  action?: ReactNode;
  className?: string;
}>;

export function Panel({ title, action, children, className = "" }: PanelProps) {
  return (
    <section className={`min-w-0 overflow-hidden rounded-control border border-line bg-panel shadow-sm ${className}`}>
      <div className="flex min-h-12 min-w-0 items-center justify-between gap-3 border-b border-line px-4">
        <h2 className="min-w-0 truncate text-sm font-semibold text-white">{title}</h2>
        {action}
      </div>
      <div className="min-w-0 p-4">{children}</div>
    </section>
  );
}

export function Pill({ children, tone = "neutral" }: PropsWithChildren<{ tone?: string }>) {
  const tones: Record<string, string> = {
    ok: "border-good/40 bg-good/10 text-good",
    warn: "border-warn/40 bg-warn/10 text-warn",
    bad: "border-bad/40 bg-bad/10 text-bad",
    neutral: "border-line bg-panel2 text-muted",
    focus: "border-focus/40 bg-focus/10 text-focus"
  };
  return (
    <span className={`inline-flex max-w-full items-center rounded border px-2 py-0.5 text-left text-xs leading-snug ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function EmptyState({ label }: { label: string }) {
  return <div className="rounded-control border border-dashed border-line p-4 text-sm text-muted">{label}</div>;
}
