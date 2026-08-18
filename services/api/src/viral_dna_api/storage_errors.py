from __future__ import annotations

from uuid import UUID


class IncompatibleShotPlanSchemaError(RuntimeError):
    """Raised when a project's stored shot workflow cannot use the current schema."""

    def __init__(self, project_id: UUID) -> None:
        self.project_id = project_id
        super().__init__(f"Shot workflow schema is incompatible for project {project_id}")
