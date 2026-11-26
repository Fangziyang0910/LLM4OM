import { useId } from "react";
import { cn } from "@/lib/utils";

/** The product mark: a feasible region with its optimal vertex. scripts/render_assets.py and index.html draw the same shape. */
export function LogoMark({ className }: { className?: string }) {
  const gradient = "logo-" + useId().replace(/[^\w-]/g, "");
  return <svg viewBox="0 0 24 24" aria-hidden className={cn("size-7 shrink-0", className)}>
    <defs>
      <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" style={{ stopColor: "var(--primary)" }} />
        <stop offset="1" style={{ stopColor: "var(--brand-accent)" }} />
      </linearGradient>
    </defs>
    <rect width="24" height="24" rx="6" fill={`url(#${gradient})`} />
    <path d="M4.5 15 8 6.5l9.5-1.2L19.5 13 11 19z" fill="#fff" fillOpacity=".28" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
    <circle cx="17.5" cy="5.3" r="2.4" fill="#fff" />
  </svg>;
}
