from viral_dna_api.editing_guidance import separate_shot_editing_guidance, split_editing_guidance
from viral_dna_api.production_seeds import ProductionSeedShot
from viral_dna_api.skill_workflow.contracts import ShotManifestShot


def test_extracts_only_editing_section_and_preserves_motion_and_manual_prompt():
    prompt = "【本镜头】摄影机缓慢推近，结束时产品停稳。\n\n【剪辑落点】在重音处硬切。\n保持方向一致。\n\n【严格约束】不改变包装。\n我的手写说明。"
    body, note = split_editing_guidance(prompt)
    assert note == "在重音处硬切。\n保持方向一致。"
    assert "【剪辑落点】" not in body
    assert "产品停稳" in body and "我的手写说明。" in body


def test_existing_shot_body_and_seed_keep_editing_notes_separate():
    shot = ShotManifestShot(
        stable_shot_key="shot_aaaaaaaa",
        order=1,
        narrative_role="产品",
        start_frame=0,
        duration_frames=90,
        description="产品特写",
        video_prompt="【本镜头】缓慢推进。\n【剪辑落点】动作停稳后切换。\n【严格约束】不新增文字。",
        video_prompt_body="【本镜头】缓慢推进。\n【剪辑落点】动作停稳后切换。",
        input_hash="sha256:" + "a" * 64,
    )
    assert shot.editing_guidance == "动作停稳后切换。"
    assert "剪辑落点" not in shot.video_prompt
    assert "剪辑落点" not in shot.video_prompt_body
    seed = ProductionSeedShot.model_validate(shot.model_dump())
    assert seed.editing_guidance == shot.editing_guidance
    assert seed.video_prompt == shot.video_prompt


def test_new_notes_do_not_overwrite_existing_editing_guidance():
    result = separate_shot_editing_guidance(
        {
            "editing_guidance": "保留人工节奏说明",
            "video_prompt": "【本镜头】产品静止。\n【剪辑落点】切至设备。",
        }
    )
    assert result["editing_guidance"] == "保留人工节奏说明\n\n切至设备。"
    assert separate_shot_editing_guidance(result) == result
