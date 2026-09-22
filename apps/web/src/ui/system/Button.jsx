import { forwardRef } from "react";
import "./buttons.css";

const roles = {
  primary: "primary-button",
  secondary: "secondary-button",
  text: "text-button",
  quiet: "text-button quiet-button",
  warning: "warning-button",
  danger: "danger-button",
};

// Keep existing layout hooks during migration. New call sites use variant/size.
function legacyVariant(className) {
  const classes = className.split(/\s+/);
  return Object.entries(roles).find(([, value]) => classes.includes(value))?.[0];
}

/**
 * Native action button; defaults to type="button", never submits implicitly.
 * variant: primary | secondary | text | quiet | warning | danger.
 * size: default (40px) | compact (36px) | prominent (44px).
 * loading is controlled by the caller: no implicit requests, retries or timers.
 * loadingLabel reserves space in both states. Existing refs/form/ARIA props pass through.
 */
export const Button = forwardRef(function Button({
  children, className = "", variant, size = "default", fullWidth = false,
  loading = false, loadingLabel, icon, disabled = false, type = "button", onClick,
  ...props
}, ref) {
  const role = variant || legacyVariant(className) || "secondary";
  const blocked = disabled || loading;
  const contents = <>{icon && <span className="ui-button-icon" aria-hidden="true">{icon}</span>}{children}</>;
  return <button
    {...props}
    ref={ref}
    type={type}
    className={["ui-button", roles[role] || roles.secondary, size !== "default" && size, fullWidth && "full", className].filter(Boolean).join(" ")}
    disabled={blocked}
    aria-busy={loading || undefined}
    onClick={event => {
      if (blocked) { event.preventDefault(); return; }
      onClick?.(event);
    }}
  >
    {loadingLabel || loading ? <span className="ui-button-content">
      <span className="ui-button-idle" aria-hidden={loading || undefined}>{contents}</span>
      <span className="ui-button-pending" aria-hidden={!loading || undefined}>
        <span className="ui-button-spinner" aria-hidden="true" />{loadingLabel || children}
      </span>
    </span> : contents}
  </button>;
});

/** Icon-only actions must supply label, aria-label or title. Navigation stays a link. */
export const IconButton = forwardRef(function IconButton({ label, title, className = "", variant, ...props }, ref) {
  return <Button
    {...props}
    ref={ref}
    variant={variant || (className.split(/\s+/).includes("bordered") ? "secondary" : "quiet")}
    className={`icon-button ${className}`}
    title={title || label}
    aria-label={label || props["aria-label"] || title}
  />;
});
