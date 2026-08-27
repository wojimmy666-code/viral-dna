from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import (
    ShotPlan,
    ShotVisualBeat,
    VideoGenerationIntentIR,
    VideoGenerationReference,
    VideoIntentDimension,
    VideoIntentDirective,
    VideoIntentFidelity,
    VideoIntentOperation,
    VideoPromptMention,
    VideoPromptReferenceKind,
    VideoPromptReferenceRole,
)

DIMENSION_LABELS = {
    VideoIntentDimension.IDENTITY: "人物身份",
    VideoIntentDimension.WARDROBE: "人物服装",
    VideoIntentDimension.PRODUCT: "产品",
    VideoIntentDimension.SCENE: "场景",
    VideoIntentDimension.PROP: "道具",
    VideoIntentDimension.MOTION: "人物动作",
    VideoIntentDimension.CAMERA: "镜头运动",
    VideoIntentDimension.TIMING: "动作节奏",
    VideoIntentDimension.COMPOSITION: "构图",
    VideoIntentDimension.TRANSITION: "转场",
    VideoIntentDimension.DIALOGUE: "对白",
    VideoIntentDimension.AUDIO: "声音",
    VideoIntentDimension.LIGHTING: "光线",
    VideoIntentDimension.STYLE: "视觉风格",
}

DIMENSION_ROLES = {
    VideoIntentDimension.IDENTITY: VideoPromptReferenceRole.ACTOR_IDENTITY,
    VideoIntentDimension.WARDROBE: VideoPromptReferenceRole.WARDROBE,
    VideoIntentDimension.PRODUCT: VideoPromptReferenceRole.PRODUCT,
    VideoIntentDimension.SCENE: VideoPromptReferenceRole.SCENE,
    VideoIntentDimension.PROP: VideoPromptReferenceRole.COMPOSITION,
    VideoIntentDimension.MOTION: VideoPromptReferenceRole.MOTION,
    VideoIntentDimension.CAMERA: VideoPromptReferenceRole.CAMERA,
    VideoIntentDimension.COMPOSITION: VideoPromptReferenceRole.COMPOSITION,
    VideoIntentDimension.TRANSITION: VideoPromptReferenceRole.TRANSITION,
    VideoIntentDimension.STYLE: VideoPromptReferenceRole.STYLE,
}

REFERENCE_STATE_TEMPLATES = {
    VideoPromptReferenceRole.ACTOR_IDENTITY: (
        "{scope}人物的面部身份、五官、脸型、年龄感和稳定外貌以 {token} 为唯一来源"
    ),
    VideoPromptReferenceRole.WARDROBE: (
        "{scope}人物服装以 {token} 展示的款式、材质、颜色和穿着状态为准"
    ),
    VideoPromptReferenceRole.PRODUCT: (
        "{scope}产品以 {token} 展示的结构、材质、颜色和品牌外观为准"
    ),
    VideoPromptReferenceRole.SCENE: (
        "{scope}场景以 {token} 展示的空间、陈设、材质、光线和环境状态为准"
    ),
    VideoPromptReferenceRole.COMPOSITION: (
        "{scope}构图、主体尺度和画面元素以 {token} 为准"
    ),
    VideoPromptReferenceRole.STYLE: (
        "{scope}画面质感、色彩和视觉风格以 {token} 为准"
    ),
}

IMAGE_ASPECTS = (
    (VideoPromptReferenceRole.WARDROBE, "服装"),
    (VideoPromptReferenceRole.PRODUCT, "产品"),
    (VideoPromptReferenceRole.SCENE, "场景"),
    (VideoPromptReferenceRole.COMPOSITION, "构图与主体空间位置"),
    (VideoPromptReferenceRole.STYLE, "光线、色彩与画面质感"),
)

DEPTH_DIMENSIONS = {
    VideoIntentDimension.MOTION,
    VideoIntentDimension.CAMERA,
    VideoIntentDimension.TIMING,
    VideoIntentDimension.COMPOSITION,
}

EDIT_PROCESS_MARKERS = (
    "替换",
    "更换",
    "换成",
    "改为",
    "重新设计",
    "移除",
    "删除",
    "原人物",
    "原服装",
    "原场景",
    "保持原样",
    "其他保持不变",
    "其他指令",
    "用户要求",
)

REFERENCE_TOKEN_PATTERN = re.compile(
    r"@[^\s，。；：、,.;:!?！？（）()\[\]【】<>《》]+"
)

FINAL_STATE_REWRITES = (
    ("保持原视频的", "采用"),
    ("保留原视频的", "采用"),
    ("沿用原视频的", "采用"),
    ("复刻原视频的", "采用"),
)


