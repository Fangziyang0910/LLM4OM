import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function Dialog({ open, title, onClose, children, wide = false }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);
  return createPortal(
    <dialog ref={ref} className={"dialog" + (wide ? " dialog-wide" : "")} aria-labelledby={titleId}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="dialog-surface">
        <header className="dialog-heading"><h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-button" aria-label={`关闭${title}`} onClick={onClose}>×</button>
        </header>
        <div className="dialog-body">{children}</div>
      </div>
    </dialog>, document.body,
  );
}
