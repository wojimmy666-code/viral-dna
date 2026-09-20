"""Sliding sessions use isolated identities, controlled clocks and no live services."""

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from viral_dna_api.accounts import http, repository, runtime
from viral_dna_api.accounts.repository import AccountError, AccountRepository, token_hash
from viral_dna_api.identity import create_identity_router

PASSWORD = "session-test-12345"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = SimpleNamespace(value=time.time())
    monkeypatch.setattr(repository.time, "time", lambda: clock.value)
    repo = AccountRepository(tmp_path / "auth.db", tmp_path / "tenants")
    repo.bootstrap(
        admin_password=PASSWORD,
        owner_password=PASSWORD,
        kind="enterprise",
        name="测试企业",
        username="13800000001",
        display_name="负责人",
        legacy_root=tmp_path / "legacy",
        account_id=uuid4(),
        workspace_id=uuid4(),
        location_id=uuid4(),
    )
    monkeypatch.setenv("VIRAL_DNA_AUTH_MODE", "password")
    monkeypatch.setenv("VIRAL_DNA_ADMIN_CONSOLE_ENABLED", "true")
    monkeypatch.setattr(http, "account_repository", lambda: repo)
    monkeypatch.setattr(runtime, "account_repository", lambda: repo)
    app = FastAPI()
    app.add_middleware(http.AccountAuthenticationMiddleware)
    app.add_exception_handler(AccountError, lambda request, exc: http.error_response(exc))
    app.include_router(http.create_account_router(None, None), prefix="/api/v1")
    app.include_router(create_identity_router(None), prefix="/api/v1")

    @app.post("/api/v1/fixture-write")
    async def write():
        return {"saved": True}

    return repo, clock, app


@pytest.mark.parametrize("admin", [False, True])
def test_activity_slides_but_reads_do_not_and_absolute_limit_cannot_move(setup, admin):
    repo, clock, _ = setup
    duration = repository.ADMIN_SESSION_SECONDS if admin else repository.SESSION_SECONDS
    maximum = repository.ADMIN_SESSION_MAX_SECONDS if admin else repository.SESSION_MAX_SECONDS
    token = repo.login("admin" if admin else "13800000001", PASSWORD, admin=admin, remote="test")
    start = clock.value
    initial = repo.session(token, admin=admin)
    clock.value += 100
    assert repo.session(token, admin=admin)["session_expires_at"] == start + duration
    assert repo.renew_session(token, admin=admin)["session_expires_at"] == start + duration
    while clock.value < start + maximum - 1:
        clock.value = min(clock.value + duration / 2, start + maximum - 1)
        renewed = repo.renew_session(token, admin=admin)
        assert renewed["session_started_at"] == initial["session_started_at"]
        assert renewed["session_expires_at"] <= start + maximum
        assert renewed["csrf_token"] == initial["csrf_token"]
    clock.value = start + maximum
    for operation in (repo.session, repo.renew_session):
        with pytest.raises(AccountError) as failure:
            operation(token, admin=admin)
        assert failure.value.status == 401


@pytest.mark.parametrize(
    "cause", ["idle", "logout", "disabled_user", "disabled_account", "password"]
)
def test_expired_or_revoked_sessions_are_never_resurrected(setup, cause):
    repo, clock, _ = setup
    token = repo.login("13800000001", PASSWORD, admin=False, remote="test")
    if cause == "idle":
        clock.value += repository.SESSION_SECONDS
    elif cause == "logout":
        repo.logout(token)
    elif cause == "password":
        repo.change_password(token, PASSWORD, "changed-password-123", admin=False)
    else:
        table = "auth_users" if cause == "disabled_user" else "auth_accounts"
        with repo.connect(write=True) as db:
            db.execute(f"UPDATE {table} SET status='disabled'")
    with pytest.raises(AccountError) as failure:
        repo.renew_session(token)
    assert failure.value.status == 401


def test_concurrent_renewal_reuses_one_session_and_preserves_project_lease(setup):
    repo, clock, _ = setup
    token = repo.login("13800000001", PASSWORD, admin=False, remote="test")
    access = repo.session(token)["access"]
    repo.lease(access, "project", editor_id="tab", token="edit", action="acquire")
    clock.value += 301
    with ThreadPoolExecutor(max_workers=4) as pool:
        sessions = list(pool.map(lambda _: repo.renew_session(token), range(8)))
    assert len({item["session_expires_at"] for item in sessions}) == 1
    with repo.connect() as db:
        assert db.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] == 1
        assert db.execute("SELECT session_hash FROM project_edit_leases").fetchone()[
            0
        ] == token_hash(token)


