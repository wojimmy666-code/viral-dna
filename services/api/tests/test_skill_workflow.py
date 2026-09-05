from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from viral_dna_api.category_profiles import CategoryProfileSnapshot
from viral_dna_api.platform_skills import PlatformSkillCatalogService
from viral_dna_api.projects import ProjectCreate, ProjectService
from viral_dna_api.skill_workflow.contracts import (
    AssetUsageInput,
    BrandSnapshotCreate,
    CreativeBriefInput,
    ExecutionStatus,
    GateActorType,
    GateDecision,
    GateDecisionRequest,
    RunContractInput,
    SkillGate,
    SkillRunCreate,
)
from viral_dna_api.skill_workflow.service import (
    SkillWorkflowService,
    SkillWorkflowServiceError,
)
from viral_dna_api.store import InMemoryStore


class FakeAccountContext:
    def __init__(self) -> None:
        self.account = SimpleNamespace(id=uuid4())

    async def current_account(self):
        return self.account


class FakeCategoryProfiles:
    def __init__(self, profile: CategoryProfileSnapshot) -> None:
        self.profile = profile
        self.used_profile_id = None

    async def snapshot(self, profile_id):
        assert profile_id == self.profile.id
        return self.profile

    async def mark_used(self, profile_id):
        self.used_profile_id = profile_id


def test_category_profile_is_authoritative_for_brand_snapshot() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        account = FakeAccountContext()
        catalog = PlatformSkillCatalogService(None)
        projects = ProjectService(store, catalog, account)
        profile = CategoryProfileSnapshot(
            id=uuid4(),
            account_id=account.account.id,
            revision=4,
            fingerprint="a" * 64,
            display_name="Autumn commuter wear",
            category_name="Womenswear",
            brand_name="Northwind",
            brief="Restrained premium commuter wardrobe",
            audiences=["Urban professionals"],
            selling_points=["Wrinkle resistant", "Multiple styling options"],
            scenes=["Morning commute"],
            forbidden_claims=["Guaranteed slimming"],
            visual_style="Natural light and muted colors",
        )
        profiles = FakeCategoryProfiles(profile)
        service = SkillWorkflowService(
            store,
            projects,
            account,
            category_profiles=profiles,
        )
        skill = await catalog.get_catalog_item("cinematic-product-story")
        project = await projects.create(
            ProjectCreate(
                kind="skill",
                name="Profile-grounded film",
                skill_version_id=skill.current_version.id,
            )
        )

        brand = await service.create_brand_snapshot(
            project.id,
            BrandSnapshotCreate(
                source_category_profile_id=profile.id,
                name="Untrusted client name",
                description="Untrusted client description",
            ),
        )

        assert brand.name == "Northwind"
        assert brand.description.startswith(profile.brief)
        assert brand.values == profile.selling_points
        assert brand.visual_identity["profile_revision"] == 4
        assert brand.visual_identity["forbidden_claims"] == ["Guaranteed slimming"]
        assert profiles.used_profile_id == profile.id

    asyncio.run(scenario())


