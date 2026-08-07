from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from viral_dna_api.notifications import (
    AccountNotification,
    InMemoryNotificationRepository,
    NotificationService,
    SQLiteNotificationRepository,
)
from viral_dna_api.workspace import WorkspaceManager
from viral_dna_api.workspace_catalog import (
    AccountContextService,
    InMemoryAccountCatalogRepository,
)


def notification(account_id, event_key: str, *, status: str = "in_progress"):
    return AccountNotification(
        account_id=account_id,
        category="video_generation",
        level="info" if status == "in_progress" else "success",
        status=status,
        title="视频生成已开始" if status == "in_progress" else "视频候选已生成",
        message="百炼 Wan 2.7",
        event_key=event_key,
        action_kind="production_shot",
        action_label="查看候选",
        action_payload={"project_id": str(uuid4())},
    )


@pytest.mark.asyncio
async def test_sqlite_notifications_are_account_scoped_and_update_in_place(
    tmp_path: Path,
) -> None:
    repository = SQLiteNotificationRepository(tmp_path / "notifications.sqlite3")
    await repository.initialize()
    first_account = uuid4()
    second_account = uuid4()

    queued = await repository.upsert(notification(first_account, "generation:run-1"))
    completed = await repository.upsert(
        notification(first_account, "generation:run-1", status="succeeded")
    )
    await repository.upsert(notification(second_account, "generation:run-2"))

    assert completed.id == queued.id
    assert completed.status == "succeeded"
    assert completed.read_at is None
    first_feed = await repository.list_for_account(first_account)
    second_feed = await repository.list_for_account(second_account)
    assert [item.id for item in first_feed] == [queued.id]
    assert len(second_feed) == 1

    marked = await repository.mark_read(first_account, queued.id, completed.updated_at)
    assert marked is not None
    assert marked.read_at is not None
    assert await repository.mark_read(second_account, queued.id, completed.updated_at) is None


@pytest.mark.asyncio
async def test_notification_service_uses_current_account_and_marks_all_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(tmp_path / ".env.local"))
    context = AccountContextService(
        InMemoryAccountCatalogRepository(),
        WorkspaceManager(),
    )
    service = NotificationService(InMemoryNotificationRepository(), context)

    created = await service.publish(
        category="video_generation",
        level="error",
        status="failed",
        title="视频生成失败：API 余额不足",
        message="请充值或切换模型。",
        event_key="generation:balance-test",
        action_kind="model_settings",
        action_label="检查模型设置",
        action_payload={"run_id": str(uuid4())},
    )
    feed = await service.list_notifications()
    assert feed.unread_count == 1
    assert feed.items[0].account_id == (await context.current_account()).id
    assert feed.items[0].workspace_id == (await context.ensure_current()).active_workspace.id

    marked = await service.mark_read(created.id)
    assert marked.read_at is not None
    assert (await service.list_notifications()).unread_count == 0

    await service.publish(
        category="export",
        level="success",
        status="succeeded",
        title="导出完成",
        message="文件已保存到工作区。",
        event_key="export:1",
    )
    result = await service.mark_all_read()
    assert result.updated_count == 1
    assert (await service.list_notifications()).unread_count == 0


def test_notification_rejects_sensitive_action_payload() -> None:
    with pytest.raises(ValidationError, match="密钥或认证信息"):
        AccountNotification(
            account_id=uuid4(),
            category="system",
            level="error",
            status="failed",
            title="配置失败",
            event_key="settings:1",
            action_payload={"api_key": "should-never-be-stored"},
        )
