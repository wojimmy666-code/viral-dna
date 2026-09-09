from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from viral_dna_api.accounts.repository import AccountError, AccountRepository, token_hash

PASSWORD = "test-password-12345"


@pytest.fixture
def repo(tmp_path: Path):
    result = AccountRepository(tmp_path / "auth.db", tmp_path / "tenants")
    result.bootstrap(
        admin_password=PASSWORD,
        name="企业甲",
        kind="enterprise",
        username="13800000001",
        display_name="负责人",
        owner_password=PASSWORD,
        legacy_root=tmp_path / "legacy",
        account_id=uuid4(),
        workspace_id=uuid4(),
        location_id=uuid4(),
    )
    return result


def session(repo, name="13800000001", remote="test"):
    token = repo.login(name, PASSWORD, admin=False, remote=remote)
    return token, repo.session(token)["access"]


def test_independent_accounts_and_single_admin(repo):
    _, owner = session(repo)
    other = repo.create_account(
        kind="personal", name="个人乙", username="13900000001", display_name="乙", actor="admin"
    )
    repo.activate(other["activation_token"], PASSWORD)
    _, person = session(repo, "13900000001")
    assert person.account_id != owner.account_id
    assert person.workspace_root != owner.workspace_root
    with pytest.raises(AccountError, match="只有启用的企业"):
        repo.invite(
            str(person.account_id), username="13900000003", display_name="成员", actor="admin"
        )
    with pytest.raises(AccountError, match="独立手机号"):
        repo.invite(str(owner.account_id), username="13900000001", display_name="乙", actor="admin")
    token = repo.login("admin", PASSWORD, admin=True, remote="admin-test")
    with pytest.raises(AccountError, match="请先登录"):
        repo.session(token)
    with repo.connect() as db:
        assert db.execute("SELECT count(*) FROM auth_admins").fetchone()[0] == 1
        assert PASSWORD not in str([tuple(row) for row in db.execute("SELECT * FROM auth_users")])


def test_invitation_is_single_use_and_removal_revokes(repo):
    _, owner = session(repo)
    invited = repo.invite(
        str(owner.account_id), username="13800000002", display_name="成员", actor=str(owner.user_id)
    )
    repo.activate(invited["activation_token"], PASSWORD)
    with pytest.raises(AccountError, match="链接已失效"):
        repo.activate(invited["activation_token"], PASSWORD)
    token, member = session(repo, "13800000002")
    assert member.account_id == owner.account_id
    repo.lease(member, "project-a", editor_id="tab-one", token="lease-token", action="acquire")
    repo.remove_member(str(owner.account_id), str(member.user_id), str(owner.user_id))
    with pytest.raises(AccountError, match="请先登录"):
        repo.session(token)
    assert not repo.lease(owner, "project-a")["occupied"]
    assert len(repo.members(str(owner.account_id))) == 2


def test_lease_race_and_stale_token(repo):
    _, owner = session(repo)

    def acquire(index):
        return repo.lease(
            owner, "project-a", editor_id=f"tab-{index}", token=f"token-{index}", action="acquire"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(acquire, [1, 2]))
    assert sum(s["editable"] for s in states) == 1
    old_generation = next(s["generation"] for s in states if s["editable"])
    with repo.connect(write=True) as db:
        db.execute("UPDATE project_edit_leases SET expires_at=0")
    renewed = repo.lease(owner, "project-a", editor_id="new", token="new-token", action="acquire")
    assert renewed["generation"] == old_generation + 1
    with pytest.raises(AccountError, match="只读"):
        repo.require_lease(owner, "project-a", "tab-1", "token-1")
    repo.lease(owner, "project-a", editor_id="tab-1", token="token-1", action="release")
    repo.require_lease(owner, "project-a", "new", "new-token")


