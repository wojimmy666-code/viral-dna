import assert from "node:assert/strict";
import test from "node:test";
import { PHONE_INPUT_PROPS, pastePhone, phoneError, passwordError, setupRequestBody } from "../src/accounts/account-form.js";

test("all front account forms require an eleven-digit mainland mobile number", () => {
  assert.equal(phoneError("13800000001"), "");
  for (const value of ["owner", "admin", "1380000000", "138000000001", "12800000001", "+8613800000001", "１３８０００００００１"]) {
    assert.match(phoneError(value), /11 位中国大陆手机号/);
  }
  assert.equal(PHONE_INPUT_PROPS.type, "tel");
  assert.equal(PHONE_INPUT_PROPS.maxLength, 11);
  assert.equal(PHONE_INPUT_PROPS.inputMode, "numeric");
});

test("passwords permit eight characters without composition rules", () => {
  assert.equal(passwordError("12345678"), "");
  assert.equal(passwordError("abcdefgh"), "");
  assert.equal(passwordError("x".repeat(128)), "");
  assert.equal(passwordError("😀".repeat(128)), "");
  for (const value of ["", "1234567", "x".repeat(129), "😀".repeat(4)]) assert.match(passwordError(value, "新密码"), /新密码需要 8–128/);
});

test("pasted mobile numbers lose outer spaces before native maxlength", () => {
  let prevented = false, value;
  pastePhone({ clipboardData: { getData: () => " 13800000001 " }, preventDefault: () => { prevented = true; } }, next => { value = next; });
  assert.equal(prevented, true); assert.equal(value, "13800000001");
});

test("setup posts only current fields, discarding obsolete code and login password state", () => {
  const draft = { kind: "enterprise", name: "测试企业", username: "13800000001", display_name: "负责人", admin_password: "12345678", owner_password: "abcdefgh", confirm_legacy_ownership: true };
  assert.deepEqual(setupRequestBody({ ...draft, username: " 13800000001 ", setup_token: "old-code", password: "old-password" }), draft);
  assert.equal(Object.hasOwn(setupRequestBody(draft), "setup_token"), false);
});