def _token(reference: VideoGenerationReference) -> str:
    return f"@{reference.label.strip().lstrip('@')}"


def _stable_reference_keys(reference: VideoGenerationReference) -> set[str]:
    keys = {f"{reference.reference_kind.value}:{reference.reference_id}"}
    beat_id = reference.visual_beat_id or (
        reference.scope.visual_beat_ids[0] if reference.scope.visual_beat_ids else None
    )
    if reference.reference_kind == VideoPromptReferenceKind.APPROVED_IMAGE and beat_id:
        keys.add(f"approved_image:visual_beat:{beat_id}")
    return keys


def _normalized(value: str | None) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _safe_positive_text(
    value: str | None,
    *,
    allowed_tokens: Iterable[str] = (),
    max_length: int | None = None,
) -> str:
    text = str(value or "").strip().strip("- ")
    if not text:
        return ""
    for source, replacement in FINAL_STATE_REWRITES:
        text = text.replace(source, replacement)
    allowed = set(allowed_tokens)
    text = REFERENCE_TOKEN_PATTERN.sub(
        lambda match: match.group(0) if match.group(0) in allowed else "",
        text,
    )
    fragments = re.split(r"(?<=[。！？；\n])", text)
    text = "".join(
        fragment
        for fragment in fragments
        if fragment.strip()
        and not any(marker in fragment for marker in EDIT_PROCESS_MARKERS)
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text).strip(" ，,；;\n")
    if not text:
        return ""
    if max_length is not None and len(text) > max_length:
        clipped = text[:max_length].rstrip(" ，,；;：:\n")
        sentence_end = max(clipped.rfind("。"), clipped.rfind("；"), clipped.rfind("！"))
        text = clipped[: sentence_end + 1] if sentence_end >= max_length // 2 else clipped
    return text if text.endswith(("。", "！", "？")) else text + "。"


def _reference_tokens(references: Iterable[VideoGenerationReference]) -> set[str]:
    return {_token(reference) for reference in references}


def _beat_visual_description(beat: ShotVisualBeat, *, max_length: int) -> str:
    text = beat.image_prompt
    for mention in beat.image_prompt_mentions:
        text = text.replace(f"@{mention.label.strip().lstrip('@')}", "")
    return _safe_positive_text(text, max_length=max_length)


def _final_value(directive: VideoIntentDirective) -> str:
    if directive.target_name:
        return directive.target_name.strip().strip("。")
    text = directive.instruction.strip().strip("。")
    for marker in ("替换为", "更换为", "换成", "改为", "重新设计为"):
        if marker in text:
            text = text.split(marker, 1)[1].strip(" ：:，,")
            break
    if any(marker in text for marker in EDIT_PROCESS_MARKERS):
        return ""
    return text


def _beat_for_reference(
    reference: VideoGenerationReference,
    shot: ShotPlan,
) -> ShotVisualBeat | None:
    return next(
        (
            beat
            for beat in shot.visual_beats
            if beat.id == reference.visual_beat_id
            or beat.id in reference.scope.visual_beat_ids
            or beat.approved_image_candidate_id == reference.reference_id
        ),
        None,
    )


def _scope_label(reference: VideoGenerationReference, shot: ShotPlan) -> str:
    indexes = [
        beat.index
        for beat in sorted(shot.visual_beats, key=lambda item: item.index)
        if beat.id in reference.scope.visual_beat_ids
    ]
    if not indexes:
        return "全程"
    return "、".join(f"图{index}" for index in indexes) + "阶段"


def _directive_scope(directive: VideoIntentDirective) -> str:
    if not directive.visual_beat_indexes:
        return "全程"
    return "、".join(f"图{index}" for index in directive.visual_beat_indexes) + "阶段"


def _reference_for_directive(
    directive: VideoIntentDirective,
    references: list[VideoGenerationReference],
) -> VideoGenerationReference | None:
    if directive.target_reference_key:
        exact = next(
            (
                reference
                for reference in references
                if directive.target_reference_key in _stable_reference_keys(reference)
            ),
            None,
        )
        if exact is not None:
            return exact
    role = DIMENSION_ROLES.get(directive.dimension)
    if role is None:
        return None
    candidates = [reference for reference in references if reference.role == role]
    if directive.target_name:
        target = _normalized(directive.target_name)
        named = [reference for reference in candidates if target in _normalized(reference.label)]
        if len(named) == 1:
            return named[0]
    return candidates[0] if len(candidates) == 1 else None


def _unique(lines: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(line for line in lines if line))


