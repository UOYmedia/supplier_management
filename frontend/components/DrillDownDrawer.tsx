"use client";
import { ReactNode } from "react";
import { X } from "lucide-react";

/**
 * Reusable right-side slide-over for dashboard drill-downs.
 * Overview widget → click → this drawer shows detail/insight, keeping the
 * dashboard (and its period filter) in context behind a dimmed backdrop.
 */
export default function DrillDownDrawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full max-w-xl bg-white shadow-2xl flex flex-col">
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100">
          <div className="min-w-0">
            <h2 className="font-semibold text-gray-800">{title}</h2>
            {subtitle && <div className="text-xs text-gray-500 mt-0.5">{subtitle}</div>}
          </div>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-700 shrink-0"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-gray-100 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}
