from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import ValidationError

from .contracts import (
    PlatformSkill,
    PlatformSkillVersion,
    SkillCatalogItem,
    SkillCatalogListResponse,
    SkillCatalogState,
    SkillLifecycle,
    SkillManifest,
    SkillValidationResult,
    SkillVersionCreate,
    utc_now,
)

MAX_SKILL_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_SKILL_PACKAGE_ENTRIES = 100
MAX_SKILL_RESOURCE_BYTES = 25 * 1024 * 1024
BLOCKED_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".js",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
}


class PlatformSkillError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def manifest_digest(manifest: SkillManifest) -> str:
    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _industrial_craft_profile() -> dict[str, object]:
    """Portable style grammar distilled from the HDASHER factory-film reference."""

    archetypes = [
        (
            "material_macro",
            "材料纹理钩子",
            "用极近材料细节建立品质感",
            "detail",
            [100],
            ["超近微距"],
            ["极慢横向滑轨", "克制拉焦"],
            ["材料缓慢经过画面", "焦点落稳"],
            ["近场材料摩擦", "低电平环境底噪"],
            ["材质不得融化、呼吸或改变结构"],
        ),
        (
            "environment_axis",
            "生产环境建立",
            "建立真实、有秩序的制造空间",
            "environment",
            [35],
            ["中轴广角全景"],
            ["笔直慢速前推"],
            ["设备低速运转", "远处人员完成小幅检查"],
            ["连续电机底噪", "空气系统风声"],
            ["不得变成科幻工厂或无人机穿越"],
        ),
        (
            "incoming_inspection",
            "来料检测",
            "以专业检测动作建立原料可信度",
            "detail",
            [85, 100],
            ["工具与材料近景"],
            ["固定机位", "5%以内慢推"],
            ["工具接近", "完成一次检测", "停顿读取", "轻微回位"],
            ["克制机械咔哒", "材料摩擦"],
            ["工具、读数和手指不得畸变"],
        ),
        (
            "material_feed",
            "原料进入工序",
            "展示材料进入真实设备的路径",
            "detail",
            [50, 65],
            ["设备侧前方中近景"],
            ["固定机位", "极慢前移"],
            ["材料恒速进入", "辊轴按真实传动运转"],
            ["低沉辊轴声", "材料连续摩擦"],
            ["材料不得反向、穿模或厚度跳变"],
        ),
        (
            "material_light_check",
            "材料状态检查",
            "用光线呈现材料层次和完整性",
            "detail",
            [85],
            ["逆光近景"],
            ["固定机位", "几厘米慢推"],
            ["主体轻微倾斜", "停住检查"],
            ["细小材料沙沙声", "远处环境底噪"],
            ["材料层数、比例和手部必须稳定"],
        ),
        (
            "forming_process",
            "核心成型工艺",
            "呈现产品结构被连续形成的过程",
            "detail",
            [65],
            ["低机位中近景"],
            ["固定机位", "5%以内慢推"],
            ["材料恒速进入", "机构完成规律短行程"],
            ["规律机械节拍", "低沉设备声"],
            ["结构不得凭空出现或数量闪变"],
        ),
        (
            "precision_action",
            "精密单次动作",
            "以一次精确动作形成剪辑击点",
            "detail",
            [100],
            ["工具接触点微距"],
            ["绝对稳定"],
            ["工具只完成一次短行程", "立即回位"],
            ["一次克制金属触点", "设备余韵"],
            ["不得出现火花、爆裂、烟雾或工具变形"],
        ),
        (
            "joining_process",
            "连接与固定",
            "表现连接、粘合或锁定工艺",
            "detail",
            [100],
            ["连接位置微距"],
            ["沿工艺方向极慢横移"],
            ["连接动作连续均匀", "主体保持稳定"],
            ["轻微气动声", "连续泵或设备底噪"],
            ["介质不得拉丝、滴落、发光或失控"],
        ),
        (
            "pressing_process",
            "压制与定型",
            "表现设备重量与尺寸精度",
            "detail",
            [65],
            ["正面略低机位"],
            ["锁定机位"],
            ["设备完成一次短行程", "保持后轻微回升"],
            ["低沉下压声", "克制到位闷响"],
            ["不得突然砸落、压毁产品或出现危险手部"],
        ),
        (
            "human_assembly",
            "人工装配",
            "用熟练人工动作补充工艺温度",
            "detail",
            [50],
            ["工作台中近景"],
            ["沿工作台慢速横移"],
            ["前景人员完成一次装配", "后方动作保持自然时间差"],
            ["手套与产品摩擦", "轻微落台声"],
            ["人物、手部、服装和工位不得漂移"],
        ),
        (
            "production_scale",
            "产线规模",
            "以空间镜头补充制造规模",
            "environment",
            [35],
            ["中轴纵深全景"],
            ["严格水平慢速前推"],
            ["近处设备规律运转", "远处人员低幅工作"],
            ["宽阔环境声床", "远近电机层次"],
            ["必须延续同一空间，不得变成仓库或总装厂"],
        ),
        (
            "performance_test",
            "性能检测",
            "以可验证测试过程证明性能",
            "detail",
            [65, 85],
            ["测试设备近景"],
            ["固定机位", "轻微推近"],
            ["完成一次真实测试循环", "结果稳定后结束"],
            ["锁扣或开关触点", "受控设备运行声"],
            ["不得编造读数、认证或不存在的测试设备"],
        ),
        (
            "dimension_check",
            "尺寸精度检测",
            "用尺寸接触点表现一致性",
            "detail",
            [100],
            ["测头与边缘微距"],
            ["固定机位"],
            ["测头轻触一次", "短暂停留后离开"],
            ["细小测量触点", "材料摩擦"],
            ["刻度、工具结构和产品尺寸不得变化"],
        ),
        (
            "finish_check",
            "成品细节检查",
            "用克制手部动作证明装配完整",
            "detail",
            [100],
            ["接缝或边缘微距"],
            ["固定机位"],
            ["手指沿接缝移动", "角部轻压并自然回弹"],
            ["细腻表面摩擦", "极轻回弹声"],
            ["只出现结构正确的手，产品不得液化或开裂"],
        ),
        (
            "product_hero",
            "成品英雄镜头",
            "把完成态产品提升为视觉主角",
            "product",
            [85],
            ["产品近景"],
            ["10度以内克制弧移", "轻微推近", "平滑拉焦"],
            ["产品完全静止", "轮廓光缓慢掠过"],
            ["极低空间气流", "克制低频落点"],
            ["产品不得旋转、悬浮、呼吸或改变几何"],
        ),
        (
            "packaging_tableau",
            "产品与包装定妆",
            "确认产品、包装和品牌资产",
            "brand",
            [65],
            ["产品包装组合近景"],
            ["8%以内笔直慢推"],
            ["产品靠近包装后停住", "品牌信息保持可读"],
            ["柔和落台声", "短尾品牌低频落点"],
            ["包装和Logo必须作为确定性平面素材，不得重绘"],
        ),
        (
            "brand_endcard",
            "品牌片尾",
            "以极简图形收束品牌记忆",
            "brand",
            [50],
            ["纯色背景居中图形"],
            ["相机绝对静止"],
            ["图形淡入并保持静止", "最后淡出"],
            ["短促低频品牌落点", "极轻空气声"],
            ["Logo字形、比例、颜色和拼写绝对锁定"],
        ),
    ]
    return {
        "api_version": "viraldna.video-skill/v2",
        "narrative": {
            "outline_pattern": [
                {
                    "key": "material_hook",
                    "target_duration_ratio": 0.12,
                    "purpose": "以材料或结构微距在首屏建立品质悬念",
                },
                {
                    "key": "process_reveal",
                    "target_duration_ratio": 0.18,
                    "purpose": "建立真实生产空间并揭示产品形成路径",
                },
                {
                    "key": "craft_proof",
                    "target_duration_ratio": 0.42,
                    "purpose": "用工艺、装配与专业动作连续证明品质",
                },
                {
                    "key": "test_proof",
                    "target_duration_ratio": 0.14,
                    "purpose": "用已批准的检测事实完成可信证明",
                },
                {
                    "key": "brand_resolution",
                    "target_duration_ratio": 0.14,
                    "purpose": "以产品定妆、包装和品牌资产收束",
                },
            ],
            "shot_count": {"min": 15, "max": 18},
            "shot_density": {
                "style": "high_density_montage",
                "average_edit_duration_seconds": {"min": 0.7, "max": 1.55},
                "detail_ratio": 0.7,
                "environment_ratio": 0.3,
            },
            "shot_archetypes": [
                {
                    "key": key,
                    "title": title,
                    "purpose": purpose,
                    "coverage": coverage,
                    "preferred_lenses_mm": lenses,
                    "preferred_framing": framing,
                    "preferred_motion": motion,
                    "generation_duration_seconds": 2
                    if key == "brand_endcard"
                    else (5 if key == "packaging_tableau" else 4),
                    "edit_duration_seconds": {"min": 0.7, "max": 1.55},
                    "action_pattern": action,
                    "sound_pattern": sound,
                    "failure_constraints": failures,
                    "fallback_key": "product_hero"
                    if key in {"performance_test", "dimension_check"}
                    else None,
                }
                for (
                    key,
                    title,
                    purpose,
                    coverage,
                    lenses,
                    framing,
                    motion,
                    action,
                    sound,
                    failures,
                ) in archetypes
            ],
        },
        "style": {
            "visual_keywords": [
                "高端写实工业品牌广告",
                "真实工业纪录质感",
                "低饱和",
                "克制电影摄影",
                "材料细节",
            ],
            "palette_policy": {
                "base": ["炭黑", "暖琥珀", "灰橄榄", "奶油白"],
                "saturation": "low",
                "brand_accent": "project_asset",
            },
            "composition": {
                "detail_ratio": 0.7,
                "environment_ratio": 0.3,
                "principles": ["单镜头单一主体", "以真实空间和工艺关系组织画面"],
            },
            "lighting": {
                "temperature_kelvin": [3200, 3600],
                "direction": "warm_side_backlight",
                "contrast": "8:1",
                "haze": "extremely_light",
                "highlight": "soft_not_clipped",
            },
            "camera": {
                "camera_character": "ARRI Alexa 35 / Cooke S4",
                "fps": 24,
                "shutter_angle": 180,
                "allowed_motion": [
                    "locked",
                    "slow_linear_push",
                    "slow_lateral_slider",
                    "restrained_arc",
                    "controlled_focus_pull",
                ],
                "avoid_motion": [
                    "handheld_shake",
                    "fpv",
                    "drone",
                    "fast_zoom",
                    "whip_pan",
                    "speed_ramp",
                ],
            },
            "rhythm": {
                "cut_density": "high",
                "transition": "hard_cut",
                "cut_on_action": True,
                "cut_on_sound": True,
            },
            "typography": {"render_mode": "deterministic_overlay", "generated_text": "forbidden"},
            "positive_lock": [
                "真实工业纪录广告",
                "主体身份和材料细节稳定",
                "全片使用同一视觉世界",
                "运镜缓慢、稳定、克制",
            ],
            "negative_lock": [
                "禁止科幻工厂、电商白底、赛博朋克和青橙调色",
                "禁止快速推拉、镜头绕飞、手持抖动、频闪和曝光抽动",
                "禁止人物复制、手部畸形、工具和机器结构漂移",
                "禁止生成Logo、包装文字、字幕、水印和二维码",
                "禁止编造认证、检测结果、产品结构或工艺",
            ],
        },
        "prompt_rules": {
            "template_language": "viraldna-template/v2",
            "language": "zh-CN",
            "allowed_variables": [
                "brand.name",
                "brand.category",
                "brief.objective",
                "brief.audience",
                "shot.title",
                "shot.subject",
                "shot.action",
                "shot.assets",
            ],
            "image_sections": [
                "reference_binding",
                "subject_and_environment",
                "material_state",
                "composition_and_lens",
                "lighting_color_texture",
                "continuity_lock",
                "exact_asset_reservation",
                "negative_constraints",
            ],
            "video_sections": [
                "accepted_frame_binding",
                "global_visual_lock",
                "shot_execution",
                "synchronous_audio",
                "cut_out",
                "strict_constraints",
            ],
            "image_target_characters": {"min": 260, "max": 700},
            "video_target_characters": {"min": 450, "max": 850},
            "independent_prompt_per_shot": True,
            "repeat_relevant_continuity_locks": True,
            "model_profiles": {
                "seedance": {
                    "single_continuous_shot": True,
                    "explicit_motion_distance": True,
                    "explicit_audio": True,
                    "disable_auto_music": True,
                    "disable_auto_cut": True,
                }
            },
        },
        "continuity": {
            "required_dimensions": [
                "environment_identity",
                "character_identity",
                "product_geometry",
                "product_material",
                "wardrobe",
                "palette",
                "lighting_direction",
                "camera_character",
                "sound_bed",
            ],
            "repeat_relevant_locks_in_every_prompt": True,
            "compare_adjacent_shots": True,
        },
        "audio": {
            "dialogue": "forbidden",
            "narration": "forbidden",
            "shot_music": "forbidden",
            "synchronous_foley": {
                "required": True,
                "qualities": ["near_field", "restrained", "physically_matched"],
            },
            "ambience": {"strategy": "continuous_sound_bed", "level": "low"},
            "editing_music": {
                "style": "minimal_low_frequency_industrial",
                "bpm": 124,
                "bpm_tolerance": 6,
            },
        },
        "editing": {
            "allowed_transitions": ["hard_cut"],
            "forbidden_transitions": ["dissolve", "flash", "glitch", "particles"],
            "cut_rules": [
                "在动作完成点切出",
                "在机械触点或拟音落点硬切",
                "连续环境底噪跨镜头不断",
                "产品定妆阶段适当延长停留",
            ],
            "opening_rhythm": "快速材料细节钩子",
            "middle_rhythm": "工艺和检测动作形成机械击点蒙太奇",
            "ending_rhythm": "产品定妆后以品牌片尾收束",
        },
        "typography_system": {
            "generated_text_policy": "forbidden",
            "render_mode": "deterministic_overlay",
            "default_fonts": {
                "zh_display": "Source Han Sans SC",
                "zh_body": "Source Han Sans SC",
                "latin_numeric": "Roboto Condensed",
            },
            "hierarchy": {"headline": {"weight": 700, "max_lines": 2}, "caption": {"weight": 500}},
            "placement": {"safe_area_percent": 8, "avoid_covering_product": True},
            "allowed_motion": ["fade", "mask_reveal", "subtle_linear_slide"],
            "forbidden_motion": ["elastic", "bounce", "particle_assembly"],
        },
        "grounding": {
            "source_priority": [
                "exact_project_assets",
                "category_profile",
                "approved_claim_evidence",
                "creative_objective",
                "skill_style_rules",
            ],
            "forbidden_inventions": [
                "product_claim",
                "certification",
                "factory_process",
                "machine_structure",
                "measurement_result",
            ],
            "missing_fact_policy": "substitute",
            "max_assets_per_shot": 3,
        },
        "quality": {
            "hard_rules": [
                "exact_assets_not_redrawn",
                "no_unverified_claims",
                "rights_confirmed_before_public_export",
                "image_prompt_is_static",
                "video_prompt_binds_accepted_frame",
                "single_primary_action_per_shot",
            ],
            "minimum_prompt_score": 85,
            "maximum_rewrite_attempts": 2,
            "required_image_sections": ["主体与场景", "构图与镜头", "光线与色彩", "严格约束"],
            "required_video_sections": [
                "首帧约束",
                "统一视觉锁定",
                "本镜头",
                "同步音效",
                "严格约束",
            ],
            "reject_vague_camera_language": True,
        },
        "canonical_cases": [
            {
                "id": "hdasher_factory_17_shots",
                "title": "HDASHER 空调滤芯工厂 17 镜头",
                "purpose": "工业工艺质感品牌短片的结构与提示词质量基线",
                "target_duration_seconds": 18.15,
                "shot_count": 17,
                "style_metrics": {
                    "detail_ratio": 0.7,
                    "environment_ratio": 0.3,
                    "edit_duration_seconds": [0.7, 1.55],
                    "video_prompt_characters": [450, 850],
                    "fps": 24,
                    "transition": "hard_cut",
                    "music_bpm": 124,
                },
                "sequence": [item[0] for item in archetypes],
                "representative_shots": [
                    {
                        "archetype": "material_macro",
                        "must_include": [
                            "唯一首帧",
                            "100mm微距",
                            "极慢滑轨",
                            "近场材料声",
                            "材质形态稳定",
                        ],
                    },
                    {
                        "archetype": "precision_action",
                        "must_include": [
                            "单次精确动作",
                            "固定机位",
                            "触点对焦",
                            "机械击点",
                            "工具结构稳定",
                        ],
                    },
                    {
                        "archetype": "packaging_tableau",
                        "must_include": [
                            "包装平面锁定",
                            "极慢推近",
                            "产品定妆",
                            "品牌低频落点",
                            "禁止文字重绘",
                        ],
                    },
                ],
                "forbidden_copy_terms": ["HDASHER", "空调滤芯", "滤材", "褶皱"],
            }
        ],
    }


