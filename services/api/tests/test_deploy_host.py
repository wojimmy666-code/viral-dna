from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn

HOST_PATH = Path(__file__).resolve().parents[3] / "scripts" / "deploy" / "api-host.py"
SPEC = importlib.util.spec_from_file_location("viral_dna_deploy_host_tests", HOST_PATH)
assert SPEC and SPEC.loader
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


@pytest.mark.parametrize("contents", [None, "broken json", "[]", '{}', '{"token":"old"}'])
def test_stop_request_only_matches_current_instance(tmp_path: Path, contents: str | None) -> None:
    request = tmp_path / "api-stop.json"
    if contents is not None:
        request.write_text(contents, encoding="utf-8")
    assert not host.stop_requested(request, "current")
    request.write_text('\ufeff{"token":"current"}', encoding="utf-8")
    assert host.stop_requested(request, "current")


def test_host_state_replacement_is_atomic_and_process_time_is_valid(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    host.write_json(state, {"token": "one"})
    host.write_json(state, {"token": "two"})
    assert json.loads(state.read_text("utf-8")) == {"token": "two"}
    assert not list(tmp_path.glob("*.tmp"))
    assert datetime.fromisoformat(host.process_started_at()) <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_host_uses_single_loopback_worker_and_graceful_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "api.env"
    env_file.write_text("VIRAL_DNA_AUTH_MODE=password\n", encoding="utf-8")
    monkeypatch.setenv("VIRAL_DNA_AUTH_MODE", "password")
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_file))
    settings: dict = {}
    state_ready = asyncio.Event()
    stop_signal = asyncio.Event()

    def config(app: str, **kwargs):
        settings.update(app=app, **kwargs)
        return settings

    class Server:
        started = False

        def __init__(self, config):
            self.config = config

        @property
        def should_exit(self):
            return stop_signal.is_set()

        @should_exit.setter
        def should_exit(self, value):
            if value:
                stop_signal.set()

        async def serve(self):
            self.started = True
            state_ready.set()
            await stop_signal.wait()
            settings["gracefully_stopped"] = True

    monkeypatch.setattr(uvicorn, "Config", config)
    monkeypatch.setattr(uvicorn, "Server", Server)
    args = argparse.Namespace(
        env_file=str(env_file), state_file=str(tmp_path / "state.json"),
        stop_file=str(tmp_path / "stop.json"), release_id="test-release", port=8000,
        stop_timeout=20,
    )
    task = asyncio.create_task(host.serve(args))
    try:
        async with asyncio.timeout(3):
            await state_ready.wait()
            state = json.loads(await asyncio.to_thread(Path(args.state_file).read_text, "utf-8"))
            assert state["releaseId"] == "test-release"
            assert len(state["token"]) == 32
            host.write_json(Path(args.stop_file), {"token": state["token"]})
            assert await task == 0
        assert settings["gracefully_stopped"]
        assert settings["host"] == "127.0.0.1"
        assert settings["workers"] == 1
        assert settings["forwarded_allow_ips"] == "127.0.0.1"
        assert settings["timeout_graceful_shutdown"] == 20
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_host_rejects_non_password_mode_before_writing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "api.env"
    env_file.write_text("VIRAL_DNA_AUTH_MODE=local_bootstrap\n", encoding="utf-8")
    monkeypatch.setenv("VIRAL_DNA_AUTH_MODE", "password")
    monkeypatch.setenv("VIRAL_DNA_ENV_FILE", str(env_file))
    args = argparse.Namespace(env_file=str(env_file), state_file=str(tmp_path / "state.json"))
    with pytest.raises(RuntimeError, match="requires.*password"):
        await host.serve(args)
    assert not await asyncio.to_thread(Path(args.state_file).exists)
