from __future__ import annotations

import asyncio
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from PIL import Image
from test_image_generation import (
    FAKE_TOOL,
    _project,
    _shot,
    isolate_image_settings,
)

from viral_dna_api.image_generation.contracts import AdapterResult, GeneratedImage
from viral_dna_api.image_generation.gateway import ImageGenerationGateway, _filesystem_path
from viral_dna_api.image_generation.local_tool import LocalToolImageAdapter
from viral_dna_api.image_generation.settings import ImageGenerationSettingsService
from viral_dna_api.models import (
    GenerationCandidateStatus,
    ImageGenerationCreate,
    ImageGenerationSettingsUpdate,
    ProductionRevision,
    WorkflowItemStatus,
)
from viral_dna_api.production import ProductionService
from viral_dna_api.store import InMemoryStore
from viral_dna_api.workspace import WorkspaceManager

WRAPPER = Path(__file__).resolve().parents[3] / "scripts" / "codex_imagegen_adapter.py"


def wrapper_functions():
    return runpy.run_path(str(WRAPPER))


def test_capture_is_thread_scoped_incremental_and_idempotent(tmp_path):
    adapter = wrapper_functions()
    generated = tmp_path / "generated"
    own = generated / "own-thread-1234"
    other = generated / "other-thread-1234"
    output = tmp_path / "output"
    for directory in (own, other, output):
        directory.mkdir(parents=True)
    Image.new("RGB", (48, 48), "red").save(other / "foreign.png")
    Image.new("RGB", (48, 48), "blue").save(own / "first.png")
    captured = set()
    options = dict(
        stdout=json.dumps({"type": "thread.started", "thread_id": own.name}),
        generated_root=generated,
        before=set(),
        started_at=time.time() - 2,
        expected_count=2,
        captured_sources=captured,
    )
    first = adapter["_capture_codex_artifacts"](output, **options)
    assert len(first) == 1
    with Image.open(first[0]) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)
    assert adapter["_capture_codex_artifacts"](output, **options) == []
    Image.new("RGB", (48, 48), "green").save(own / "second.png")
    second = adapter["_capture_codex_artifacts"](output, **options)
    assert len(second) == 1
    assert second[0].name == "codex-candidate-002.png"
    assert len(captured) == 2
    assert adapter["_capture_codex_artifacts"](output, **options) == []


def test_capture_waits_for_complete_image_and_never_guesses_global_output(tmp_path):
    adapter = wrapper_functions()
    generated = tmp_path / "generated"
    own = generated / "own-thread-1234"
    own.mkdir(parents=True)
    output = tmp_path / "output"
    output.mkdir()
    original = tmp_path / "valid.png"
    Image.new("RGB", (48, 48), "blue").save(original)
    destination = own / "rendering.png"
    destination.write_bytes(original.read_bytes()[:32])
    options = dict(
        stdout=json.dumps({"type": "thread.started", "thread_id": own.name}),
        generated_root=generated,
        before=set(),
        started_at=time.time() - 2,
        expected_count=1,
        captured_sources=set(),
    )
    assert adapter["_capture_codex_artifacts"](output, **options) == []
    destination.write_bytes(original.read_bytes())
    assert adapter["_capture_codex_artifacts"](output, **{**options, "stdout": ""}) == []
    assert len(adapter["_capture_codex_artifacts"](output, **options)) == 1


def test_lean_prompt_preserves_creative_text_references_size_and_count():
    adapter = wrapper_functions()
    positive = "【全局】暖色低饱和。\n【局部】保持图1的产品结构，35mm，侧逆光。"
    negative = "不要改变品牌色，不增加文字。"
    prompt = adapter["_codex_generation_prompt"](
        {
            "prompt": {"positive": positive, "negative": negative},
            "output": {"width": 1280, "height": 720},
            "candidate_count": 2,
        },
        [("product", Path("product.png")), ("scene", Path("factory.png"))],
    )
    assert prompt.count(positive) == prompt.count(negative) == 1
    assert prompt.index("product.png") < prompt.index("factory.png")
    assert "1280 × 720" in prompt and "生成 2 张" in prompt
    assert "每完成一张" in prompt and "不删减或扩写" in prompt
    assert adapter["_parser"]().get_default("reasoning_effort") == "medium"