def _default_manifest(
    *,
    skill_id: str,
    version: str,
    name: str,
    summary: str,
    category: str,
    cover_url: str,
    keywords: list[str],
    channels: list[str],
    goals: list[str],
    asset_role: str,
    asset_label: str,
    fidelity: str,
    camera_motion: list[str],
) -> SkillManifest:
    payload: dict[str, object] = {
        "api_version": "viraldna.video-skill/v1",
        "kind": "VideoSkill",
        "metadata": {
            "id": skill_id,
            "version": version,
            "name": name,
            "summary": summary,
            "category": category,
            "tags": keywords[:6],
            "locale": "zh-CN",
            "cover_url": cover_url,
        },
        "resources": [],
        "spec": {
            "intent": {
                "supported_goals": goals,
                "supported_channels": channels,
                "duration_seconds": {"min": 10, "max": 60},
                "aspect_ratios": ["9:16", "16:9", "1:1", "4:5"],
            },
            "intake": {
                "required_fields": [
                    "brand",
                    "objective",
                    "audience",
                    "distribution_channel",
                    "target_duration",
                    "output_aspect_ratio",
                ],
                "creative_basis": {
                    "allowed": ["brand_led", "reference_led", "hybrid"],
                    "recommended": "hybrid",
                },
                "asset_roles": [
                    {
                        "role": asset_role,
                        "label": asset_label,
                        "media_types": ["image"],
                        "min_count": 1,
                        "max_count": 8,
                        "fidelity": fidelity,
                    },
                    {
                        "role": "logo",
                        "label": "品牌 Logo",
                        "media_types": ["image"],
                        "min_count": 0,
                        "max_count": 2,
                        "fidelity": "exact",
                    },
                    {
                        "role": "reference_video",
                        "label": "风格参考视频",
                        "media_types": ["video"],
                        "min_count": 0,
                        "max_count": 3,
                        "fidelity": "style_only",
                    },
                ],
                "questions": [
                    {
                        "key": "primary_message",
                        "label": "观众看完后最应记住什么？",
                        "type": "long_text",
                        "required": True,
                        "max_length": 500,
                    }
                ],
            },
            "narrative": {
                "outline_pattern": [
                    {
                        "key": "hook",
                        "target_duration_ratio": 0.15,
                        "purpose": "首屏建立清晰悬念或利益点",
                    },
                    {
                        "key": "reveal",
                        "target_duration_ratio": 0.25,
                        "purpose": "揭示主体和真实使用情境",
                    },
                    {
                        "key": "proof",
                        "target_duration_ratio": 0.40,
                        "purpose": "用已批准事实解释核心价值",
                    },
                    {
                        "key": "resolution",
                        "target_duration_ratio": 0.20,
                        "purpose": "收束情绪并给出行动指引",
                    },
                ],
                "shot_count": {"min": 4, "max": 12},
            },
            "style": {
                "visual_keywords": keywords,
                "palette_policy": {"source": "brand_then_reference"},
                "composition": {
                    "principles": [
                        "one dominant subject per shot",
                        "reserve safe area for deterministic typography",
                    ]
                },
                "lighting": {"principles": ["controlled motivated lighting"]},
                "camera": {
                    "allowed_motion": camera_motion,
                    "avoid_motion": ["random_handheld", "unmotivated_whip_pan"],
                },
                "rhythm": {"cut_density": "medium"},
                "typography": {
                    "render_mode": "deterministic_overlay",
                    "max_lines": 2,
                },
                "positive_lock": [
                    "preserve subject identity and material detail",
                    "keep one coherent visual language",
                ],
                "negative_lock": [
                    "no invented certifications or claims",
                    "no generated logo or unreadable packaging text",
                    "no unexplained identity changes",
                ],
            },
            "prompt_rules": {
                "template_language": "viraldna-template/v1",
                "allowed_variables": [
                    "brand.name",
                    "brief.objective",
                    "brief.audience",
                    "shot.description",
                    "shot.narrative_role",
                ],
                "image_sections": [
                    "subject_and_action",
                    "environment",
                    "composition",
                    "lighting_and_color",
                    "asset_fidelity",
                    "negative_constraints",
                ],
                "video_sections": [
                    "accepted_frame_binding",
                    "action_progression",
                    "camera_motion",
                    "temporal_continuity",
                    "audio_intent",
                    "negative_constraints",
                ],
            },
            "continuity": {
                "default_locks": [
                    "subject_identity",
                    "screen_direction",
                    "palette",
                ],
                "allow_intentional_change_with_reason": True,
            },
            "workflow": {
                "automation_default": "guided",
                "automation_allowed": ["guided", "full_auto"],
                "look_test": {
                    "required": True,
                    "representative_count": 2,
                    "use_output_aspect_ratio": True,
                },
                "gates": [
                    "brief_approved",
                    "style_approved",
                    "storyboard_approved",
                    "images_approved",
                    "videos_approved",
                    "picture_locked",
                    "audio_caption_approved",
                    "delivery_approved",
                ],
            },
            "generation_policy": {
                "user_must_select": [
                    "image_model",
                    "image_resolution",
                    "video_model",
                    "video_resolution",
                ],
                "allow_silent_provider_fallback": False,
                "image_capabilities": [
                    "text_to_image",
                    "image_to_image",
                    "aspect_ratio_control",
                ],
                "video_capabilities": ["image_to_video", "duration_control"],
                "recommended_candidate_counts": {
                    "look_test": 2,
                    "shot_image": 2,
                    "shot_video": 1,
                },
            },
            "audio": {
                "music": {
                    "timing": "after_picture_lock",
                    "strategy": "coherent_full_timeline_track",
                },
                "voiceover": {"enabled": "optional"},
                "sound_effects": {"enabled": "optional"},
            },
            "captions": {
                "source": "final_speech_track",
                "deterministic_render": True,
                "safe_area_required": True,
            },
            "quality": {
                "hard_rules": [
                    "exact_assets_not_redrawn",
                    "no_unverified_claims",
                    "rights_confirmed_before_public_export",
                ]
            },
            "delivery": {
                "require_manifest": True,
                "require_content_hashes": True,
                "require_media_probe": True,
            },
        },
    }
    if skill_id == "platform.cinematic-product-story":
        profile = _industrial_craft_profile()
        payload["api_version"] = profile["api_version"]
        spec = payload["spec"]
        assert isinstance(spec, dict)
        for key, value in profile.items():
            if key != "api_version":
                spec[key] = value
    return SkillManifest.model_validate(payload)


