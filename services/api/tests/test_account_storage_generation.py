import hashlib
from uuid import uuid4

import pytest
import test_account_storage_http as storage_fixtures

from viral_dna_api.access_context import account_access
from viral_dna_api.accounts.repository import AccountError
from viral_dna_api.models import GenerationCandidate, GenerationRun, ProductionRunStatus

account_sandbox = storage_fixtures.account_sandbox
durable = storage_fixtures.durable


def make_run(box):
    return GenerationRun(
        project_id=box.production.id,
        shot_plan_id=box.shot.id,
        revision_id=uuid4(),
        kind="image",
        provider="isolated-test",
        model="image-test",
        model_snapshot="image-test",
        prompt_version="v1",
        schema_version="v1",
        pricing_version="v1",
        request_fingerprint="1" * 64,
        input_snapshot_relative_path="test/snapshot.json",
        request_payload={"prompt_snapshot": "全局：产品。局部：特写", "candidate_count": 1},
    )


@pytest.mark.asyncio
async def test_adopted_result_cannot_be_purged_and_detached_result_is_retired(durable):
    token = account_access.set(durable.owner)
    try:
        run = make_run(durable)
        await durable.repository.save_generation_run(run)
        path = durable.owner.workspace_root / "deletion-test.png"
        path.write_bytes(b"test")
        candidate = GenerationCandidate(
            generation_run_id=run.id,
            ordinal=1,
            kind="image",
            relative_path=path.name,
            sha256=hashlib.sha256(b"test").hexdigest(),
            metadata_relative_path="test/metadata.json",
        )
        await durable.repository.save_generation_candidate(candidate)
        adopted = durable.shot.model_copy(update={"approved_image_candidate_id": candidate.id})
        await durable.repository.save_shot_plan(adopted)
        service = durable.durable
        key = f"candidate:{candidate.id}"
        service.catalog.trash(key)
        with pytest.raises(AccountError, match="引用"):
            await service.purge(service.catalog.entry(key))
        assert path.is_file()
        await durable.repository.save_shot_plan(durable.shot)
        await service.purge(service.catalog.entry(key))
        assert not path.exists()
        assert (
            str((await durable.repository.get_generation_candidate(candidate.id)).status)
            == "archived"
        )
    finally:
        account_access.reset(token)


@pytest.mark.asyncio
async def test_new_candidate_archives_without_promotion_and_survives_project_removal(durable):  # noqa: F811
    token = account_access.set(durable.owner)
    try:
        service, repository = durable.durable, durable.repository
        run = make_run(durable)
        await repository.save_generation_run(run)
        assert service.catalog.usage()["reserved_bytes"] > 0
        path = durable.owner.workspace_root / "candidate.png"
        payload = b"test generated original"
        path.write_bytes(payload)
        candidate = GenerationCandidate(
            generation_run_id=run.id,
            ordinal=1,
            kind="image",
            relative_path=path.name,
            sha256=hashlib.sha256(payload).hexdigest(),
            metadata_relative_path="test/metadata.json",
            width=8,
            height=8,
        )
        await repository.save_generation_candidate(candidate)
        assert await repository.list_assets() == []
        assert service.catalog.entries(kind="image")["total"] == 1
        await repository.save_generation_run(
            run.model_copy(
                update={"status": ProductionRunStatus.COMPLETED, "actual_cost_micros": 123}
            )
        )
        entry = service.catalog.entry(f"candidate:{candidate.id}")
        assert entry["metadata"]["actual_cost_micros"] == 123
        assert entry["metadata"]["prompt_snapshot"] == run.request_payload["prompt_snapshot"]
        assert service.catalog.usage()["reserved_bytes"] == 0
        await repository.delete_production_project(run.project_id)
        path.unlink()
        assert service.catalog.entries(kind="image")["total"] == 1
        blob = service.catalog.blob(entry["sha256"])
        assert service.catalog.resolve(blob["relative_path"]).read_bytes() == payload
    finally:
        account_access.reset(token)


@pytest.mark.asyncio
async def test_full_quota_stops_run_before_queue_and_failed_save_releases_hold(
    durable,
    monkeypatch,  # noqa: F811
):
    token = account_access.set(durable.owner)
    try:
        run = make_run(durable)
        durable.durable.catalog.set_limit(1, "test")
        with pytest.raises(AccountError, match="空间不足"):
            await durable.repository.save_generation_run(run)
        assert await durable.repository.get_generation_run(run.id) is None
        durable.durable.catalog.set_limit(100_000_000, "test")

        async def fail_write(_run):
            raise RuntimeError("isolated disk failure")

        monkeypatch.setattr(
            durable.repository.backend.repository, "save_generation_run", fail_write
        )
        with pytest.raises(RuntimeError, match="isolated"):
            await durable.repository.save_generation_run(run)
        assert durable.durable.catalog.usage()["reserved_bytes"] == 0
    finally:
        account_access.reset(token)
