import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.account_storage.catalog import StorageCatalog
from viral_dna_api.account_storage.transfer import BatchManifest, TransferReceiver
from viral_dna_api.accounts.repository import AccountError


def fixture(tmp_path, payload=b"generated-image"):
    storage = StorageCatalog(tmp_path, str(uuid4()))
    receiver = TransferReceiver(SimpleNamespace(catalog=storage))
    digest = hashlib.sha256(payload).hexdigest()
    workspace = uuid4()
    manifest = BatchManifest.model_validate(
        {
            "id": str(uuid4()),
            "source_workspace_id": str(workspace),
            "entries": [
                {
                    "key": "candidate:test",
                    "kind": "image",
                    "sha256": digest,
                    "metadata": {"filename": "image.png"},
                    "updated_at": 1,
                }
            ],
            "files": [
                {
                    "sha256": digest,
                    "size_bytes": len(payload),
                    "filename": "image.png",
                    "mime_type": "image/png",
                }
            ],
        }
    )
    return storage, receiver, manifest


@pytest.mark.asyncio
async def test_resume_restart_verify_and_idempotent_commit(tmp_path):
    payload = b"generated-image"
    storage, receiver, manifest = fixture(tmp_path, payload)
    first = receiver.begin(manifest)
    upload = first["uploads"][0]
    receiver.chunk(upload["id"], 0, payload[:4])
    receiver = TransferReceiver(
        SimpleNamespace(catalog=StorageCatalog(tmp_path, storage.account_id))
    )
    second = receiver.begin(manifest)
    assert second["uploads"][0]["received"] == 4
    assert storage.usage()["reserved_bytes"] == len(payload)
    with pytest.raises(AccountError, match="尚未"):
        receiver.finish(upload["id"])
    with pytest.raises(AccountError, match="未完成"):
        await receiver.commit(manifest.id)
    receiver.chunk(upload["id"], 4, payload[4:])
    receiver.finish(upload["id"])
    await receiver.commit(manifest.id)
    await receiver.commit(manifest.id)
    assert storage.entries(kind="image")["total"] == 1
    assert storage.usage()["used_bytes"] == len(payload)
    assert storage.usage()["reserved_bytes"] == 0
    # A completely new batch of the same file does not upload or charge again.
    third = receiver.begin(manifest.model_copy(update={"id": uuid4()}))
    assert third["uploads"] == []


def test_manifest_binding_and_bad_chunks(tmp_path):
    storage, receiver, manifest = fixture(tmp_path)
    with pytest.raises(AccountError, match="工作区"):
        receiver.begin(manifest, str(uuid4()))
    upload = receiver.begin(manifest)["uploads"][0]
    with pytest.raises(AccountError, match="进度"):
        receiver.chunk(upload["id"], 1, b"x")
    with pytest.raises(AccountError, match="超过"):
        receiver.chunk(upload["id"], 0, b"x" * 100)
    receiver.chunk(upload["id"], 0, b"x" * manifest.files[0].size_bytes)
    with pytest.raises(AccountError, match="校验"):
        receiver.finish(upload["id"])
    assert receiver.upload(upload["id"])["received"] == 0
    assert storage.usage()["used_bytes"] == 0


def test_server_admission_converts_generation_reservation_without_double_charge(tmp_path):
    storage, receiver, manifest = fixture(tmp_path)
    storage.set_limit(20, "admin")
    run_id = str(uuid4())
    manifest.entries[0].metadata["generation_run_id"] = run_id
    storage.reserve(f"remote-generation:{manifest.source_workspace_id}:{run_id}", 20, "generation")
    receiver.begin(manifest)
    assert storage.usage()["reserved_bytes"] == 20


def test_plain_upload_cannot_exceed_quota(tmp_path):
    storage, receiver, manifest = fixture(tmp_path)
    storage.set_limit(1, "admin")
    with pytest.raises(AccountError, match="空间不足"):
        receiver.begin(manifest)
    assert storage.jobs() == []


def test_explicit_history_purge_releases_only_unreferenced_bytes(tmp_path):
    storage, _, _ = fixture(tmp_path)
    file = tmp_path / "history.png"
    file.write_bytes(b"picture")
    blob = storage.keep_file(file)
    storage.put_entry("one", "image", blob["sha256"], {})
    storage.put_entry("two", "image", blob["sha256"], {})
    storage.trash("one")
    storage.purge("one")
    assert storage.usage()["used_bytes"] == 7
    storage.trash("two")
    storage.purge("two")
    assert storage.usage()["used_bytes"] == 0
    assert not file.exists()


def test_existing_free_thumbnail_must_pass_quota_before_promotion_to_original(tmp_path):
    payload = b"generated-image"
    storage, receiver, manifest = fixture(tmp_path, payload)
    path = tmp_path / "thumbnail.png"
    path.write_bytes(payload)
    storage.keep_file(path, chargeable=False)
    storage.set_limit(len(payload) - 1, "admin")
    with pytest.raises(AccountError, match="空间不足"):
        receiver.begin(manifest)
    assert storage.usage()["used_bytes"] == 0
    storage.set_limit(len(payload), "admin")
    assert receiver.begin(manifest)["uploads"] == []
    assert storage.usage()["used_bytes"] == len(payload)
    assert storage.usage()["reserved_bytes"] == 0


@pytest.mark.asyncio
async def test_abandoned_chunk_reservation_expires_without_deleting_durable_results(tmp_path):
    storage, receiver, manifest = fixture(tmp_path)
    job = receiver.begin(manifest)
    upload = job["uploads"][0]
    receiver.chunk(upload["id"], 0, b"gene")
    with storage.connect(write=True) as db:
        db.execute("UPDATE jobs SET updated_at=0")
    receiver.cleanup_incomplete()
    assert storage.usage()["reserved_bytes"] == 0
    assert not storage.resolve(f"temp/storage-sync/{upload['id']}.part").exists()
    renewed = receiver.begin(manifest)
    assert renewed["uploads"][0]["received"] == 0
