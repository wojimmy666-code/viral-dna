import asyncio
import copy
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from test_creative_concepts import finish, setup

from viral_dna_api.models import AnalysisRecord, ShotVideoGenerationDraft, Video, WorkflowItemStatus
from viral_dna_api.production import ProductionService, ProductionServiceError
from viral_dna_api.production_prompt_documents import (
    ProductionPromptDocuments,
    PromptDocumentUpdate,
    document_bodies,
)
from viral_dna_api.project_prompts import PromptRevisionConflict
from viral_dna_api.sqlite_store import SQLiteStore
from viral_dna_api.viral_insights.contracts import (
    CreativeActionRequest,
    CreativeGenerateRequest,
    ViralConceptPublishRequest,
)
from viral_dna_api.viral_insights.creative_language import (
    CreativePromptLanguageError,
    is_foreign_prose,
    require_chinese_prompts,
)
from viral_dna_api.viral_insights.prompt_document_routes import create_prompt_document_router
from viral_dna_api.viral_insights.prompt_language_service import (
    PromptLanguageService,
    PromptTranslationRequest,
    PromptTranslationResponse,
    validate_translation,
)
from viral_dna_api.viral_insights.publisher import ProductionConceptPublisher
from viral_dna_api.viral_insights.service import ViralInsightServiceError
from viral_dna_api.workspace import WorkspaceManager


@pytest.mark.parametrize("sqlite", [False, True])
@pytest.mark.parametrize("race", ["draft", "global"])
def test_commit_fence_rejects_concurrent_draft_or_globals(tmp_path, monkeypatch, sqlite, race):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))

    async def scenario():
        repo, _, _, production, _, result = await fixture(tmp_path, sqlite)
        documents = ProductionPromptDocuments(production)
        before = await documents.get(result.project_id)
        plans = await repo.list_shot_plans(result.project_id)
        old_project = (await repo.get_production_project(result.project_id)).model_copy(deep=True)
        body = document_bodies(before)
        body["shots"][0]["video_prompt"] = "不能部分写入的新提示词"
        original_save = repo.save_production_bundle

        async def race_at_commit(*args, **kwargs):
            if race == "draft":
                draft = ShotVideoGenerationDraft(
                    project_id=result.project_id,
                    shot_plan_id=plans[0].id,
                    model_alias="seedance",
                    resolution="720P",
                    duration_seconds=5,
                    video_prompt="另一页面的新草稿",
                )
                assert await repo.compare_and_swap_video_generation_draft(draft, 0)
            else:
                context = await production.get_prompt_context(result.project_id)
                newer = context.model_copy(
                    update={
                        "id": uuid4(),
                        "revision_number": context.revision_number + 1,
                        "common_video_prompt": "另一页面的全局",
                    }
                )
                assert await repo.save_project_prompt_revision(newer, context.id)
            return await original_save(*args, **kwargs)

        repo.save_production_bundle = race_at_commit
        with pytest.raises(PromptRevisionConflict):
            await documents.save(
                result.project_id, PromptDocumentUpdate(expected_token=before["token"], **body)
            )
        assert (
            await repo.get_production_project(result.project_id)
        ).current_revision_id == old_project.current_revision_id
        assert [p.model_dump() for p in await repo.list_shot_plans(result.project_id)] == [
            p.model_dump() for p in plans
        ]
        assert all(
            p.video_prompt != "不能部分写入的新提示词"
            for p in await repo.list_shot_plans(result.project_id)
        )

    asyncio.run(scenario())


def test_document_routes_are_read_only_and_sources_keep_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))

    async def scenario():
        repo, report, creative, production, batch, result = await fixture(tmp_path)
        app = FastAPI()
        app.include_router(create_prompt_document_router(creative, production))
        before = len(await repo.list_model_runs(report.analysis_id))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(f"/analyses/{report.analysis_id}/prompt-sources")
            assert listing.status_code == 200
            assert listing.json()[0]["key"] == f"production:{result.project_id}"
            assert listing.json()[0]["batch_id"] == str(batch.id)
            response = await client.get(f"/productions/{result.project_id}/prompt-document")
            assert response.status_code == 200 and len(response.json()["shots"]) == 5
            preview = await client.get(f"/viral-concept-sets/{batch.id}/prompt-document")
            assert preview.json()["read_only"] is True
            missing = await client.get(f"/productions/{uuid4()}/prompt-document")
            assert missing.status_code == 404
        assert len(await repo.list_model_runs(report.analysis_id)) == before

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text,invalid",
    [
        ("Wide shot, Iceland Vik Black Sand Beach, overcast sky and diffused light.", True),
        ("画面：A young woman walks across the black sand beach.", True),
        ("远景，冰岛黑沙滩，JK 格纹裙，4K、HDR、35mm 镜头。", False),
        ("镜头推进，英文标识：“Travel across the world with me”。", False),
        ("穿 Nike 外套，站在巴黎街头。", False),
    ],
)
def test_prompt_language_guard(text, invalid):
    assert is_foreign_prose(text) is invalid


