from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..production import ProductionServiceError
from ..production_prompt_documents import PromptDocumentUpdate
from ..project_prompts import PromptRevisionConflict
from .prompt_language_service import (
    PromptLanguageService,
    PromptTranslationRequest,
    concept_document,
)
from .service import ViralInsightServiceError


def create_prompt_document_router(creative, production):
    router = APIRouter(tags=["prompt-documents"])
    language = PromptLanguageService(creative, production)

    async def call(awaitable):
        try:
            return await awaitable
        except (ViralInsightServiceError, ProductionServiceError) as exc:
            raise HTTPException(
                exc.status_code, detail={"code": exc.code, "message": str(exc)}
            ) from exc
        except PromptRevisionConflict as exc:
            raise HTTPException(
                409, detail={"code": "prompt_document_changed", "message": str(exc)}
            ) from exc

    @router.get("/analyses/{analysis_id}/prompt-sources")
    async def sources(analysis_id: UUID):
        report = await call(creative.insights._source_report(analysis_id))
        video = await creative.repository.get_video(report.video_id)
        projects = (
            await production.list_projects(video.record_id) if video and video.record_id else []
        )
        history = await call(creative.history(analysis_id))
        by_project = {
            str(item.published_result.project_id): item for item in history if item.published_result
        }
        results = [
            {
                "key": f"production:{item.id}",
                "kind": "production",
                "id": str(item.id),
                "name": item.name,
                "batch_id": str(by_project[str(item.id)].id)
                if str(item.id) in by_project
                else None,
            }
            for item in projects
        ]
        for item in history:
            if item.operation == "localize" and item.status in {
                "queued",
                "running",
                "failed",
                "cancelled",
            }:
                results.append(
                    {
                        "key": f"concept:{item.id}",
                        "kind": "concept",
                        "id": str(item.id),
                        "batch_id": str(item.id),
                        "name": item.input_snapshot.get("prompt_language_source", {}).get(
                            "name", "中文校正"
                        ),
                        "operation": "localize",
                        "status": item.status,
                    }
                )
                continue
            if item.phase != "expanded" or not item.concepts or item.published_result:
                continue
            if item.status != "completed" and item.error_code != "creative_prompt_language_invalid":
                continue
            if item.language_applied_revision_id:
                continue
            results.append(
                {
                    "key": f"concept:{item.id}",
                    "kind": "concept",
                    "id": str(item.id),
                    "batch_id": str(item.id),
                    "name": item.concepts[0].name,
                    "operation": item.operation,
                    "status": item.status,
                    "created_at": item.created_at,
                    "project_id": item.input_snapshot.get("prompt_language_project_id"),
                }
            )
        return results

    @router.get("/productions/{project_id}/prompt-document")
    async def production_document(project_id: UUID):
        return await call(language.documents.get(project_id))

    @router.put("/productions/{project_id}/prompt-document")
    async def update_document(project_id: UUID, payload: PromptDocumentUpdate):
        return await call(language.documents.save(project_id, payload))

    @router.get("/viral-concept-sets/{concept_set_id}/prompt-document")
    async def preview(concept_set_id: UUID):
        parent, _ = await call(language.source(concept_set_id))
        document = parent.language_result or concept_document(parent)
        return {
            **document,
            "batch_id": str(parent.id),
            "read_only": True,
            "operation": parent.operation,
            "applied_revision_id": parent.language_applied_revision_id,
            "source_document": parent.input_snapshot.get("prompt_language_source")
            if parent.operation == "localize"
            else None,
        }

    @router.get("/viral-concept-sets/{concept_set_id}/localization-estimate")
    async def estimate(concept_set_id: UUID, project_id: UUID | None = None):
        return await call(language.estimate(concept_set_id, project_id))

    @router.post("/viral-concept-sets/{concept_set_id}/localize", status_code=202)
    async def localize(concept_set_id: UUID, payload: PromptTranslationRequest):
        return await call(language.start(concept_set_id, payload))

    @router.post("/viral-concept-sets/{concept_set_id}/apply-language")
    async def apply(concept_set_id: UUID):
        return await call(language.apply(concept_set_id))

    return router