def test_absolute_limit_also_protects_edit_lease(setup):
    repo, clock, _ = setup
    token = repo.login("13800000001", PASSWORD, admin=False, remote="test")
    access = repo.session(token)["access"]
    with repo.connect(write=True) as db:
        db.execute(
            "UPDATE auth_sessions SET created_at=?, expires_at=?",
            (clock.value - repository.SESSION_MAX_SECONDS, clock.value + 3600),
        )
    with pytest.raises(AccountError) as failure:
        repo.lease(access, "project", editor_id="tab", token="edit", action="acquire")
    assert failure.value.status == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_http_renews_cookie_and_server_expiry_with_origin_csrf_and_identity_checks(
    setup, admin
):
    _, clock, app = setup
    prefix = "/api/v1/admin" if admin else "/api/v1"
    cookie = http.ADMIN_COOKIE if admin else http.USER_COOKIE
    other_cookie = http.USER_COOKIE if admin else http.ADMIN_COOKIE
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        headers={"Origin": "https://testserver"},
    ) as client:
        login = await client.post(
            prefix + "/auth/login",
            json={"username": "admin" if admin else "13800000001", "password": PASSWORD},
        )
        assert login.status_code == 200
        session = login.json()
        assert (await client.get(prefix + "/session")).json()["session_expires_at"] == session[
            "session_expires_at"
        ]
        clock.value += 301
        assert (await client.post(prefix + "/auth/refresh")).status_code == 403
        headers = {"X-CSRF-Token": session["csrf_token"]}
        assert (
            await client.post(
                prefix + "/auth/refresh", headers={**headers, "Origin": "https://untrusted.example"}
            )
        ).status_code == 403
        assert (
            await client.post(
                prefix + "/auth/refresh", headers={**headers, "X-Session-Principal": str(uuid4())}
            )
        ).status_code == 409
        renewed = await client.post(prefix + "/auth/refresh", headers=headers)
        assert renewed.status_code == 200
        assert renewed.json()["session_expires_at"] == session["session_expires_at"] + 301
        assert renewed.json()["csrf_token"] == session["csrf_token"]
        assert renewed.headers["set-cookie"].startswith(cookie + "=")
        assert other_cookie + "=" not in renewed.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age="):
            assert flag in renewed.headers["set-cookie"]
        assert "no-store" in renewed.headers["cache-control"]


@pytest.mark.asyncio
async def test_reauthentication_requires_original_user_and_never_steals_another_members_lease(
    setup,
):
    repo, _, app = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        headers={"Origin": "https://testserver"},
    ) as client:
        original = (
            await client.post(
                "/api/v1/auth/login", json={"username": "13800000001", "password": PASSWORD}
            )
        ).json()
        old_token = client.cookies.get(http.USER_COOKIE)
        owner = repo.session(old_token)["access"]
        repo.create_member(
            str(owner.account_id),
            username="13800000002",
            display_name="成员",
            password=PASSWORD,
            actor=str(owner.user_id),
        )
        member_token = repo.login("13800000002", PASSWORD, admin=False, remote="other")
        member = repo.session(member_token)["access"]
        repo.lease(member, "project", editor_id="other-tab", token="other-edit", action="acquire")
        wrong = await client.post(
            "/api/v1/auth/reauthenticate",
            json={
                "username": "13800000002",
                "password": PASSWORD,
                "expected_principal_id": original["user_id"],
            },
        )
        assert wrong.status_code == 409 and "set-cookie" not in wrong.headers
        assert client.cookies.get(http.USER_COOKIE) == old_token
        response = await client.post(
            "/api/v1/auth/reauthenticate",
            json={
                "username": "13800000001",
                "password": PASSWORD,
                "expected_principal_id": original["user_id"],
            },
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == original["user_id"]
        assert response.json()["csrf_token"] != original["csrf_token"]
        with pytest.raises(AccountError):
            repo.session(old_token)
        assert repo.lease(member, "project", editor_id="other-tab", token="other-edit")["editable"]