async def fixture(tmp_path, sqlite=False):
    repo, report, categories, provider, creative = await setup(
        SQLiteStore(tmp_path / "test.sqlite") if sqlite else None
    )
    first = await finish(
        creative,
        await creative.generate(
            report.analysis_id,
            CreativeGenerateRequest(request_id=uuid4(), category_profile_id=categories.profile.id),
        ),
    )
    batch = await finish(
        creative,
        await creative.act(
            first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=True
        ),
    )
    record = uuid4()
    await repo.save_video(
        Video(
            id=report.video_id,
            record_id=record,
            source_type="upload",
            filename="test.mp4",
            title="source",
            width=1080,
            height=1920,
            duration_seconds=8.5,
            status="ready",
        )
    )
    await repo.save_record(
        AnalysisRecord(
            id=record,
            video_id=report.video_id,
            name="source",
            source_type="upload",
            latest_analysis_id=report.analysis_id,
        )
    )
    production = ProductionService(repo, WorkspaceManager())
    result = await ProductionConceptPublisher(production).publish(
        analysis_id=report.analysis_id,
        concept=batch.concepts[0],
        payload=ViralConceptPublishRequest(record_id=record),
    )
    batch.published_result = result
    await repo.save_viral_concept_set(batch)
    return repo, report, creative, production, batch, result


@pytest.mark.parametrize("sqlite", [False, True])
def test_live_prompts_save_and_conflict_preserve_original_media(tmp_path, monkeypatch, sqlite):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))

    async def scenario():
        repo, report, _, production, _, result = await fixture(tmp_path, sqlite)
        documents = ProductionPromptDocuments(production)
        plans = await repo.list_shot_plans(result.project_id)
        first = plans[0]
        adopted = uuid4()
        first.approved_video_candidate_id = adopted
        first.video_status = WorkflowItemStatus.APPROVED
        await repo.save_shot_plan(first)
        draft = ShotVideoGenerationDraft(
            project_id=result.project_id,
            shot_plan_id=first.id,
            model_alias="seedance",
            resolution="720P",
            duration_seconds=5,
            video_prompt="这是视频阶段最新的人工提示词",
            candidate_count=2,
        )
        assert await repo.compare_and_swap_video_generation_draft(draft, 0)
        doc = await documents.get(result.project_id)
        assert len(doc["shots"]) == 5 != len(report.prompt_package.shots)
        assert doc["shots"][0]["video_prompt"] == draft.video_prompt
        body = document_bodies(doc)
        body["shots"][0]["video_prompt"] = "镜头缓缓推进，人物回头。"
        saved = await documents.save(
            result.project_id, PromptDocumentUpdate(expected_token=doc["token"], **body)
        )
        after = await repo.get_video_generation_draft(first.id)
        assert after.video_prompt == body["shots"][0]["video_prompt"]
        assert after.draft_version == draft.draft_version + 1
        assert after.input_plan == draft.input_plan and after.candidate_count == 2
        current = await repo.get_shot_plan(first.id)
        assert current.approved_video_candidate_id == adopted
        assert current.video_status == WorkflowItemStatus.APPROVED
        assert [
            (p.id, p.start_seconds, p.end_seconds)
            for p in await repo.list_shot_plans(result.project_id)
        ] == [(p.id, p.start_seconds, p.end_seconds) for p in plans]
        assert (await repo.get_report_by_analysis(report.analysis_id)) == report
        with pytest.raises(ProductionServiceError, match="已更新"):
            await documents.save(
                result.project_id, PromptDocumentUpdate(expected_token=doc["token"], **body)
            )
        assert (await documents.get(result.project_id))["token"] == saved["token"]
        changed = document_bodies(saved)
        changed["shots"].reverse()
        with pytest.raises(ProductionServiceError, match="重排"):
            await documents.save(
                result.project_id, PromptDocumentUpdate(expected_token=saved["token"], **changed)
            )

    asyncio.run(scenario())


