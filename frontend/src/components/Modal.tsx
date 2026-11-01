/** Modale accessible : fermeture par Échap, par clic sur le fond ou par le
 *  bouton, focus placé sur la fenêtre à l'ouverture.
 */

import { useEffect, useRef, type ReactNode } from "react";

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.6rem" }}>
          <h2>{title}</h2>
          <button type="button" onClick={onClose} aria-label="Fermer">
            Fermer
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
