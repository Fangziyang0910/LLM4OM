import { CircleCheck, CircleDashed, CircleSlash, CircleX, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { STATUS, tone } from "@/format";

type Tone = ReturnType<typeof tone>;

/** Text and tinted-surface classes for each status tone. */
export const TONE: Record<Tone, { text: string; soft: string; border: string }> = {
  good: { text: "text-success", soft: "bg-success/10 text-success border-success/20", border: "border-success/30" },
  bad: { text: "text-destructive", soft: "bg-destructive/10 text-destructive border-destructive/20", border: "border-destructive/30" },
  warn: { text: "text-warning", soft: "bg-warning/10 text-warning border-warning/25", border: "border-warning/35" },
  live: { text: "text-primary", soft: "bg-primary/10 text-primary border-primary/20", border: "border-primary/30" },
  idle: { text: "text-muted-foreground", soft: "bg-muted text-muted-foreground border-border", border: "border-border" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return <Badge variant="outline" className={cn("font-medium", TONE[tone(status)].soft, className)}>{STATUS[status] ?? status}</Badge>;
}

export function StatusIcon({ status, className }: { status: string; className?: string }) {
  const t = tone(status);
  const Icon = t === "good" ? CircleCheck : t === "bad" ? CircleX : t === "warn" ? (status === "interrupted" ? CircleSlash : TriangleAlert) : CircleDashed;
  if (t === "live") return <Spinner className={cn("size-4 text-primary", className)} />;
  return <Icon className={cn("size-4", TONE[t].text, className)} />;
}
