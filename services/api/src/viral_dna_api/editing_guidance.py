"""Keep editing instructions out of generated footage prompts, without losing them."""

import re


def split_editing_guidance(prompt: str) -> tuple[str, str]:
    notes = []

    def capture(match):
        notes.append(match.group(1).strip())
        return ""

    cleaned = re.sub(r"【剪辑落点】([\s\S]*?)(?=【[^】\n]+】|\Z)", capture, prompt)
    # Only remove the exact compiler boilerplate, not arbitrary user prose.
    cleaned = re.sub(r"在指定结束状态形成明确的剪辑落点，方便[^。\n]+。", "", cleaned)
    return cleaned.strip(), "\n\n".join(notes)


def separate_shot_editing_guidance(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    notes = []
    for field in ("video_prompt", "video_prompt_body"):
        if isinstance(result.get(field), str):
            result[field], note = split_editing_guidance(result[field])
            if note and note not in notes:
                notes.append(note)
    if notes:
        existing = result.get("editing_guidance") or ""
        result["editing_guidance"] = "\n\n".join(
            [existing] + [note for note in notes if note not in existing]
        ).strip()
    elif result.get("editing_guidance") is None:
        spec = result.get("creative_spec")
        if hasattr(spec, "model_dump"):
            spec = spec.model_dump()
        transition = (spec or {}).get("transition", {})
        result["editing_guidance"] = "\n\n".join(notes) or "\n".join(
            str(transition[key]) for key in ("cut_out", "continuity_note") if transition.get(key)
        )
    return result
