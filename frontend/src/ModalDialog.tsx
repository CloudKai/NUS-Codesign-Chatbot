/** Modal dialog over the native showModal contract: focus is contained while
 * open, Escape dismisses, the backdrop renders, and closing returns focus to
 * the element that opened it. The production CSP keeps `style-src 'self'`, so
 * dialog positioning stays in styles.css.
 */
import { useLayoutEffect, useRef, type ReactNode } from 'react';

export function ModalDialog({ label, className = 'course-dialog', onClose, children }: {
  label: string; className?: string; onClose: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog || dialog.open) return;
    // jsdom has no showModal; every supported browser does, so tests exercise
    // the non-modal fallback while production gets the real modal contract.
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    return () => {
      // Closing before removal restores focus to the opener; Escape already
      // closed the dialog before this cleanup runs.
      if (dialog.open) {
        if (typeof dialog.close === 'function') dialog.close();
        else dialog.removeAttribute('open');
      }
    };
  }, []);
  return <dialog ref={ref} className={className} aria-label={label} onClose={onClose}>{children}</dialog>;
}
