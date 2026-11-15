"use client";

import { useEffect, useRef, type ReactNode } from "react";

export default function DetailDialog({children, onClose, title="收藏內容", autoFocusClose = true}: {children: ReactNode; onClose: () => void; title?:string; autoFocusClose?: boolean}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    dialog.querySelector<HTMLElement>("[data-dialog-initial-focus]")?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
    };
  }, []);

  return <dialog ref={dialogRef} className="detail-dialog" aria-labelledby="detail-dialog-title" onCancel={event => {event.preventDefault(); onClose();}}>
    <div className="detail-dialog-heading">
      <h2 id="detail-dialog-title">{title}</h2>
      <button type="button" className="text-button" onClick={onClose} autoFocus={autoFocusClose}>關閉 ×</button>
    </div>
    <div className="detail-dialog-body">{children}</div>
  </dialog>;
}