def _seed_state() -> SkillCatalogState:
    now = utc_now()
    definitions = [
        (
            "platform.cinematic-product-story",
            "cinematic-product-story",
            "电影感产品故事",
            "以克制电影摄影、材质细节和清晰叙事呈现产品价值。",
            "商业广告",
            "/skill-covers/cinematic-product.svg",
            ["产品", "电影感", "品牌", "材质细节"],
            ["douyin", "xiaohongshu", "wechat_channels"],
            ["product_launch", "product_education", "brand_story"],
            "product_hero",
            "产品主图",
            "identity_lock",
            ["locked", "slow_push", "slow_orbit", "macro_slide"],
        ),
        (
            "platform.creator-explainer",
            "creator-explainer",
            "自媒体分步讲解",
            "用真人讲解、步骤演示和证据画面完成清楚可信的短视频。",
            "自媒体创作",
            "/skill-covers/creator-explainer.svg",
            ["讲解", "真人", "步骤", "可信"],
            ["douyin", "xiaohongshu", "bilibili"],
            ["product_education", "tutorial", "creator_content"],
            "presenter",
            "出镜人物",
            "identity_lock",
            ["locked", "gentle_follow", "detail_insert"],
        ),
        (
            "platform.rhythmic-sports-short",
            "rhythmic-sports-short",
            "节奏运动短片",
            "以动作阶段、方向连续和音乐节拍组织有冲击力的运动短片。",
            "专业影视",
            "/skill-covers/rhythmic-sports.svg",
            ["运动", "节奏", "动作连续", "高能"],
            ["douyin", "bilibili", "wechat_channels"],
            ["event_recap", "sports_promo", "brand_story"],
            "athlete",
            "人物或队伍",
            "identity_lock",
            ["tracking", "low_angle_follow", "controlled_whip"],
        ),
    ]
    skills: list[PlatformSkill] = []
    versions: list[PlatformSkillVersion] = []
    for (
        skill_id,
        slug,
        name,
        summary,
        category,
        cover_url,
        keywords,
        channels,
        goals,
        role,
        role_label,
        fidelity,
        camera_motion,
    ) in definitions:
        manifest_version = "2.0.0" if skill_id == "platform.cinematic-product-story" else "1.0.0"
        manifest = _default_manifest(
            skill_id=skill_id,
            version=manifest_version,
            name=name,
            summary=summary,
            category=category,
            cover_url=cover_url,
            keywords=keywords,
            channels=channels,
            goals=goals,
            asset_role=role,
            asset_label=role_label,
            fidelity=fidelity,
            camera_motion=camera_motion,
        )
        version_id = uuid5(NAMESPACE_URL, f"viraldna:{skill_id}:{manifest_version}")
        version = PlatformSkillVersion(
            id=version_id,
            skill_id=skill_id,
            version=manifest_version,
            revision_number=1,
            manifest=manifest,
            content_digest=manifest_digest(manifest),
            changelog=(
                "升级为工业工艺品牌短片 Skill v2，加入标准案例、镜头语法和提示词质检"
                if manifest_version == "2.0.0"
                else "平台首发版本"
            ),
            status=SkillLifecycle.PUBLISHED,
            created_at=now,
            published_at=now,
        )
        versions.append(version)
        skills.append(
            PlatformSkill(
                id=skill_id,
                slug=slug,
                name=name,
                summary=summary,
                category=category,
                tags=keywords,
                cover_url=cover_url,
                lifecycle=SkillLifecycle.PUBLISHED,
                current_published_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
        )
    return SkillCatalogState(skills=skills, versions=versions)


def _merge_builtin_updates(state: SkillCatalogState) -> tuple[SkillCatalogState, bool]:
    """Publish new built-in versions without mutating frozen project snapshots."""

    seed = _seed_state()
    desired = next(
        item
        for item in seed.versions
        if item.skill_id == "platform.cinematic-product-story" and item.version == "2.0.0"
    )
    if any(item.id == desired.id for item in state.versions):
        return state, False
    skill = next(
        (item for item in state.skills if item.id == desired.skill_id),
        None,
    )
    if skill is None:
        desired_skill = next(item for item in seed.skills if item.id == desired.skill_id)
        state.skills.append(desired_skill)
        state.versions.append(desired)
        return state, True
    current = next(
        (item for item in state.versions if item.id == skill.current_published_version_id),
        None,
    )
    # A platform-admin-authored newer version always wins over the built-in migration.
    if current is not None and current.version not in {"1.0.0", "1.1.0"}:
        return state, False
    next_revision = (
        max(
            (item.revision_number for item in state.versions if item.skill_id == desired.skill_id),
            default=0,
        )
        + 1
    )
    migrated = desired.model_copy(update={"revision_number": next_revision})
    state.versions.append(migrated)
    skill.current_published_version_id = migrated.id
    skill.lifecycle = SkillLifecycle.PUBLISHED
    skill.name = migrated.manifest.metadata.name
    skill.summary = migrated.manifest.metadata.summary
    skill.tags = migrated.manifest.metadata.tags
    skill.updated_at = utc_now()
    return state, True


class PlatformSkillCatalogService:
    def __init__(self, state_path: Path | None = None, resource_root: Path | None = None) -> None:
        self.state_path = state_path.resolve() if state_path else None
        self.resource_root = (
            resource_root.resolve()
            if resource_root
            else (self.state_path.parent / "platform-skill-resources" if self.state_path else None)
        )
        self._lock = asyncio.Lock()
        self._memory_state: SkillCatalogState | None = None

    def _read_state(self) -> SkillCatalogState:
        if self.state_path is None:
            if self._memory_state is None:
                self._memory_state = _seed_state()
            return self._memory_state.model_copy(deep=True)
        if not self.state_path.is_file():
            state = _seed_state()
            self._write_state(state)
            return state
        try:
            state = SkillCatalogState.model_validate_json(self.state_path.read_text("utf-8-sig"))
            state, changed = _merge_builtin_updates(state)
            if changed:
                self._write_state(state)
            return state
        except (OSError, ValidationError) as exc:
            raise PlatformSkillError(
                500,
                "skill_catalog_invalid",
                "平台 Skill 目录损坏，已停止读取",
            ) from exc

    def _write_state(self, state: SkillCatalogState) -> None:
        if self.state_path is None:
            self._memory_state = state.model_copy(deep=True)
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump_json(indent=2)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            dir=self.state_path.parent,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.state_path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    async def list_catalog(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        favorite_skill_ids: set[str] | None = None,
    ) -> SkillCatalogListResponse:
        state = await asyncio.to_thread(self._read_state)
        favorites = favorite_skill_ids or set()
        normalized_query = (query or "").strip().casefold()
        items: list[SkillCatalogItem] = []
        for skill in state.skills:
            if skill.lifecycle != SkillLifecycle.PUBLISHED:
                continue
            version = next(
                (
                    item
                    for item in state.versions
                    if item.id == skill.current_published_version_id
                    and item.status == SkillLifecycle.PUBLISHED
                ),
                None,
            )
            if version is None:
                continue
            searchable = " ".join(
                [skill.name, skill.summary, skill.category, *skill.tags]
            ).casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            if category and skill.category != category:
                continue
            spec = version.manifest.spec
            items.append(
                SkillCatalogItem(
                    **skill.model_dump(mode="python"),
                    current_version=version,
                    favorited=skill.id in favorites,
                    supported_channels=spec.intent.supported_channels,
                    aspect_ratios=spec.intent.aspect_ratios,
                    duration_seconds=spec.intent.duration_seconds,
                    asset_roles=spec.intake.asset_roles,
                )
            )
        items.sort(key=lambda item: (-item.usage_count, item.name.casefold()))
        categories = sorted(
            {
                skill.category
                for skill in state.skills
                if skill.lifecycle == SkillLifecycle.PUBLISHED
            }
        )
        return SkillCatalogListResponse(
            items=items,
            total=len(items),
            categories=categories,
        )

    async def get_catalog_item(
        self,
        slug: str,
        *,
        favorite_skill_ids: set[str] | None = None,
    ) -> SkillCatalogItem:
        state = await asyncio.to_thread(self._read_state)
        skill = next(
            (
                item
                for item in state.skills
                if item.slug == slug and item.lifecycle == SkillLifecycle.PUBLISHED
            ),
            None,
        )
        if skill is None or skill.current_published_version_id is None:
            raise PlatformSkillError(404, "skill_not_found", "Skill 不存在或尚未发布")
        version = next(
            (item for item in state.versions if item.id == skill.current_published_version_id),
            None,
        )
        if version is None:
            raise PlatformSkillError(409, "skill_version_missing", "Skill 发布版本不存在")
        spec = version.manifest.spec
        return SkillCatalogItem(
            **skill.model_dump(mode="python"),
            current_version=version,
            favorited=skill.id in (favorite_skill_ids or set()),
            supported_channels=spec.intent.supported_channels,
            aspect_ratios=spec.intent.aspect_ratios,
            duration_seconds=spec.intent.duration_seconds,
            asset_roles=spec.intake.asset_roles,
        )

    async def get_version(self, version_id: UUID) -> PlatformSkillVersion:
        state = await asyncio.to_thread(self._read_state)
        version = next((item for item in state.versions if item.id == version_id), None)
        if version is None:
            raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
        return version

    async def require_usable_version(self, version_id: UUID) -> PlatformSkillVersion:
        version = await self.get_version(version_id)
        if version.status != SkillLifecycle.PUBLISHED:
            raise PlatformSkillError(
                409,
                "skill_version_not_available",
                "该 Skill 版本当前不能用于新建项目",
            )
        return version

    async def list_admin(self) -> SkillCatalogState:
        return await asyncio.to_thread(self._read_state)

    async def create_version(self, payload: SkillVersionCreate) -> PlatformSkillVersion:
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            skill = next(
                (item for item in state.skills if item.id == payload.manifest.metadata.id),
                None,
            )
            now = utc_now()
            if skill is None:
                slug = payload.manifest.metadata.id.removeprefix("platform.").replace(".", "-")
                skill = PlatformSkill(
                    id=payload.manifest.metadata.id,
                    slug=slug,
                    name=payload.manifest.metadata.name,
                    summary=payload.manifest.metadata.summary,
                    category=payload.manifest.metadata.category,
                    tags=payload.manifest.metadata.tags,
                    cover_url=payload.manifest.metadata.cover_url,
                    lifecycle=SkillLifecycle.DRAFT,
                    created_at=now,
                    updated_at=now,
                )
                state.skills.append(skill)
            if any(
                item.skill_id == skill.id and item.version == payload.manifest.metadata.version
                for item in state.versions
            ):
                raise PlatformSkillError(
                    409,
                    "skill_version_exists",
                    "该 Skill 版本号已经存在",
                )
            revision_number = (
                max(
                    (item.revision_number for item in state.versions if item.skill_id == skill.id),
                    default=0,
                )
                + 1
            )
            version = PlatformSkillVersion(
                skill_id=skill.id,
                version=payload.manifest.metadata.version,
                revision_number=revision_number,
                manifest=payload.manifest,
                content_digest=manifest_digest(payload.manifest),
                changelog=payload.changelog,
            )
            state.versions.append(version)
            skill.name = payload.manifest.metadata.name
            skill.summary = payload.manifest.metadata.summary
            skill.category = payload.manifest.metadata.category
            skill.tags = payload.manifest.metadata.tags
            skill.cover_url = payload.manifest.metadata.cover_url
            skill.updated_at = now
            await asyncio.to_thread(self._write_state, state)
            return version

    async def update_draft(
        self,
        version_id: UUID,
        payload: SkillVersionCreate,
    ) -> PlatformSkillVersion:
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            index = next(
                (idx for idx, item in enumerate(state.versions) if item.id == version_id),
                None,
            )
            if index is None:
                raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
            current = state.versions[index]
            if current.status != SkillLifecycle.DRAFT:
                raise PlatformSkillError(
                    409,
                    "published_skill_immutable",
                    "已发布的 Skill 版本不可修改，请创建新版本",
                )
            if payload.manifest.metadata.id != current.skill_id:
                raise PlatformSkillError(422, "skill_id_immutable", "Skill ID 不可修改")
            updated = current.model_copy(
                update={
                    "version": payload.manifest.metadata.version,
                    "manifest": payload.manifest,
                    "content_digest": manifest_digest(payload.manifest),
                    "changelog": payload.changelog,
                }
            )
            state.versions[index] = updated
            await asyncio.to_thread(self._write_state, state)
            return updated

    async def validate_version(self, version_id: UUID) -> SkillValidationResult:
        version = await self.get_version(version_id)
        issues: list[str] = []
        resource_keys = {item.key for item in version.manifest.resources}
        if (
            version.manifest.metadata.cover_resource
            and version.manifest.metadata.cover_resource not in resource_keys
        ):
            issues.append("封面资源不存在")
        if version.content_digest != manifest_digest(version.manifest):
            issues.append("清单内容摘要不一致")
        return SkillValidationResult(
            valid=not issues,
            issues=issues,
            content_digest=manifest_digest(version.manifest),
            resource_count=len(version.manifest.resources),
        )

    async def publish(self, version_id: UUID, admin_id: UUID | None) -> PlatformSkillVersion:
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            version_index = next(
                (idx for idx, item in enumerate(state.versions) if item.id == version_id),
                None,
            )
            if version_index is None:
                raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
            current = state.versions[version_index]
            if current.status == SkillLifecycle.BLOCKED:
                raise PlatformSkillError(409, "skill_version_blocked", "已阻断版本不能发布")
            validation = await self.validate_version(version_id)
            if not validation.valid:
                raise PlatformSkillError(
                    422,
                    "skill_validation_failed",
                    "；".join(validation.issues),
                )
            now = utc_now()
            published = current.model_copy(
                update={
                    "status": SkillLifecycle.PUBLISHED,
                    "published_at": current.published_at or now,
                    "published_by": admin_id,
                }
            )
            state.versions[version_index] = published
            skill = next(item for item in state.skills if item.id == current.skill_id)
            skill.lifecycle = SkillLifecycle.PUBLISHED
            skill.current_published_version_id = published.id
            skill.updated_at = now
            await asyncio.to_thread(self._write_state, state)
            return published

    async def set_version_status(
        self,
        version_id: UUID,
        status: SkillLifecycle,
    ) -> PlatformSkillVersion:
        if status not in {SkillLifecycle.DEPRECATED, SkillLifecycle.BLOCKED}:
            raise PlatformSkillError(422, "skill_status_invalid", "只支持弃用或阻断版本")
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            index = next(
                (idx for idx, item in enumerate(state.versions) if item.id == version_id),
                None,
            )
            if index is None:
                raise PlatformSkillError(404, "skill_version_not_found", "Skill 版本不存在")
            updated = state.versions[index].model_copy(update={"status": status})
            state.versions[index] = updated
            skill = next(item for item in state.skills if item.id == updated.skill_id)
            if skill.current_published_version_id == updated.id:
                skill.lifecycle = status
                skill.updated_at = utc_now()
            await asyncio.to_thread(self._write_state, state)
            return updated

    async def import_package(
        self,
        payload: bytes,
        *,
        changelog: str = "",
    ) -> PlatformSkillVersion:
        if not payload:
            raise PlatformSkillError(422, "skill_package_empty", "Skill 包不能为空")
        if len(payload) > MAX_SKILL_PACKAGE_BYTES:
            raise PlatformSkillError(413, "skill_package_too_large", "Skill 包不能超过 50 MB")
        with tempfile.TemporaryDirectory(prefix="viraldna-skill-") as directory:
            archive_path = Path(directory) / "skill.zip"
            archive_path.write_bytes(payload)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    entries = archive.infolist()
                    if len(entries) > MAX_SKILL_PACKAGE_ENTRIES:
                        raise PlatformSkillError(
                            422,
                            "skill_package_too_many_entries",
                            "Skill 包文件数量超过限制",
                        )
                    by_name: dict[str, zipfile.ZipInfo] = {}
                    for entry in entries:
                        normalized = PurePosixPath(entry.filename.replace("\\", "/"))
                        if normalized.is_absolute() or ".." in normalized.parts or entry.is_dir():
                            if entry.is_dir():
                                continue
                            raise PlatformSkillError(
                                422,
                                "skill_package_path_invalid",
                                "Skill 包包含不安全路径",
                            )
                        if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            raise PlatformSkillError(
                                422,
                                "skill_package_symlink_forbidden",
                                "Skill 包不能包含符号链接",
                            )
                        if normalized.suffix.casefold() in BLOCKED_EXTENSIONS:
                            raise PlatformSkillError(
                                422,
                                "skill_package_executable_forbidden",
                                "Skill 包不能包含可执行文件或脚本",
                            )
                        if entry.file_size > MAX_SKILL_RESOURCE_BYTES:
                            raise PlatformSkillError(
                                413,
                                "skill_resource_too_large",
                                "单个 Skill 资源不能超过 25 MB",
                            )
                        by_name[normalized.as_posix()] = entry
                    manifest_entry = by_name.get("skill.yaml")
                    if manifest_entry is None:
                        raise PlatformSkillError(
                            422,
                            "skill_manifest_missing",
                            "Skill 包根目录缺少 skill.yaml",
                        )
                    try:
                        manifest_payload = yaml.safe_load(
                            archive.read(manifest_entry).decode("utf-8-sig")
                        )
                        manifest = SkillManifest.model_validate(manifest_payload)
                    except (UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
                        raise PlatformSkillError(
                            422,
                            "skill_manifest_invalid",
                            f"Skill 清单无效：{exc}",
                        ) from exc
                    declared = {item.path: item for item in manifest.resources}
                    actual_resources = {name for name in by_name if name.startswith("resources/")}
                    if actual_resources != set(declared):
                        raise PlatformSkillError(
                            422,
                            "skill_resource_manifest_mismatch",
                            "Skill 包资源与清单声明不一致",
                        )
                    for path, resource in declared.items():
                        content = archive.read(by_name[path])
                        if hashlib.sha256(content).hexdigest() != resource.sha256:
                            raise PlatformSkillError(
                                422,
                                "skill_resource_hash_mismatch",
                                f"资源 {resource.key} 的 SHA-256 不一致",
                            )
                    version = await self.create_version(
                        SkillVersionCreate(manifest=manifest, changelog=changelog)
                    )
                    if self.resource_root is not None and manifest.resources:
                        version_root = self.resource_root / str(version.id)
                        version_root.mkdir(parents=True, exist_ok=False)
                        for path in declared:
                            destination = version_root / PurePosixPath(path)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(archive.read(by_name[path]))
                    return version
            except zipfile.BadZipFile as exc:
                raise PlatformSkillError(
                    422,
                    "skill_package_invalid",
                    "Skill 包不是有效 ZIP 文件",
                ) from exc