def test_preflight_enforces_skill_inputs_and_manual_gate() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        account = FakeAccountContext()
        catalog = PlatformSkillCatalogService(None)
        projects = ProjectService(store, catalog, account)
        service = SkillWorkflowService(store, projects, account)
        skill = await catalog.get_catalog_item("cinematic-product-story")
        project = await projects.create(
            ProjectCreate(
                kind="skill",
                name="Brand film",
                skill_version_id=skill.current_version.id,
            )
        )
        brand = await service.create_brand_snapshot(
            project.id,
            BrandSnapshotCreate(
                name="ViralDNA",
                description="Video creation platform",
                values=["Reliable production"],
                visual_identity={
                    "category_name": "Creator tools",
                    "visual_style": "Restrained editorial lighting",
                    "scenes": ["Creator desk"],
                },
            ),
        )
        await service.put_brief(
            project.id,
            CreativeBriefInput(
                brand_snapshot_id=brand.id,
                objective="Launch a new product",
                audience="Creators",
                distribution_channel="douyin",
                target_duration_seconds=15,
                output_aspect_ratio="9:16",
                creative_basis="hybrid",
                forbidden_messages=["Unsupported absolute claims"],
                skill_answers={"primary_message": "Make branded video production reliable"},
            ),
        )
        contract = await service.put_run_contract(
            project.id,
            RunContractInput(
                image_provider_connection_id="dashscope",
                image_model_id="qwen_image_2_pro",
                image_width=1024,
                image_height=1824,
                video_provider_connection_id="gemini_omni",
                video_model_id="gemini_omni_1_1_flash",
                video_width=1080,
                video_height=1920,
                video_resolution_label="1080P",
                video_fps=30,
                video_duration_capabilities_seconds=[5, 8],
                text_model_selection="workspace_default",
                generate_video_audio=True,
                audio_source_strategy="candidate",
                estimate_status="known",
                estimated_cost_micros=2_000_000,
                budget_limit_micros=5_000_000,
                supports_exact_overlay=True,
            ),
        )

        blocked = await service.preflight(project.id)
        assert not blocked.can_start
        assert "asset_role_required" in {item.code for item in blocked.issues}

        asset_ids = [uuid4() for _ in range(20)]
        usage_inputs = [
            AssetUsageInput(
                asset_id=asset_id,
                role="product_hero",
                fidelity="identity_lock",
                rights_status="confirmed",
                allowed_distribution=["douyin"],
                snapshot_sha256=f"{index:064x}",
            )
            for index, asset_id in enumerate(asset_ids, start=1)
        ]
        usage_inputs.append(
            AssetUsageInput(
                asset_id=uuid4(),
                role="reference_video",
                fidelity="style_only",
                rights_status="confirmed",
                allowed_distribution=["douyin"],
                snapshot_sha256="f" * 64,
            )
        )
        usages = await service.replace_asset_usages(
            project.id,
            usage_inputs,
        )
        current_brief = (await service.workspace(project.id)).brief
        brief_payload = current_brief.model_dump(
            mode="python",
            exclude={
                "id",
                "project_id",
                "revision_number",
                "target_duration_frames",
                "input_hash",
                "created_by",
                "created_at",
            },
        )
        brief_payload["selected_asset_usage_ids"] = [item.id for item in usages]
        current_brief = await service.put_brief(
            project.id,
            CreativeBriefInput.model_validate(brief_payload),
        )
        ready = await service.preflight(project.id)
        assert ready.can_start
        assert "image_reference_count_unsupported" not in {
            item.code for item in ready.issues
        }
        assert "asset_role_limit_exceeded" not in {item.code for item in ready.issues}
        assert "video_reference_unsupported" not in {item.code for item in ready.issues}
        assert "video_reference_pipeline_unavailable" not in {
            item.code for item in ready.issues
        }

        run = await service.start_run(
            project.id,
            SkillRunCreate(
                run_contract_revision_id=contract.id,
                idempotency_key="workflow-test-idempotency",
            ),
        )
        same = await service.start_run(
            project.id,
            SkillRunCreate(
                run_contract_revision_id=contract.id,
                idempotency_key="workflow-test-idempotency",
            ),
        )
        assert same.run.id == run.run.id

        with pytest.raises(SkillWorkflowServiceError) as gate_blocked:
            await service.compile_style(run.run.id)
        assert gate_blocked.value.code == "brief_gate_required"

        await service.decide_gate(
            run.run.id,
            SkillGate.BRIEF_APPROVED,
            GateDecisionRequest(
                decision="approve",
                related_revision_ids=[current_brief.id, contract.id],
            ),
        )
        detail = await service.compile_style(run.run.id)
        assert any(step.operation == "compile_style_bible" for step in detail.steps)
        await service.compile_style(run.run.id)
        assert len(await store.list_style_bible_revisions(project.id)) == 1
        workspace = await service.workspace(project.id)
        assert workspace.style_bible is not None
        assert "品牌视觉风格：Restrained editorial lighting" in workspace.style_bible.positive_lock
        assert "Unsupported absolute claims" in workspace.style_bible.negative_lock
        assert workspace.style_bible.texture["category_scenes"] == ["Creator desk"]
        assert workspace.style_bible.typography["render_mode"] == "deterministic_overlay"
        assert workspace.style_bible.typography["default_fonts"]["zh_display"]
        assert workspace.style_bible.sound["editing_music"]["bpm"] == 124
        assert workspace.style_bible.editing["allowed_transitions"] == ["hard_cut"]
        assert workspace.look_test is not None

        await store.save_gate_decision(
            GateDecision(
                project_id=project.id,
                skill_run_id=run.run.id,
                gate=SkillGate.STYLE_APPROVED,
                decision="approve",
                actor_type=GateActorType.USER,
                actor_id=account.account.id,
                related_revision_ids=[workspace.style_bible.id, workspace.look_test.id],
            )
        )
        compiling = await service.compile_storyboard(run.run.id)
        compile_step = next(
            item for item in compiling.steps if item.operation == "compile_storyboard"
        )
        assert compile_step.execution_status in {
            ExecutionStatus.RUNNING,
            ExecutionStatus.SUCCEEDED,
        }
        storyboard_task = service._storyboard_tasks.get(run.run.id)
        if storyboard_task is not None:
            await storyboard_task
        storyboard_workspace = await service.workspace(project.id)
        assert storyboard_workspace.shot_manifest is not None
        # 15 seconds at the reference pacing suggests 14 shots; the Skill's old
        # minimum of 15 must not force a filler shot or reject this result.
        assert len(storyboard_workspace.shot_manifest.shots) == 14
        assert all(
            item.prompt_quality.passed
            for item in storyboard_workspace.shot_manifest.shots
        )
        assert storyboard_workspace.shot_manifest.authoring_model
        completed_steps = await store.list_skill_step_runs(run.run.id)
        completed_compile = next(
            item for item in completed_steps if item.operation == "compile_storyboard"
        )
        assert completed_compile.execution_status == ExecutionStatus.SUCCEEDED
        assert completed_compile.progress == 100

        next_brief_payload = current_brief.model_dump(
            mode="python",
            exclude={
                "id",
                "project_id",
                "revision_number",
                "target_duration_frames",
                "input_hash",
                "created_by",
                "created_at",
            },
        )
        next_brief_payload["objective"] = "Launch the updated product story"
        await service.put_brief(
            project.id,
            CreativeBriefInput.model_validate(next_brief_payload),
        )
        decisions = await store.list_gate_decisions(run.run.id)
        latest_g0 = max(
            (item for item in decisions if item.gate == SkillGate.BRIEF_APPROVED),
            key=lambda item: item.created_at,
        )
        assert latest_g0.decision == "request_revision"
        assert latest_g0.actor_type == "system"
        with pytest.raises(SkillWorkflowServiceError) as stale_gate:
            await service.compile_style(run.run.id)
        assert stale_gate.value.code == "brief_gate_required"

    asyncio.run(scenario())
