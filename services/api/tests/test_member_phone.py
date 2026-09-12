"""Phone changes exercise disposable identity databases, never live accounts."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.accounts import repository as repository_module
from viral_dna_api.accounts.repository import AccountError, AccountRepository

PASSWORD = "phone-change-test-password"
OLD = "13800000001"
NEW = "13900000001"


@pytest.fixture
def context(tmp_path):
    repo = AccountRepository(tmp_path / "identity.sqlite3", tmp_path / "accounts")
    repo.bootstrap(
        admin_password=PASSWORD,
        owner_password=PASSWORD,
        kind="enterprise",
        name="隔离测试企业",
        username=OLD,
        display_name="负责人",
        legacy_root=tmp_path / "legacy",
        account_id=uuid4(),
        workspace_id=uuid4(),
        location_id=uuid4(),
    )
    token = repo.login(OLD, PASSWORD, admin=False, remote="fixture")
    owner = repo.session(token)["access"]
    admin_token = repo.login("admin", PASSWORD, admin=True, remote="fixture-admin")
    admin = repo.session(admin_token, admin=True)["admin_id"]
    return repo, owner, token, admin, admin_token


def change(context, **overrides):
    repo, owner, _, admin, _ = context
    params = dict(
        account_id=str(owner.account_id),
        user_id=str(owner.user_id),
        current_username=OLD,
        username=NEW,
        actor=admin,
    )
    params.update(overrides)
    return repo.change_member_phone(**params)


def snapshot(repo):
    with repo.connect() as db:
        names = [
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        return {
            name: sorted(tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')) for name in names
        }


def test_change_preserves_identity_password_and_workspace_revokes_only_target(context):
    repo, owner, token, admin, admin_token = context
    member = repo.invite(
        str(owner.account_id), username="13800000002", display_name="成员", actor=admin
    )
    repo.activate(member["activation_token"], PASSWORD)
    member_token = repo.login("13800000002", PASSWORD, admin=False, remote="member")
    other = repo.session(member_token)["access"]
    reset = repo.reset_link(str(owner.account_id), str(owner.user_id), admin)
    other_reset = repo.reset_link(str(owner.account_id), str(other.user_id), admin)
    storage_token = repo.issue_storage_token(owner, "device")
    repo.lease(owner, "owner-project", editor_id="owner-tab", token="owner-lease", action="acquire")
    repo.lease(
        other, "member-project", editor_id="member-tab", token="member-lease", action="acquire"
    )
    media = Path(owner.workspace_root) / "retained-media.txt"
    media.write_text("asset / project history fixture", encoding="utf-8")
    before = snapshot(repo)

    result = change(context)

    assert result == {"updated": True, "id": str(owner.user_id), "username": NEW}
    after = snapshot(repo)
    assert after["auth_accounts"] == before["auth_accounts"]
    assert after["auth_account_runtime"] == before["auth_account_runtime"]
    assert after["auth_admins"] == before["auth_admins"]
    expected_users = [list(row) for row in before["auth_users"]]
    for row in expected_users:
        if row[0] == str(owner.user_id):
            row[2] = NEW
    assert after["auth_users"] == sorted(tuple(row) for row in expected_users)
    assert media.read_text("utf-8") == "asset / project history fixture"
    with pytest.raises(AccountError):
        repo.session(token)
    with pytest.raises(AccountError):
        repo.storage_token_session(storage_token["token"])
    with pytest.raises(AccountError):
        repo.activate(reset["activation_token"], PASSWORD)
    with pytest.raises(AccountError):
        repo.login(OLD, PASSWORD, admin=False, remote="old-name")
    new_token = repo.login(NEW, PASSWORD, admin=False, remote="new-name")
    assert repo.session(new_token)["access"].user_id == owner.user_id
    assert repo.session(new_token)["access"].workspace_root == owner.workspace_root
    assert repo.session(member_token)["access"].user_id == other.user_id
    assert repo.session(admin_token, admin=True)["admin_id"] == admin
    assert not repo.lease(other, "owner-project")["occupied"]
    repo.require_lease(other, "member-project", "member-tab", "member-lease")
    with repo.connect() as db:
        assert db.execute(
            "SELECT 1 FROM auth_invitations WHERE user_id=?", (str(other.user_id),)
        ).fetchone()
        audit = db.execute("SELECT * FROM auth_audit WHERE action='user_phone_changed'").fetchone()
        assert audit["actor_id"] == admin
        assert audit["account_id"] == str(owner.account_id)
        assert audit["subject_id"] == str(owner.user_id)
    assert other_reset["activation_token"] not in str(after)


@pytest.mark.parametrize(
    "value", ["admin", "12800000001", "+8613800000001", "１３８０００００００１"]
)
def test_invalid_phone_is_rejected_without_mutation(context, value):
    before = snapshot(context[0])
    with pytest.raises(AccountError) as error:
        change(context, username=value)
    assert error.value.code == "username_invalid"
    assert snapshot(context[0]) == before


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"username": OLD}, "username_unchanged"),
        ({"current_username": "13700000001"}, "username_changed"),
        ({"account_id": str(uuid4())}, "member_missing"),
        ({"user_id": str(uuid4())}, "member_missing"),
        ({"actor": "admin"}, "admin_required"),
    ],
)
def test_validation_and_scope_fail_without_mutation(context, overrides, code):
    before = snapshot(context[0])
    with pytest.raises(AccountError) as error:
        change(context, **overrides)
    assert error.value.code == code
    assert snapshot(context[0]) == before


def test_conflicting_phone_in_another_account_is_rejected(context):
    repo = context[0]
    repo.create_account(
        kind="personal", name="其他账户", username=NEW, display_name="其他用户", actor=context[3]
    )
    before = snapshot(repo)
    with pytest.raises(AccountError) as error:
        change(context)
    assert error.value.code == "username_exists"
    assert snapshot(repo) == before


def test_failure_rolls_back_phone_and_revocations(context, monkeypatch):
    repo = context[0]
    before = snapshot(repo)

    def fail_audit(*args):
        raise sqlite3.OperationalError("simulated audit failure")

    monkeypatch.setattr(repo, "audit", fail_audit)
    with pytest.raises(sqlite3.OperationalError):
        change(context)
    assert snapshot(repo) == before


def test_in_flight_old_phone_login_cannot_create_session_after_change(context, monkeypatch):
    repo = context[0]
    original = repository_module.password_matches

    def rename_before_verification_finishes(password, encoded):
        change(context)
        return original(password, encoded)

    monkeypatch.setattr(repository_module, "password_matches", rename_before_verification_finishes)
    with pytest.raises(AccountError) as error:
        repo.login(OLD, PASSWORD, admin=False, remote="racing-login")
    assert error.value.code == "login_failed"
    with repo.connect() as db:
        assert not db.execute(
            "SELECT 1 FROM auth_sessions WHERE principal_id=?", (str(context[1].user_id),)
        ).fetchone()


def test_concurrent_admin_edits_cannot_overwrite_each_other(context):
    def update(phone):
        try:
            return change(context, username=phone)["username"]
        except AccountError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [NEW, "13700000001"]))
    assert results.count("username_changed") == 1
    with context[0].connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM auth_audit WHERE action='user_phone_changed'"
            ).fetchone()[0]
            == 1
        )


def test_concurrent_users_cannot_claim_the_same_phone(context):
    repo, owner, _, admin, _ = context
    member = repo.invite(
        str(owner.account_id), username="13800000002", display_name="成员", actor=admin
    )

    def update(user):
        try:
            change(context, user_id=user[0], current_username=user[1])
            return "updated"
        except AccountError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [(str(owner.user_id), OLD), (member["id"], "13800000002")]))
    assert sorted(results) == ["updated", "username_exists"]


def test_personal_account_owner_can_change_phone_without_changing_kind(context):
    repo, _, _, admin, _ = context
    person = repo.create_account(
        kind="personal", name="个人账户", username="13700000001", display_name="个人", actor=admin
    )
    repo.activate(person["activation_token"], PASSWORD)
    token = repo.login("13700000001", PASSWORD, admin=False, remote="person")
    before = repo.session(token)["access"]
    change(
        context,
        account_id=person["id"],
        user_id=str(before.user_id),
        current_username="13700000001",
    )
    token = repo.login(NEW, PASSWORD, admin=False, remote="person-new")
    after = repo.session(token)["access"]
    assert after.account_kind == "personal"
    assert after.account_id == before.account_id
    assert after.workspace_root == before.workspace_root


@pytest.mark.parametrize("status", ["pending", "disabled"])
def test_inactive_member_keeps_status_and_must_receive_a_new_invitation(context, status):
    repo, owner, _, admin, _ = context
    member = repo.invite(
        str(owner.account_id), username="13800000003", display_name="成员", actor=admin
    )
    if status == "disabled":
        repo.remove_member(str(owner.account_id), member["id"], admin)
    change(context, user_id=member["id"], current_username="13800000003")
    row = next(row for row in repo.members(str(owner.account_id)) if row["id"] == member["id"])
    assert row["username"] == NEW
    assert row["status"] == status
    with pytest.raises(AccountError):
        repo.activate(member["activation_token"], PASSWORD)
