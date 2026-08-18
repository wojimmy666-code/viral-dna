from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .domain import AssetProvenance, GeneratedArtifact, StorageObjectReference


class GeneratedArtifactRepository(Protocol):
    async def save_generated_artifact(
        self, artifact: GeneratedArtifact
    ) -> GeneratedArtifact: ...

    async def get_generated_artifact(
        self, artifact_id: UUID
    ) -> GeneratedArtifact | None: ...

    async def list_generated_artifacts(self) -> list[GeneratedArtifact]: ...

    async def save_storage_object_reference(
        self, reference: StorageObjectReference
    ) -> StorageObjectReference: ...

    async def list_storage_object_references(
        self, object_id: UUID | None = None
    ) -> list[StorageObjectReference]: ...

    async def save_asset_provenance(
        self, provenance: AssetProvenance
    ) -> AssetProvenance: ...

    async def get_asset_provenance(self, asset_id: UUID) -> AssetProvenance | None: ...