async def configured_gateway(tmp_path, monkeypatch, *, repository=None):
    isolate_image_settings(tmp_path, monkeypatch)
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    tool = tmp_path / "stream-tool.py"
    stream = """
    import time
    timing = {"schema_version": "viral-dna-image-timing/v1",
              "request_id": request["request_id"], "elapsed_ms": 12, "events": []}
    (output_root / "timing.json").write_text(json.dumps(timing), "utf-8")
    progress = {"protocol_version": "viral-dna-image-tool/v1",
                "request_id": request["request_id"], "candidates": candidates[:1]}
    (output_root / "progress.json").write_text(json.dumps(progress), "utf-8")
    deadline = time.monotonic() + 12
    while not (request_path.parent / "release").exists():
        if time.monotonic() > deadline:
            raise SystemExit("test release timed out")
        time.sleep(0.02)
    if (request_path.parent / "fail").exists():
        raise SystemExit("second candidate failed")
    if (request_path.parent / "reorder").exists():
        candidates.reverse()
"""
    tool.write_text(
        FAKE_TOOL.replace(
            '    (output_root / "result.json")', stream + '    (output_root / "result.json")'
        ),
        "utf-8",
    )
    settings = ImageGenerationSettingsService()
    await settings.update(
        ImageGenerationSettingsUpdate(
            execution_mode="local_tool",
            local_executable_path=sys.executable,
            local_fixed_args=[str(tool)],
            local_cost_source="unmetered",
            local_proxy_mode="disabled",
            local_concurrency=2,
        )
    )
    workspace = WorkspaceManager()
    return ImageGenerationGateway(workspace, settings, repository=repository), workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "reorder"])
async def test_gateway_publishes_first_image_before_exit_and_keeps_it_on_error(
    tmp_path,
    monkeypatch,
    outcome,
):
    gateway, workspace = await configured_gateway(tmp_path, monkeypatch)
    project = _project()
    shot = _shot(project.id)
    run_id = uuid4()
    root = _filesystem_path(
        workspace.production_shot_root(project.record_id, project.id, shot.id)
        / "images"
        / str(run_id)
    )
    root.mkdir(parents=True)
    if outcome == "failure":
        (root / "fail").touch()
    if outcome == "reorder":
        (root / "reorder").touch()
    cancellation = Event()
    published = []

    async def receive(candidate):
        published.append(candidate)
        if len(published) == 1:
            assert not (root / "tool-output" / "result.json").exists()
            assert _filesystem_path(workspace.resolve(candidate.relative_path)).is_file()
            if outcome == "cancel":
                cancellation.set()
            else:
                (root / "release").touch()

    run, candidates = await gateway.generate(
        project,
        shot,
        shot.revision_id,
        [],
        [],
        candidate_count=2,
        source_path=None,
        input_mode="text_to_image",
        run_id=run_id,
        on_candidate=receive,
        cancel_event=cancellation,
    )
    assert len(published) == (2 if outcome == "success" else 1)
    assert [item.id for item in candidates] == [item.id for item in published]
    assert len({item.id for item in candidates}) == len(candidates)
    timing = run.execution_summary["timing"]
    assert timing["phase"] == ("completed" if outcome == "success" else "failed")
    assert timing["first_candidate_ms"] <= timing["elapsed_ms"]
    assert timing["adapter_execution_ms"] >= 0
    assert timing["slot_wait_ms"] >= 0
    assert timing["candidate_publication_ms"] >= 0
    assert run.execution_summary["codex_timing"]["request_id"] == str(run_id)
    saved_timing = json.loads((root / "gateway-timing.json").read_text("utf-8"))
    assert saved_timing == {"request_id": str(run_id), **timing}
    if outcome == "success":
        assert run.status == "completed"
    else:
        assert run.status == "failed"
        expected_error = {
            "cancel": "generation_cancelled",
            "failure": "local_tool_failed",
            "reorder": "local_tool_output_changed",
        }[outcome]
        assert run.error_code == expected_error
        assert _filesystem_path(workspace.resolve(candidates[0].relative_path)).is_file()