def _reference_state_lines(
    references: list[VideoGenerationReference],
    shot: ShotPlan,
) -> list[str]:
    lines: list[str] = []
    for reference in references:
        if reference.reference_kind in {
            VideoPromptReferenceKind.APPROVED_IMAGE,
            VideoPromptReferenceKind.DEPTH_CONTROL,
            VideoPromptReferenceKind.REFERENCE_VIDEO,
        }:
            continue
        template = REFERENCE_STATE_TEMPLATES.get(reference.role)
        if template is None:
            continue
        lines.append(
            "- "
            + template.format(
                scope=_scope_label(reference, shot),
                token=_token(reference),
            )
            + "。"
        )
    return _unique(lines)


def _directive_state_lines(
    intent: VideoGenerationIntentIR,
    references: list[VideoGenerationReference],
) -> list[str]:
    lines: list[str] = []
    has_depth = any(
        reference.reference_kind == VideoPromptReferenceKind.DEPTH_CONTROL
        for reference in references
    )
    for directive in intent.directives:
        if directive.operation == VideoIntentOperation.UNSPECIFIED:
            continue
        if directive.dimension == VideoIntentDimension.TRANSITION:
            continue
        target_reference = _reference_for_directive(directive, references)
        if has_depth and directive.dimension in DEPTH_DIMENSIONS and (
            directive.preferred_source == "depth_control"
            or (
                target_reference is not None
                and target_reference.reference_kind == VideoPromptReferenceKind.DEPTH_CONTROL
            )
        ):
            continue
        scope = _directive_scope(directive)
        label = DIMENSION_LABELS[directive.dimension]
        if directive.operation in {
            VideoIntentOperation.REPLACE,
            VideoIntentOperation.REDESIGN,
        }:
            if target_reference is not None:
                # The concrete reference line already states the resolved final source. Only add
                # another line when the user explicitly scoped it to selected visual beats.
                if not directive.visual_beat_indexes:
                    continue
                value = _token(target_reference)
            else:
                value = _final_value(directive)
            if value:
                lines.append(f"- {scope}{label}呈现为 {value}。")
        elif directive.operation == VideoIntentOperation.PRESERVE:
            lines.append(f"- {scope}{label}与对应分镜参考画面的最终状态一致，并在该阶段保持稳定。")
        elif directive.operation == VideoIntentOperation.REMOVE:
            target = directive.target_name.strip() if directive.target_name else label
            lines.append(f"- {scope}画面中不出现{target}。")
    return _unique(lines)


def _format_seconds(value: float) -> str:
    return f"{max(value, 0):.2f}"


