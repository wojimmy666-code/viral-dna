from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from viral_dna_api.account_storage.catalog import GB, StorageCatalog
from viral_dna_api.accounts.repository import AccountError


def catalog(tmp_path, kind="personal"):
    return StorageCatalog(tmp_path, str(uuid4()), kind)


def test_defaults_and_owner_isolation(tmp_path):
    personal = catalog(tmp_path / "personal")
    enterprise = catalog(tmp_path / "enterprise", "enterprise")
    assert personal.usage()["limit_bytes"] == 2 * GB
    assert enterprise.usage()["limit_bytes"] == 10 * GB
    with pytest.raises(AccountError, match="其他账户"):
        catalog(tmp_path / "personal")


def test_reservations_are_atomic_and_idempotent(tmp_path):
    storage = catalog(tmp_path)
    storage.set_limit(100, "admin", "test")

    def reserve(index):
        try:
            storage.reserve(str(index), 60)
            return True
        except AccountError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [1, 2]))
    assert results.count(True) == 1
    storage.reserve(str(results.index(True) + 1), 60)
    assert storage.usage()["reserved_bytes"] == 60
    with pytest.raises(AccountError, match="低于"):
        storage.set_limit(59, "admin")
    assert len(storage.audit()) == 1


def test_history_and_asset_share_capacity_and_preserve_file(tmp_path):
    storage = catalog(tmp_path)
    source = tmp_path / "original.png"
    source.write_bytes(b"media-content")
    blob = storage.keep_file(source)
    storage.put_entry("candidate:1", "image", blob["sha256"], {"name": "picture"})
    storage.put_entry("asset:1", "asset", blob["sha256"], {"name": "picture asset"})
    storage.keep_file(source)
    assert storage.usage()["used_bytes"] == len(b"media-content")
    source.unlink()
    assert storage.resolve(blob["relative_path"]).read_bytes() == b"media-content"
    storage.trash("candidate:1")
    assert storage.usage()["used_bytes"] == len(b"media-content")
    assert storage.entries(trash=True)["total"] == 1


def test_existing_paid_output_is_preserved_and_new_upload_rejected(tmp_path):
    storage = catalog(tmp_path)
    storage.set_limit(10, "admin")
    storage.reserve("generation:one", 10, "generation")
    result = tmp_path / "large.png"
    result.write_bytes(b"a" * 20)
    storage.keep_file(result, reservation_id="generation:one", preserve=True)
    assert storage.usage()["over_limit"]
    assert storage.usage()["reserved_bytes"] == 0
    with pytest.raises(AccountError):
        storage.reserve("next", 1)


def test_checksum_and_path_validation(tmp_path):
    storage = catalog(tmp_path / "account")
    source = storage.root / "picture.png"
    source.write_bytes(b"picture")
    with pytest.raises(AccountError, match="校验"):
        storage.keep_file(source, expected_sha256="0" * 64)
    with pytest.raises(AccountError, match="路径"):
        storage.resolve("../other-account/private.png")
    assert storage.usage()["used_bytes"] == 0


def test_thumbnail_is_unmetered_until_used_as_content(tmp_path):
    storage = catalog(tmp_path)
    source = tmp_path / "picture.png"
    source.write_bytes(b"picture")
    storage.keep_file(source, chargeable=False)
    assert storage.usage()["used_bytes"] == 0
    storage.keep_file(source)
    assert storage.usage()["used_bytes"] == 7


def test_new_confirmed_server_resets_receipts_but_same_server_resumes(tmp_path):
    storage = catalog(tmp_path)
    source = tmp_path / "original.png"
    source.write_bytes(b"file")
    blob = storage.keep_file(source)
    storage.put_entry("image:1", "image", blob["sha256"], {})
    entry = storage.entry("image:1")
    storage.select_sync_target("https://first.example:account1")
    storage.mark_synced(entry["key"], entry["updated_at"])
    storage.save_job("send:pending", "failed", {"entries": []})
    storage.select_sync_target("https://first.example:account1")
    assert storage.pending_entries() == []
    assert storage.jobs(internal=True)[0]["status"] == "failed"
    storage.select_sync_target("https://second.example:account2")
    assert len(storage.pending_entries()) == 1
    assert storage.jobs(internal=True) == []


def test_inventory_keeps_original_creation_time_and_does_not_auto_push_old_media(tmp_path):
    storage = catalog(tmp_path)
    file = tmp_path / "old.png"
    file.write_bytes(b"old")
    blob = storage.keep_file(file)
    storage.put_entry(
        "candidate:old", "image", blob["sha256"], {"created_at": "2024-01-01T00:00:00+00:00"}
    )
    assert storage.entry("candidate:old")["created_at"] == 1704067200
    assert storage.pending_entries(created_after=1704067201) == []
    assert len(storage.pending_entries()) == 1