@pytest.mark.asyncio
async def test_shared_local_slots_allow_two_tasks_and_queue_the_third(tmp_path, monkeypatch):
    gateway, _workspace = await configured_gateway(tmp_path, monkeypatch)
    release = asyncio.Event()
    two_started = asyncio.Event()
    active = 0
    maximum = 0
    started = 0
    image_path = tmp_path / "result.png"
    Image.new("RGB", (48, 48), "blue").save(image_path)

    async def generate(_self, request):
        nonlocal active, maximum, started
        active += 1
        started += 1
        maximum = max(maximum, active)
        if active == 2:
            two_started.set()
        try:
            await release.wait()
            return AdapterResult(images=(GeneratedImage(image_path.read_bytes(), "image/png"),))
        finally:
            active -= 1

    monkeypatch.setattr(LocalToolImageAdapter, "generate", generate)
    project = _project()
    tasks = [
        asyncio.create_task(
            gateway.generate(
                project,
                _shot(project.id),
                uuid4(),
                [],
                [],
                candidate_count=1,
                source_path=None,
                input_mode="text_to_image",
                reuse_cache=False,
            )
        )
        for _ in range(3)
    ]
    try:
        await asyncio.wait_for(two_started.wait(), timeout=5)
        await asyncio.sleep(0.1)
        assert started == maximum == 2
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    assert started == 3 and maximum == 2
    assert all(run.status == "completed" for run, _ in results)
    assert max(run.execution_summary["timing"]["slot_wait_ms"] for run, _ in results) >= 50


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "adopted"])
async def test_production_exposes_partial_media_and_preserves_user_choice(
    tmp_path,
    monkeypatch,
    outcome,
):
    repository = InMemoryStore()
    gateway, workspace = await configured_gateway(tmp_path, monkeypatch, repository=repository)
    project = _project().model_copy(update={"current_revision_id": uuid4()})
    shot = _shot(project.id).model_copy(update={"revision_id": project.current_revision_id})
    workspace.initialize_production(project.record_id, project.id)
    await repository.save_production_project(project)
    await repository.save_shot_plan(shot)
    service = ProductionService(repository, workspace, image_gateway=gateway)

    async def prepare_revision(next_project, kind, summary, *, revision_id, **_kwargs):
        revision = ProductionRevision(
            id=revision_id,
            project_id=project.id,
            parent_revision_id=next_project.current_revision_id,
            revision_number=2,
            change_kind=kind,
            change_summary=summary,
            snapshot_relative_path=f"revisions/{revision_id}.json",
        )
        return next_project.model_copy(update={"current_revision_id": revision_id}), revision

    monkeypatch.setattr(service, "_prepare_revision", prepare_revision)
    queued = await service._enqueue_image_run(
        shot.id,
        ImageGenerationCreate(
            expected_revision_id=project.current_revision_id,
            candidate_count=2,
            execution_mode="local_tool",
            input_mode="text_to_image",
            allow_unknown_cost=True,
        ),
    )
    root = _filesystem_path(
        workspace.production_shot_root(project.record_id, project.id, shot.id)
        / "images"
        / str(queued.id)
    )
    if outcome == "failure":
        (root / "fail").touch()
    cancellation = Event()
    task = asyncio.create_task(service._run_queued_image(queued.id, cancellation))
    try:
        deadline = time.monotonic() + 6
        while not (available := await repository.list_generation_candidates(queued.id)):
            if task.done() or time.monotonic() > deadline:
                pytest.fail(str(await repository.get_generation_run(queued.id)))
            await asyncio.sleep(0.025)
        response = await service.get_generation_run(queued.id)
        assert response.status == "running" and len(response.candidates) == 1
        assert not (root / "tool-output" / "result.json").exists()
        first = available[0]
        previews = await service._image_navigation_previews(project.id, [shot])
        assert previews[shot.id]["candidate_id"] == str(first.id)
        await repository.save_generation_candidate(
            first.model_copy(update={"status": GenerationCandidateStatus.SELECTED})
        )
        if outcome == "adopted":
            beat = shot.visual_beats[0].model_copy(
                update={
                    "image_status": WorkflowItemStatus.APPROVED,
                    "approved_image_candidate_id": first.id,
                }
            )
            await repository.save_shot_plan(
                shot.model_copy(
                    update={
                        "visual_beats": [beat],
                        "image_status": WorkflowItemStatus.APPROVED,
                        "approved_image_candidate_id": first.id,
                    }
                )
            )
        if outcome == "cancel":
            cancellation.set()
    finally:
        (root / "release").touch()
        await asyncio.wait_for(task, timeout=8)
    response = await service.get_generation_run(queued.id)
    assert len(response.candidates) == (2 if outcome in {"success", "adopted"} else 1)
    assert (await repository.get_generation_candidate(first.id)).status == "selected"
    assert (
        response.status
        == {
            "success": "completed",
            "adopted": "completed",
            "failure": "failed",
            "cancel": "cancelled",
        }[outcome]
    )
    if outcome == "adopted":
        current_shot = await repository.get_shot_plan(shot.id)
        assert current_shot.approved_image_candidate_id == first.id
        assert current_shot.visual_beats[0].image_status == "approved"


