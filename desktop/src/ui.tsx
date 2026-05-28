import { useCallback, useRef, useState, type ReactNode } from "react";

export const PRIMARY_BTN =
  "rounded-md bg-[var(--color-brass)] px-4 py-2 text-[13px] font-medium text-[#1b1d23] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
export const GHOST_BTN =
  "rounded-md border border-[var(--color-line)] px-4 py-2 text-[13px] text-[var(--color-ink-2)] transition-colors hover:bg-[var(--color-bg-raised)] disabled:opacity-40";
export const DANGER_BTN =
  "rounded-md border border-[var(--color-danger)]/40 px-3 py-2 text-[13px] text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)]/10 disabled:opacity-40";
export const SM_GHOST_BTN =
  "rounded-md border border-[var(--color-line)] px-2.5 py-1 text-[12px] text-[var(--color-ink-2)] transition-colors hover:bg-[var(--color-bg-raised)] disabled:opacity-40";
export const INPUT_CLS =
  "w-full rounded-md border border-[var(--color-line)] bg-[var(--color-bg-raised)] px-3 py-2 text-[14px] text-[var(--color-ink-1)] outline-none focus:border-[var(--color-brass)]";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] p-5 ${className}`}>
      {children}
    </div>
  );
}

export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-7 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-[22px] font-medium tracking-tight text-[var(--color-ink-1)]">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-[var(--color-ink-3)]">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] px-5 py-8 text-center text-[13px] text-[var(--color-ink-3)]">
      {children}
    </div>
  );
}

export function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="mb-3 block">
      {label && <div className="mb-1 text-[12px] text-[var(--color-ink-3)]">{label}</div>}
      {children}
    </label>
  );
}

export function ModalShell({
  title,
  onClose,
  children,
  width = "w-[560px]",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/55" />
      <div
        className={`relative ${width} max-h-[85vh] overflow-auto rounded-xl border border-[var(--color-line)] bg-[var(--color-bg-base)] p-6 shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-medium text-[var(--color-ink-1)]">{title}</h3>
          <button className="text-[var(--color-ink-4)] hover:text-[var(--color-ink-1)]" onClick={onClose}>
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ModalActions({
  onCancel,
  onConfirm,
  confirmLabel,
  disabled,
}: {
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="mt-5 flex justify-end gap-3">
      <button className={GHOST_BTN} onClick={onCancel}>
        取消
      </button>
      <button className={PRIMARY_BTN} onClick={onConfirm} disabled={disabled}>
        {confirmLabel}
      </button>
    </div>
  );
}

export type Toast = { text: string; kind: "ok" | "err" } | null;

export function useToast() {
  const [toast, setToast] = useState<Toast>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const notify = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    setToast({ text, kind });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 4000);
  }, []);
  return { toast, notify };
}

export function ToastView({ toast }: { toast: Toast }) {
  if (!toast) return null;
  const tone =
    toast.kind === "err"
      ? "border-[var(--color-danger)]/50 text-[var(--color-danger)]"
      : "border-[var(--color-ok)]/50 text-[var(--color-ok)]";
  return (
    <div
      className={`fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-md border bg-[var(--color-bg-elev)] px-4 py-2.5 text-[13px] shadow-lg ${tone}`}
    >
      {toast.text}
    </div>
  );
}
