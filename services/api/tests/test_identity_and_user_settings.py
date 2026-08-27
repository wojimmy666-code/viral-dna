from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from viral_dna_api.account_preferences import (
    UserPreferencesRepository,
    UserPreferencesService,
    create_user_preferences_router,
)
from viral_dna_api.identity import create_identity_router
from viral_dna_api.workspace_catalog import Account


class StubAccountContext:
    def __init__(self) -> None:
        self.account = Account(display_name="默认用户")

    async def current_account(self) -> Account:
        return self.account


def build_app(path: Path) -> FastAPI:
    context = StubAccountContext()
    preferences = UserPreferencesService(
        context,  # type: ignore[arg-type]
        UserPreferencesRepository(path),
    )
    app = FastAPI()
    app.include_router(create_identity_router(context), prefix="/api/v1")  # type: ignore[arg-type]
    app.include_router(create_user_preferences_router(preferences), prefix="/api/v1")
    return app


def test_user_and_platform_admin_sessions_are_distinct(tmp_path: Path) -> None:
    with TestClient(build_app(tmp_path / "settings.json")) as client:
        user = client.get("/api/v1/session")
        admin = client.get("/api/v1/admin/session")

    assert user.status_code == 200
    assert user.json()["principal_type"] == "user"
    assert user.json()["display_name"] == "默认用户"
    assert admin.status_code == 200
    assert admin.json()["principal_type"] == "platform_admin"
    assert admin.json()["display_name"] == "本地平台管理员"
    assert admin.json()["admin_id"] != user.json()["user_id"]


def test_user_preferences_are_account_scoped_and_do_not_accept_api_keys(
    tmp_path: Path,
) -> None:
    with TestClient(build_app(tmp_path / "settings.json")) as client:
        initial = client.get("/api/v1/me/settings/preferences")
        assert initial.status_code == 200
        assert initial.json()["settings"]["text_model_alias"] == "qwen37"
        assert {item["alias"] for item in initial.json()["text_models"]} == {
            "qwen37",
            "qwen36flash",
        }
        assert {item["id"] for item in initial.json()["text_model_tasks"]} == {
            "replication_plan",
            "shot_image_prompt",
            "video_prompt",
        }
        revision = initial.json()["revision"]

        updated = client.put(
            "/api/v1/me/settings/preferences",
            json={
                "revision": revision,
                "settings": {
                    "target_model": "generic",
                    "analysis_profile": "quality",
                    "max_cost_cny": 8.5,
                    "image_model_alias": "qwen_image_2_pro",
                    "image_candidate_count": 2,
                    "video_model_alias": "minimax_h3",
                    "video_resolution": "1080P",
                    "text_model_alias": "qwen36flash",
                    "text_model_fallback_enabled": False,
                    "text_model_task_overrides": {"video_prompt": "qwen37"},
                },
            },
        )
        rejected = client.put(
            "/api/v1/me/settings/preferences",
            json={
                "revision": updated.json()["revision"],
                "settings": {
                    **updated.json()["settings"],
                    "api_key": "must-not-be-stored-here",
                },
            },
        )

    assert updated.status_code == 200
    assert updated.json()["settings"]["video_resolution"] == "1080P"
    assert updated.json()["settings"]["text_model_alias"] == "qwen36flash"
    assert updated.json()["settings"]["text_model_fallback_enabled"] is False
    assert updated.json()["settings"]["text_model_task_overrides"] == {
        "video_prompt": "qwen37"
    }
    assert rejected.status_code == 422


def test_user_preferences_reject_unknown_text_model_alias(tmp_path: Path) -> None:
    with TestClient(build_app(tmp_path / "settings.json")) as client:
        initial = client.get("/api/v1/me/settings/preferences").json()
        response = client.put(
            "/api/v1/me/settings/preferences",
            json={
                "revision": initial["revision"],
                "settings": {
                    **initial["settings"],
                    "text_model_alias": "missing-model",
                },
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "文案模型不存在：missing-model"


def test_user_preferences_use_revision_conflict_protection(tmp_path: Path) -> None:
    with TestClient(build_app(tmp_path / "settings.json")) as client:
        initial = client.get("/api/v1/me/settings/preferences").json()
        first = client.put(
            "/api/v1/me/settings/preferences",
            json={"revision": initial["revision"], "settings": initial["settings"]},
        )
        stale = client.put(
            "/api/v1/me/settings/preferences",
            json={"revision": initial["revision"], "settings": initial["settings"]},
        )

    assert first.status_code == 200
    assert stale.status_code == 409