@pytest.mark.asyncio
async def test_wrapper_detects_first_file_while_codex_is_still_running(tmp_path):
    fake = tmp_path / "codex.py"
    fake.write_text(
        """
import json, os, sys, time
from pathlib import Path
from PIL import Image
if "--version" in sys.argv:
    print("codex-cli 99-test")
    raise SystemExit(0)
root = Path(sys.argv[sys.argv.index("--cd") + 1])
output = Path(os.environ["CODEX_HOME"]) / "generated_images" / "own-thread-1234"
output.mkdir(parents=True)
sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": output.name}), flush=True)
Image.new("RGB", (48, 48), "blue").save(output / "first.png")
deadline = time.monotonic() + 12
while not (root / "release").exists():
    if time.monotonic() > deadline:
        raise SystemExit("test release timed out")
    time.sleep(0.02)
Image.new("RGB", (48, 48), "red").save(output / "second.png")
print(json.dumps({"type": "turn.completed"}), flush=True)
""",
        "utf-8",
    )
    root = tmp_path / "run"
    root.mkdir()
    request_path = root / "request.json"
    request_id = str(uuid4())
    request_path.write_text(
        json.dumps(
            {
                "protocol_version": "viral-dna-image-tool/v1",
                "request_id": request_id,
                "candidate_count": 2,
                "output": {"width": 48, "height": 48},
                "prompt": {"positive": "保留画面要求", "negative": "不要文字"},
                "inputs": [],
            }
        ),
        "utf-8",
    )
    output = root / "tool-output"
    task = asyncio.create_task(
        asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                str(WRAPPER),
                "--codex-executable",
                sys.executable,
                "--codex-fixed-arg",
                str(fake),
                "--codex-runner",
                "exec",
                "generate",
                "--request",
                str(request_path),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "CODEX_HOME": str(tmp_path / "codex-home")},
        )
    )
    try:
        deadline = time.monotonic() + 8
        while not (output / "progress.json").exists():
            if task.done():
                pytest.fail((await task).stderr)
            assert time.monotonic() < deadline
            await asyncio.sleep(0.025)
        progress = json.loads((output / "progress.json").read_text("utf-8"))
        assert progress["request_id"] == request_id
        assert len(progress["candidates"]) == 1
        assert not task.done() and not (output / "result.json").exists()
    finally:
        (root / "release").touch()
        result = await task
    assert result.returncode == 0, result.stderr
    final = json.loads((output / "result.json").read_text("utf-8"))
    assert len(final["candidates"]) == 2
    assert final["candidates"][0] == progress["candidates"][0]
