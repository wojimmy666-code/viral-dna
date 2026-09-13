import assert from "node:assert/strict";
import test from "node:test";
import { destinationAfterLogin, loginHref, safeLoginDestination } from "../src/accounts/login-destination.js";

test("login return preserves approved internal routes and rejects external/administrative targets", () => {
  for (const target of ["/projects/new", "/skills", "/skills/product-story/start", "/projects/abc?tab=images#shot-1", "/account/storage"]) {
    assert.equal(safeLoginDestination(target), target);
    assert.equal(new URLSearchParams(loginHref(target).split("?")[1]).get("returnTo"), target);
  }
  for (const target of [null, "", "https://evil.example", "//evil.example", "/\\evil.example", "/%5cevil.example", "/%2fevil.example", "/projects/../../admin/accounts", "/login", "/activate", "/api/v1/assets", "/admin/accounts", "/projects\n/evil", "/projects/%00", "/projects/%zz"]) {
    assert.equal(safeLoginDestination(target), "/projects", String(target));
  }
});

test("direct protected links and explicit public CTAs return to the intended page", () => {
  assert.equal(destinationAfterLogin({ pathname: "/login", search: "?returnTo=%2Fskills", hash: "" }), "/skills");
  assert.equal(destinationAfterLogin({ pathname: "/projects/new", search: "", hash: "" }), "/projects/new");
  assert.equal(destinationAfterLogin({ pathname: "/login", search: "", hash: "" }), "/projects");
  assert.equal(destinationAfterLogin({ pathname: "/admin/login", search: "?returnTo=%2Fskills", hash: "" }, true), "/admin/accounts");
});
