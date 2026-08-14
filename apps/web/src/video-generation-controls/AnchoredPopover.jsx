import { useCallback, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";

const VIEWPORT_GAP = 12;
const ANCHOR_GAP = 8;
const MINIMUM_POPOVER_HEIGHT = 220;

function setPixelStyle(element, property, value) {
  const nextValue = `${Math.max(0, Math.round(value * 100) / 100)}px`;
  if (element.style[property] !== nextValue) element.style[property] = nextValue;
}

function naturalPopoverHeight(popover) {
  const popoverStyle = window.getComputedStyle(popover);
  const borderHeight = (
    (Number.parseFloat(popoverStyle.borderTopWidth) || 0)
    + (Number.parseFloat(popoverStyle.borderBottomWidth) || 0)
  );

  return Array.from(popover.children).reduce((height, child) => {
    const childStyle = window.getComputedStyle(child);
    return (
      height
      + child.scrollHeight
      + (Number.parseFloat(childStyle.marginTop) || 0)
      + (Number.parseFloat(childStyle.marginBottom) || 0)
    );
  }, borderHeight);
}

export function AnchoredPopover({
  anchorRef,
  children,
  className = "",
  id,
  labelledBy,
  onClose,
  open,
  preferredWidth = 420,
}) {
  const popoverRef = useRef(null);

  const updatePosition = useCallback(() => {
    const anchor = anchorRef?.current;
    const popover = popoverRef.current;
    if (!anchor || !popover || typeof window === "undefined") return;

    const anchorRect = anchor.getBoundingClientRect();
    const visualViewport = window.visualViewport;
    const viewportLeft = visualViewport?.offsetLeft || 0;
    const viewportTop = visualViewport?.offsetTop || 0;
    const viewportWidth = visualViewport?.width || window.innerWidth;
    const viewportHeight = visualViewport?.height || window.innerHeight;
    const viewportRight = viewportLeft + viewportWidth;
    const viewportBottom = viewportTop + viewportHeight;
    const width = Math.min(preferredWidth, Math.max(0, viewportWidth - VIEWPORT_GAP * 2));

    setPixelStyle(popover, "width", width);

    const naturalHeight = naturalPopoverHeight(popover);
    const availableAbove = Math.max(
      0,
      anchorRect.top - viewportTop - VIEWPORT_GAP - ANCHOR_GAP,
    );
    const availableBelow = Math.max(
      0,
      viewportBottom - anchorRect.bottom - VIEWPORT_GAP - ANCHOR_GAP,
    );
    const placeAbove = availableAbove >= Math.min(naturalHeight, 320)
      || availableAbove > availableBelow;
    const availableHeight = placeAbove ? availableAbove : availableBelow;
    const viewportAvailableHeight = Math.max(0, viewportHeight - VIEWPORT_GAP * 2);
    const useViewportFallback = availableHeight < Math.min(
      MINIMUM_POPOVER_HEIGHT,
      viewportAvailableHeight,
    );
    const finalAvailableHeight = useViewportFallback
      ? viewportAvailableHeight
      : availableHeight;

    setPixelStyle(popover, "maxHeight", Math.min(naturalHeight, finalAvailableHeight));
    const renderedHeight = popover.getBoundingClientRect().height;
    const left = Math.min(
      Math.max(viewportLeft + VIEWPORT_GAP, anchorRect.left),
      Math.max(viewportLeft + VIEWPORT_GAP, viewportRight - width - VIEWPORT_GAP),
    );
    const top = useViewportFallback
      ? viewportTop + VIEWPORT_GAP
      : placeAbove
        ? Math.max(viewportTop + VIEWPORT_GAP, anchorRect.top - renderedHeight - ANCHOR_GAP)
      : Math.min(
        viewportBottom - renderedHeight - VIEWPORT_GAP,
        anchorRect.bottom + ANCHOR_GAP,
      );

    setPixelStyle(popover, "left", left);
    setPixelStyle(popover, "top", Math.max(viewportTop + VIEWPORT_GAP, top));
    popover.style.visibility = "visible";
    popover.dataset.placement = useViewportFallback
      ? "viewport"
      : placeAbove
        ? "above"
        : "below";
  }, [anchorRef, preferredWidth]);

  useLayoutEffect(() => {
    if (!open || typeof window === "undefined") return undefined;

    function handleAncestorScroll(event) {
      if (popoverRef.current?.contains(event.target)) return;
      updatePosition();
    }

    updatePosition();
    const frame = window.requestAnimationFrame(updatePosition);
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(updatePosition);
    if (popoverRef.current) observer?.observe(popoverRef.current);

    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", handleAncestorScroll, {
      capture: true,
      passive: true,
    });
    window.visualViewport?.addEventListener("resize", updatePosition);
    window.visualViewport?.addEventListener("scroll", updatePosition);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", handleAncestorScroll, true);
      window.visualViewport?.removeEventListener("resize", updatePosition);
      window.visualViewport?.removeEventListener("scroll", updatePosition);
    };
  }, [open, updatePosition]);

  useLayoutEffect(() => {
    if (!open || typeof document === "undefined") return undefined;

    function handlePointerDown(event) {
      if (popoverRef.current?.contains(event.target)) return;
      if (anchorRef?.current?.contains(event.target)) return;
      onClose();
    }

    function handleKeyDown(event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
      window.requestAnimationFrame(() => anchorRef?.current?.focus());
    }

    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [anchorRef, onClose, open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      aria-labelledby={labelledBy}
      className={`video-generation-popover ${className}`.trim()}
      id={id}
      ref={popoverRef}
      role="dialog"
      style={{ visibility: "hidden" }}
    >
      {children}
    </div>,
    document.body,
  );
}
