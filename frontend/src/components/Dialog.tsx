import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

/** A modal dialog; Escape and a click on the backdrop close it. `flush` drops the body padding. */
export function Dialog({ open, title, onClose, children, wide = false, flush = false, footer }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean; flush?: boolean; footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);
  return createPortal(
    <dialog ref={ref} className={"dialog" + (wide ? " wide" : "")} aria-labelledby={titleId}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      {open ? <div className="dialog-surface">
        <header className="dialog-head"><h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}><X /></button>
        </header>
        <div className={"dialog-body" + (flush ? " flush" : "")}>{children}</div>
        {footer ? <footer className="dialog-foot">{footer}</footer> : null}
      </div> : null}
    </dialog>, document.body,
  );
}
