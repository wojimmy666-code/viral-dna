import { forwardRef, useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from '@phosphor-icons/react';
import { IconButton } from './Button.jsx';
import './dialogs.css';

let scrollLocks = 0;
let previousOverflow = '';
function lockScroll() {
  if (scrollLocks++ === 0) { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  return () => { if (--scrollLocks === 0) document.body.style.overflow = previousOverflow; };
}

export function DialogHeader({ title, description, titleId, descriptionId, onClose, busy, closeLabel = '关闭', className = '' }) {
  return <header className={`ui-dialog-header ${className}`}>
    <div><h2 id={titleId}>{title}</h2>{description && <p id={descriptionId}>{description}</p>}</div>
    {onClose && <IconButton label={closeLabel} disabled={busy} onClick={onClose}><X size={20} /></IconButton>}
  </header>;
}

/** Shared modal shell. Business state and requests belong to the caller.
 * size: confirm | input | generation | large | wide; open defaults to mounted.
 * Omit title when a complex dialog supplies its own header/body/footer.
 * Draft protection belongs to the form or useActionDialog's in-place decision.
 */
export const Dialog = forwardRef(function Dialog({
  open = true, title, description, children, footer, className = '', size = 'generation', placement = 'center', skin = 'default',
  busy = false, onClose, closeOnBackdrop = false, initialFocusRef, initialFocus = 'first',
  closeLabel, onCancel, onKeyDown, onClick, ...props
}, forwardedRef) {
  const node = useRef(null);
  const callbacks = useRef(null);
  const id = useId();
  callbacks.current = { busy, onClose };
  function close() { if (!callbacks.current.busy) callbacks.current.onClose?.(); }
  useLayoutEffect(() => {
    if (!open) return undefined;
    const dialog = node.current;
    const previous = document.activeElement;
    const unlock = lockScroll();
    if (!dialog.open) dialog.showModal();
    const target = initialFocusRef?.current || (initialFocus === 'cancel'
      ? dialog.querySelector('[data-dialog-cancel]') : initialFocus === 'title' ? dialog :
        dialog.querySelector('[autofocus], input:not([disabled]), textarea:not([disabled]), select:not([disabled])'));
    (target || dialog).focus({ preventScroll: true });
    return () => {
      if (dialog.open) dialog.close();
      unlock();
      if (previous?.isConnected && !previous.closest('[inert]')) previous.focus({ preventScroll: true });
    };
  }, [open]);
  if (!open || typeof document === 'undefined') return null;
  return createPortal(<dialog {...props}
    ref={value => { node.current = value; if (typeof forwardedRef === 'function') forwardedRef(value); else if (forwardedRef) forwardedRef.current = value; }}
    className={`${skin === 'media' ? 'ui-media-dialog' : 'ui-dialog'} ui-dialog-${size} ui-dialog-${placement} ${className}`} tabIndex={-1}
    aria-labelledby={props['aria-labelledby'] || (title ? `${id}-title` : undefined)}
    aria-describedby={props['aria-describedby'] || (description ? `${id}-description` : undefined)}
    aria-busy={busy || undefined}
    onCancel={event => { event.preventDefault(); onCancel?.(event); if (!onCancel) close(); }}
    onKeyDown={event => {
      onKeyDown?.(event);
      // IME Enter commits text, never the form underneath it.
      if (event.key === 'Enter' && (event.nativeEvent.isComposing || event.keyCode === 229)) event.preventDefault();
      if (event.key === 'Escape') event.stopPropagation();
    }}
    onClick={event => {
      event.stopPropagation(); onClick?.(event);
      if (!closeOnBackdrop || event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
    }}>
    {title && <DialogHeader title={title} description={description} titleId={`${id}-title`} descriptionId={`${id}-description`} onClose={onClose ? close : undefined} busy={busy} closeLabel={closeLabel} />}
    {children}
    {footer && <footer className="ui-dialog-footer">{footer}</footer>}
  </dialog>, document.body);
});