def test_reset_and_disable_revoke_sessions(repo):
    token, owner = session(repo)
    link = repo.reset_link(str(owner.account_id), str(owner.user_id), "admin")
    with repo.connect() as db:
        saved = db.execute("SELECT token_hash FROM auth_invitations").fetchone()[0]
        assert saved == token_hash(link["activation_token"])
    repo.activate(link["activation_token"], "changed-password-123")
    with pytest.raises(AccountError):
        repo.session(token)
    token = repo.login("13800000001", "changed-password-123", admin=False, remote="new")
    repo.update_account(str(owner.account_id), actor="admin", status="disabled")
    with pytest.raises(AccountError):
        repo.session(token)


def test_login_throttles_unknown_names(repo):
    for _ in range(8):
        with pytest.raises(AccountError) as error:
            repo.login("13900000099", PASSWORD, admin=False, remote="abuse")
        assert error.value.status == 401
    with pytest.raises(AccountError) as error:
        repo.login("13900000099", PASSWORD, admin=False, remote="abuse")
    assert error.value.status == 429


def test_removed_member_can_be_reinvited_but_old_credentials_never_return(repo):
    _, owner = session(repo)
    invitation = repo.invite(
        str(owner.account_id), username="13800000004", display_name="成员", actor="owner"
    )
    repo.activate(invitation["activation_token"], PASSWORD)
    old_token, member = session(repo, "13800000004")
    repo.remove_member(str(owner.account_id), str(member.user_id), "owner")
    replacement = repo.restore_member(str(owner.account_id), str(member.user_id), "owner")
    with pytest.raises(AccountError):
        repo.login("13800000004", PASSWORD, admin=False, remote="returning")
    repo.activate(replacement["activation_token"], "brand-new-password-123")
    new_token = repo.login("13800000004", "brand-new-password-123", admin=False, remote="returning")
    assert repo.session(new_token)["access"].user_id == member.user_id
    with pytest.raises(AccountError):
        repo.session(old_token)
    with pytest.raises(AccountError):
        repo.restore_member(str(owner.account_id), str(owner.user_id), "owner")


def test_external_catalog_is_unassigned_by_default_and_cannot_be_shared(repo):
    _, owner = session(repo)
    other = repo.create_account(
        kind="personal", name="隔离账户", username="13900000005", display_name="乙", actor="admin"
    )
    assert repo.managed_asset_project(other["id"]) is None
    repo.update_account(str(owner.account_id), actor="admin", managed_asset_project="catalog-a")
    with pytest.raises(AccountError, match="已属于其他账户"):
        repo.update_account(other["id"], actor="admin", managed_asset_project="catalog-a")
    repo.update_account(other["id"], actor="admin", managed_asset_project="catalog-b")
    assert repo.managed_asset_project(other["id"]) == "catalog-b"
    repo.update_account(other["id"], actor="admin", managed_asset_project="")
    assert repo.managed_asset_project(other["id"]) is None


def test_notification_reads_are_per_member_and_per_event_version(repo):
    _, owner = session(repo)
    member = repo.invite(
        str(owner.account_id), username="13800000006", display_name="成员", actor="owner"
    )
    repo.mark_notifications(str(owner.user_id), [("shared-job", "version-1")])
    assert repo.read_notifications(member["id"]) == {}
    assert repo.read_notifications(str(owner.user_id)) == {"shared-job": "version-1"}
    repo.mark_notifications(member["id"], [("shared-job", "version-2")])
    assert repo.read_notifications(str(owner.user_id))["shared-job"] == "version-1"


def test_expired_invitation_and_expired_session_fail_closed(repo):
    token, owner = session(repo)
    invitation = repo.invite(
        str(owner.account_id), username="13800000007", display_name="成员", actor="owner"
    )
    with repo.connect(write=True) as db:
        db.execute("UPDATE auth_invitations SET expires_at=0")
        db.execute("UPDATE auth_sessions SET expires_at=0")
    with pytest.raises(AccountError, match="链接已失效"):
        repo.activate(invitation["activation_token"], PASSWORD)
    with pytest.raises(AccountError):
        repo.session(token)
    with pytest.raises(AccountError):
        repo.lease(owner, "project-a", editor_id="stale-tab", token="stale", action="acquire")
