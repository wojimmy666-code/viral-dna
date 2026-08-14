from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from .models import (
    GenerationCandidate,
    GenerationCandidateArchiveReason,
    GenerationCandidateStatus,
)


def is_user_deleted_candidate(candidate: GenerationCandidate) -> bool:
    return candidate.status == GenerationCandidateStatus.ARCHIVED and (
        candidate.archive_reason == GenerationCandidateArchiveReason.USER_DELETED
        or candidate.quality_report.get("archive_reason")
        == GenerationCandidateArchiveReason.USER_DELETED.value
    )


def archive_candidate_records(
    candidates: Iterable[GenerationCandidate],
    *,
    actor_account_id: UUID | None,
    archived_at: datetime,
) -> list[GenerationCandidate]:
    output: list[GenerationCandidate] = []
    for candidate in candidates:
        quality_report = dict(candidate.quality_report)
        quality_report["archive_reason"] = (
            GenerationCandidateArchiveReason.USER_DELETED.value
        )
        output.append(
            candidate.model_copy(
                update={
                    "status": GenerationCandidateStatus.ARCHIVED,
                    "archived_at": archived_at,
                    "archived_by_account_id": actor_account_id,
                    "archive_reason": GenerationCandidateArchiveReason.USER_DELETED,
                    "quality_report": quality_report,
                }
            )
        )
    return output


def restore_candidate_records(
    candidates: Iterable[GenerationCandidate],
) -> list[GenerationCandidate]:
    output: list[GenerationCandidate] = []
    for candidate in candidates:
        quality_report = dict(candidate.quality_report)
        quality_report.pop("archive_reason", None)
        output.append(
            candidate.model_copy(
                update={
                    "status": GenerationCandidateStatus.READY,
                    "archived_at": None,
                    "archived_by_account_id": None,
                    "archive_reason": None,
                    "quality_report": quality_report,
                }
            )
        )
    return output
