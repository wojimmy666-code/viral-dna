from __future__ import annotations

import asyncio
from uuid import uuid4

from viral_dna_api.platform_skills.service import _seed_state
from viral_dna_api.skill_workflow.contracts import (
    BrandSnapshot,
    CreativeBriefRevision,
    RunContractRevision,
    StyleBibleRevision,
    content_digest,
)
from viral_dna_api.skill_workflow.storyboard_authoring import (
    ReferenceStyleStoryboardAuthor,
    StoryboardAuthoringContext,
    assess_prompts,
    compile_image_prompt,
    compile_video_prompt,
    creative_spec_from_authored,
)


def _digest(value: object) -> str:
    return content_digest(value)


def test_industrial_skill_v2_keeps_style_without_copying_reference_product() -> None:
    async def scenario() -> None:
        manifest = next(
            item.manifest
            for item in _seed_state().versions
            if item.skill_id == "platform.cinematic-product-story"
        )
        project_id = uuid4()
        brand = BrandSnapshot(
            project_id=project_id,
            name="Aster",
            description="专业咖啡设备",
            visual_identity={
                "category_name": "咖啡机",
                "scenes": ["金属加工车间", "装配检测台"],
            },
            content_hash=_digest("brand"),
        )
        brief = CreativeBriefRevision(
            project_id=project_id,
            brand_snapshot_id=brand.id,
            objective="用制造细节证明咖啡机的可靠品质",
            audience="重视品质的家庭用户",
            distribution_channel="douyin",
            target_duration_seconds=18,
            target_duration_frames=432,
            output_aspect_ratio="16:9",
            fps=24,
            creative_basis="brand_led",
            revision_number=1,
            input_hash=_digest("brief"),
        )
        contract = RunContractRevision(
            project_id=project_id,
            image_provider_connection_id="dashscope",
            image_model_id="qwen_image_2_pro",
            image_width=1024,
            image_height=576,
            video_provider_connection_id="seedance",
            video_model_id="seedance-1.5-pro",
            video_width=1920,
            video_height=1080,
            video_resolution_label="1080P",
            video_fps=24,
            video_duration_capabilities_seconds=[4, 5],
            text_model_selection="workspace_default",
            revision_number=1,
            input_hash=_digest("contract"),
        )
        bible = StyleBibleRevision(
            project_id=project_id,
            revision_number=1,
            skill_version_digest=_digest("skill"),
            brand_snapshot_digest=brand.content_hash,
            brief_revision_id=brief.id,
            positive_lock=manifest.spec.style.positive_lock,
            negative_lock=manifest.spec.style.negative_lock,
            input_hash=_digest("style-input"),
            content_hash=_digest("style"),
        )
        context = StoryboardAuthoringContext(
            manifest=manifest,
            brand=brand,
            brief=brief,
            style_bible=bible,
            run_contract=contract,
            asset_facts=[{"id": "asset_product", "role": "product_hero"}],
            approved_claims=[],
        )
        result = await ReferenceStyleStoryboardAuthor().author(context)
        assert 15 <= len(result.storyboard.shots) <= 18
        assert result.storyboard.edit_plan["transition"] == "hard_cut"
        assert result.storyboard.edit_plan["detail_ratio"] == 0.7
        assert "3200" in result.storyboard.continuity_bible["lighting"]
        assert all("HDASHER" not in item.subject for item in result.storyboard.shots)
        assert all("空调滤芯" not in item.subject for item in result.storyboard.shots)

        representative = result.storyboard.shots[0]
        spec = creative_spec_from_authored(representative)
        image_prompt = compile_image_prompt(
            spec,
            brand_name=brand.name,
            exact_asset_reserved=False,
        )
        video_prompt = compile_video_prompt(
            spec,
            order=1,
            generation_duration_seconds=4,
            aspect_ratio="16:9",
            fps=24,
        )
        quality = assess_prompts(
            image_prompt,
            video_prompt,
            minimum_score=85,
            forbidden_copy_terms=["HDASHER", "空调滤芯", "滤材", "褶皱"],
            allowed_context=f"{brand.name} {brand.description} 咖啡机",
            required_image_sections=manifest.spec.quality.required_image_sections,
            required_video_sections=manifest.spec.quality.required_video_sections,
            image_character_range=(
                manifest.spec.prompt_rules.image_target_characters.min,
                manifest.spec.prompt_rules.image_target_characters.max,
            ),
            video_character_range=(
                manifest.spec.prompt_rules.video_target_characters.min,
                manifest.spec.prompt_rules.video_target_characters.max,
            ),
        )
        assert quality.passed
        assert quality.score >= 90
        assert len(video_prompt) >= 450
        assert "【同步音效】" in video_prompt
        assert "唯一首帧" in video_prompt

    asyncio.run(scenario())