def _phase_lines(
    references: list[VideoGenerationReference],
    shot: ShotPlan,
    duration_seconds: float,
) -> list[str]:
    approved = [
        reference
        for reference in references
        if reference.reference_kind == VideoPromptReferenceKind.APPROVED_IMAGE
    ]
    overridden_roles = {
        reference.role
        for reference in references
        if reference.reference_kind
        not in {
            VideoPromptReferenceKind.APPROVED_IMAGE,
            VideoPromptReferenceKind.DEPTH_CONTROL,
            VideoPromptReferenceKind.REFERENCE_VIDEO,
        }
    }
    identity_is_external = VideoPromptReferenceRole.ACTOR_IDENTITY in overridden_roles
    lines: list[str] = []
    description_budget = max(260, min(1600, 3200 // max(len(approved), 1)))
    for reference in approved:
        beat = _beat_for_reference(reference, shot)
        start_ratio = reference.scope.start_ratio
        end_ratio = reference.scope.end_ratio
        if start_ratio is None:
            start_ratio = beat.start_ratio if beat is not None else 0
        if end_ratio is None:
            end_ratio = beat.end_ratio if beat is not None else 1
        aspects = [label for role, label in IMAGE_ASPECTS if role not in overridden_roles]
        if not aspects:
            aspects = ["构图与主体空间位置"]
        title = beat.title if beat is not None else reference.label.rsplit("/", 1)[-1]
        heading = (
            f"【{_format_seconds(start_ratio * duration_seconds)}–"
            f"{_format_seconds(end_ratio * duration_seconds)} 秒｜{title}】"
        )
        paragraphs = [
            f"该阶段的{'、'.join(aspects)}以 {_token(reference)} 为准。"
        ]
        description = _beat_visual_description(beat, max_length=description_budget) if beat else ""
        if description:
            paragraphs.append(description)
        if identity_is_external:
            paragraphs.append("人物可识别身份只采用已绑定的人物身份资产，不继承分镜图中的人物身份。")
        lines.append(heading + "\n" + "\n".join(paragraphs))
    return lines


def _depth_directives(intent: VideoGenerationIntentIR) -> list[VideoIntentDirective]:
    return [
        directive
        for directive in intent.directives
        if directive.dimension in DEPTH_DIMENSIONS
        and (
            directive.preferred_source == "depth_control"
            or str(directive.target_reference_key or "").startswith("depth_control:")
        )
        and directive.operation
        in {
            VideoIntentOperation.PRESERVE,
            VideoIntentOperation.REPLACE,
            VideoIntentOperation.REDESIGN,
        }
    ]


def _depth_policy(intent: VideoGenerationIntentIR) -> str:
    directives = _depth_directives(intent)
    if any(item.fidelity == VideoIntentFidelity.STRICT for item in directives):
        return (
            "严格遵循其动作顺序、姿态轨迹、主体位置、节奏、遮挡和镜头关系；"
            "不从该视频获取人物身份、服装、颜色或纹理"
        )
    return (
        "遵循其主要动作轨迹、空间位置、节奏和镜头关系，并允许按目标人物及最终场景"
        "做自然幅度适配；不从该视频获取人物身份、服装、颜色或纹理"
    )


def _motion_lines(
    intent: VideoGenerationIntentIR,
    references: list[VideoGenerationReference],
    shot: ShotPlan,
) -> list[str]:
    lines: list[str] = []
    allowed_tokens = _reference_tokens(references)
    for reference in references:
        if reference.reference_kind == VideoPromptReferenceKind.DEPTH_CONTROL:
            lines.append(
                f"- 人物动作、姿态、运动轨迹、节奏、空间位置与镜头关系由 "
                f"{_token(reference)} 提供；{_depth_policy(intent)}。"
            )
        elif reference.reference_kind == VideoPromptReferenceKind.REFERENCE_VIDEO and (
            reference.role in {VideoPromptReferenceRole.MOTION, VideoPromptReferenceRole.CAMERA}
        ):
            lines.append(
                f"- {_scope_label(reference, shot)}动作与镜头关系以 "
                f"{_token(reference)} 为准。"
            )
    creative = _safe_positive_text(
        intent.creative_instruction,
        allowed_tokens=allowed_tokens,
        max_length=1200,
    )
    if creative:
        lines.append(f"- {creative}")
    if intent.dialogue_text:
        lines.append(
            "- 人物表演与口型节奏对应对白："
            f"“{intent.dialogue_text.strip()}”；可用音轨由后续音频流程生成。"
        )
    return _unique(lines)


def _transition_lines(
    intent: VideoGenerationIntentIR,
    references: list[VideoGenerationReference],
    shot: ShotPlan,
    duration_seconds: float,
) -> list[str]:
    approved = [
        reference
        for reference in references
        if reference.reference_kind == VideoPromptReferenceKind.APPROVED_IMAGE
    ]
    approved_with_beats = [
        (reference, _beat_for_reference(reference, shot)) for reference in approved
    ]
    approved_with_beats = [item for item in approved_with_beats if item[1] is not None]
    directive = next(
        (
            item
            for item in intent.directives
            if item.dimension == VideoIntentDimension.TRANSITION
            and item.operation != VideoIntentOperation.UNSPECIFIED
        ),
        None,
    )
    allowed_tokens = _reference_tokens(references)
    instruction = _safe_positive_text(
        intent.transition_instruction,
        allowed_tokens=allowed_tokens,
        max_length=1000,
    )
    lines: list[str] = []
    for (current_reference, current), (next_reference, following) in zip(
        approved_with_beats,
        approved_with_beats[1:],
        strict=False,
    ):
        start = current.end_ratio * duration_seconds
        end = following.start_ratio * duration_seconds
        window = (
            f"{_format_seconds(start)}–{_format_seconds(end)} 秒"
            if end - start > 0.02
            else f"{_format_seconds(start)} 秒附近"
        )
        pair = f"{_token(current_reference)} 到 {_token(next_reference)} "
        if directive is not None and directive.operation == VideoIntentOperation.REMOVE:
            lines.append(f"- {window}，{pair}直接切换，不叠加过渡效果。")
            continue
        evidence = current.transition_to_next_prompt.strip()
        if directive is not None and directive.operation == VideoIntentOperation.PRESERVE:
            detail = instruction or evidence or "采用已分析的触发动作、遮挡关系、速度和视觉节奏"
            detail = detail.rstrip("。；;，, ")
            lines.append(
                f"- {window}，{pair}呈现连续视觉转场：{detail}；"
                "转场由视频模型生成，不使用硬切。"
            )
        elif directive is not None and directive.operation in {
            VideoIntentOperation.REPLACE,
            VideoIntentOperation.REDESIGN,
        }:
            detail = instruction or _safe_positive_text(directive.instruction)
            suffix = f"：{detail.rstrip('。')}。" if detail else "，不使用固定硬切。"
            lines.append(f"- {window}，{pair}由视频模型生成连续视觉转场{suffix}")
        elif current.transition_to_next_type == "cut":
            lines.append(f"- {window}，{pair}直接切换。")
        elif current.transition_to_next_type == "model_generated":
            detail = instruction or evidence
            suffix = (
                f"：{detail.rstrip('。')}。"
                if detail
                else (
                    "；保持人物身份、身体中心、运动方向、人物尺度、机位和空间关系连续，"
                    "不使用无依据的固定特效或硬切。"
                )
            )
            lines.append(
                f"- {window}，{pair}由视频模型结合前后画面生成连续视觉转场{suffix}"
            )
        else:
            detail = f"；{evidence}" if evidence else ""
            lines.append(
                f"- {window}，{pair}呈现 {current.transition_to_next_type} 转场{detail}。"
            )
    if not lines and instruction:
        lines.append(f"- {instruction}")
    return _unique(lines)


def compile_intent_prompt(
    intent: VideoGenerationIntentIR,
    references: Iterable[VideoGenerationReference],
    shot: ShotPlan,
    *,
    duration_seconds: float | None = None,
    output_aspect_ratio: str | None = None,
) -> tuple[str, list[VideoPromptMention], list[str]]:
    ordered = sorted(references, key=lambda item: item.order)
    duration = duration_seconds or shot.duration_seconds
    token_line = " ".join(_token(item) for item in ordered)

    orientation = ""
    if output_aspect_ratio and ":" in output_aspect_ratio:
        width, height = (int(value) for value in output_aspect_ratio.split(":", 1))
        orientation = "竖屏" if height > width else "横屏" if width > height else "方形"
    if output_aspect_ratio:
        final_state_lines = [
            f"- 生成一段 {output_aspect_ratio}、时长 {_format_seconds(duration)} 秒的"
            f"{orientation}视频。"
        ]
    else:
        final_state_lines = [f"- 视频总时长为 {_format_seconds(duration)} 秒。"]
    allowed_tokens = _reference_tokens(ordered)
    resolved_state = _safe_positive_text(
        intent.final_state_instruction,
        allowed_tokens=allowed_tokens,
        max_length=2400,
    )
    if resolved_state:
        final_state_lines.append(f"- {resolved_state}")
    final_state_lines.extend(_reference_state_lines(ordered, shot))
    final_state_lines.extend(_directive_state_lines(intent, ordered))

    phase_lines = _phase_lines(ordered, shot, duration)
    motion_lines = _motion_lines(intent, ordered, shot)
    transition_lines = _transition_lines(intent, ordered, shot, duration)

    consistency_lines: list[str] = []
    if any(reference.role == VideoPromptReferenceRole.ACTOR_IDENTITY for reference in ordered):
        consistency_lines.append(
            "- 全片人物面部、五官、脸型、年龄感和稳定外貌一致，不发生身份漂移。"
        )
    if len(phase_lines) > 1:
        consistency_lines.extend(
            [
                "- 各阶段保持同一主体的身体比例、空间方向、动作承接和光影连续。",
                "- 服装、产品或场景状态只在对应分段边界与转场中变化，不提前出现后一阶段状态。",
            ]
        )
    consistency_lines.append("- 画面不增加未指定人物、产品、道具、字幕、文字或水印。")

    sections = [token_line, "【最终画面】\n" + "\n".join(_unique(final_state_lines))]
    sections.extend(phase_lines)
    if motion_lines:
        sections.append("【动作与镜头】\n" + "\n".join(motion_lines))
    if transition_lines:
        sections.append("【转场】\n" + "\n".join(transition_lines))
    sections.append("【一致性】\n" + "\n".join(_unique(consistency_lines)))

    prompt = "\n\n".join(section for section in sections if section).strip()[:8000]
    mentions = [
        VideoPromptMention(**reference.model_dump(mode="python"))
        for reference in ordered
        if _token(reference) in prompt
    ]
    negatives = list(
        dict.fromkeys(
            [
                *intent.negative_constraints,
                "非意图要求的人物身份漂移",
                "非意图要求的服装、产品或场景串用",
                "非意图要求的额外人物、文字或水印",
                "动作顺序错乱或转场前后状态提前泄露",
            ]
        )
    )[:40]
    return prompt, mentions, negatives
