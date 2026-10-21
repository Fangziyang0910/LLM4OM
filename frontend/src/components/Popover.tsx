import * as Radix from "@radix-ui/react-popover";
import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";

/** A picker button with a panel below it; Radix handles focus, Escape, outside clicks and placement. */
export function Popover({ label, value, icon, children, align = "start", wide = false }: {
  label: string; value: ReactNode; icon?: ReactNode; align?: "start" | "end"; wide?: boolean;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return <Radix.Root open={open} onOpenChange={setOpen}>
    <Radix.Trigger asChild>
      <button type="button" className="picker">
        {icon}
        <span className="picker-text"><span className="picker-label">{label}</span><span className="picker-value">{value}</span></span>
        <ChevronDown size={15} className="picker-chevron" />
      </button>
    </Radix.Trigger>
    <Radix.Portal>
      <Radix.Content className={"popover-panel" + (wide ? " wide" : "")} align={align} sideOffset={8} collisionPadding={12} aria-label={label}>
        {children(() => setOpen(false))}
      </Radix.Content>
    </Radix.Portal>
  </Radix.Root>;
}
