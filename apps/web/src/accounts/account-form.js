export const PHONE_PATTERN = "1[3-9][0-9]{9}";
export const PHONE_ERROR = "手机号必须为 11 位中国大陆手机号";
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;
export const PHONE_INPUT_PROPS = {
  type: "tel", inputMode: "numeric", minLength: 11, maxLength: 11,
  pattern: PHONE_PATTERN, placeholder: "11 位手机号", title: PHONE_ERROR,
  autoComplete: "username",
};

export function phoneError(value) {
  return new RegExp(`^${PHONE_PATTERN}$`).test(String(value || "").trim()) ? "" : PHONE_ERROR;
}

export function pastePhone(event, setValue) {
  const value = event.clipboardData?.getData("text")?.trim();
  if (!value || phoneError(value)) return;
  // Normalize before native maxlength can truncate a pasted number with spaces.
  event.preventDefault();
  setValue(value);
}

export function passwordError(value, label = "密码") {
  const length = [...String(value || "")].length;
  return length >= PASSWORD_MIN_LENGTH && length <= PASSWORD_MAX_LENGTH
    ? "" : `${label}需要 8–128 个字符`;
}

export function setupRequestBody(draft) {
  // Explicit fields also discard initialization-code state retained by an old tab/HMR.
  return {
    kind: draft.kind, name: draft.name, username: draft.username.trim(),
    display_name: draft.display_name, admin_password: draft.admin_password,
    owner_password: draft.owner_password, confirm_legacy_ownership: draft.confirm_legacy_ownership,
  };
}