def test_translation_requires_confirmation_previews_then_applies_once(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRAL_DNA_WORKSPACE_ROOT", str(tmp_path))

    async def scenario():
        repo, report, creative, production, batch, result = await fixture(tmp_path, True)
        language = PromptLanguageService(creative, production)
        doc = await language.documents.get(result.project_id)
        bodies = document_bodies(doc)
        bodies["shots"][0]["images"][0]["prompt"] = (
            "Wide shot of a young woman on the black sand beach."
        )
        source = await language.documents.save(
            result.project_id, PromptDocumentUpdate(expected_token=doc["token"], **bodies)
        )
        estimate = await language.estimate(batch.id, result.project_id)
        calls = []

        async def model(job, targets, prompt, **kwargs):
            calls.append(prompt)
            response = document_bodies(source)
            response["shots"][0]["images"][0]["prompt"] = "远景，一位年轻女性站在黑沙滩上。"
            return PromptTranslationResponse(**response)

        creative._generate = model
        request = PromptTranslationRequest(
            request_id=uuid4(),
            project_id=result.project_id,
            expected_estimate=estimate["estimate_token"],
        )
        with pytest.raises(ViralInsightServiceError, match="计费"):
            await language.start(batch.id, request)
        assert not calls
        request.confirm_cost = True
        job = await language.start(batch.id, request)
        completed = await finish(creative, job)
        assert completed.status == "completed", completed.error_message
        assert (await language.documents.get(result.project_id))["token"] == source["token"]
        assert (await language.start(batch.id, request)).id == job.id
        assert len(calls) == 1
        applied = await language.apply(job.id)
        assert applied["shots"][0]["images"][0]["prompt"].startswith("远景")
        assert not applied["language_issues"]
        assert (await language.apply(job.id))["token"] == applied["token"]
        assert len(calls) == 1
        assert (await repo.get_report_by_analysis(report.analysis_id)) == report

    asyncio.run(scenario())


def test_translation_rejects_structure_numbers_and_manual_rewrite():
    shot = {
        "id": str(uuid4()),
        "index": 1,
        "title": "冰岛",
        "duration_seconds": 2,
        "images": [
            {
                "id": str(uuid4()),
                "prompt": "A wide shot with a 35mm lens.",
                "negative_constraints": [],
            }
        ],
        "video_prompt": "镜头推进",
        "video_negative_constraints": [],
    }
    source = {"common_image_prompt": "", "common_video_prompt": "", "shots": [shot]}
    payload = document_bodies(source)
    payload["shots"][0]["images"][0]["prompt"] = "35mm 镜头，远景。"
    assert (
        validate_translation(source, PromptTranslationResponse(**payload))["shots"][0]["title"]
        == "冰岛"
    )
    for change in ("number", "manual", "id", "english"):
        invalid = copy.deepcopy(payload)
        if change == "number":
            invalid["shots"][0]["images"][0]["prompt"] = "50mm 镜头，远景。"
        if change == "manual":
            invalid["shots"][0]["video_prompt"] = "镜头拉远"
        if change == "id":
            invalid["shots"][0]["id"] = str(uuid4())
        if change == "english":
            invalid["shots"][0]["images"][0]["prompt"] = shot["images"][0]["prompt"]
        with pytest.raises(ValueError):
            validate_translation(source, PromptTranslationResponse(**invalid))


def test_generated_english_is_recoverable_not_silently_published(tmp_path):
    async def scenario():
        repo, report, categories, provider, creative = await setup()
        generate = provider.generate

        async def english(request, schema):
            result = await generate(request, schema)
            if hasattr(result.data, "concept"):
                result.data.concept.shots[
                    0
                ].image_prompt = "A wide shot of the Iceland black sand beach."
            return result

        provider.generate = english
        first = await finish(
            creative,
            await creative.generate(
                report.analysis_id,
                CreativeGenerateRequest(
                    request_id=uuid4(), category_profile_id=categories.profile.id
                ),
            ),
        )
        batch = await finish(
            creative,
            await creative.act(
                first.id, first.ideas[0].id, CreativeActionRequest(request_id=uuid4()), expand=True
            ),
        )
        assert batch.error_code == "creative_prompt_language_invalid"
        assert batch.status == "failed" and batch.concepts and batch.language_issues
        assert len(provider.requests) == 2
        with pytest.raises(CreativePromptLanguageError):
            require_chinese_prompts(batch.concepts[0])

    asyncio.run(scenario())
