"""Language checks for generated execution prompts, not a content translator."""

import re

LANGUAGE_INSTRUCTIONS = """语言规则：所有面向用户的自然语言正文必须使用简体中文，尤其是每个
image_prompt、video_prompt、description 和 negative_constraints；不能只把标题写成中文。
JSON 字段名保持协议规定的英文。允许 JK、AI、HDR、4K 等专业缩写、原始品牌名和必须保留的
英文台词/标识；外文原文须标注为 英文台词：“...” 或 英文标识：“...”。
地名、镜头语言、动作、光线和材质用中文描述，不输出整句英文执行提示词。
返回前逐镜检查图片和视频正文的语言；不要自动生成图片或视频。"""

_HAN = re.compile(r"[\u3400-\u9fff]")
_WORD = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
_VERBATIM = re.compile(
    r'(?:英文)?(?:台词|对白|字幕|标识|画面文字|屏幕文字)\s*[：:]\s*(?:“[^”]*”|"[^"]*"|「[^」]*」)'
)
_REFERENCE = re.compile(r"@(?:\[[^\]\n]+\]|[^\s，。；、]+)")
_TERMS = {
    "jk",
    "ai",
    "hdr",
    "uhd",
    "hd",
    "fps",
    "rgb",
    "cmyk",
    "iso",
    "led",
    "vr",
    "ar",
    "vfx",
    "cgi",
    "cg",
    "3d",
    "2d",
    "pov",
    "mm",
    "cm",
    "k",
}


class CreativePromptLanguageError(ValueError):
    code = "creative_prompt_language_invalid"

    def __init__(self, fields):
        self.fields = fields
        super().__init__(
            "以下提示词未使用中文：" + "、".join(fields[:6]) + "；原结果已保留，可转为中文后继续"
        )


def is_foreign_prose(text):
    text = _REFERENCE.sub("", _VERBATIM.sub("", str(text or "")))
    words = [word for word in _WORD.findall(text) if word.lower() not in _TERMS]
    han = len(_HAN.findall(text))
    if not words:
        return False
    # A short Latin proper name amid Chinese is valid. A Chinese heading does
    # not make a paragraph of English valid. This is a narrow language guard.
    if not han:
        return True
    if len(words) >= 5 and sum(map(len, words)) > han * 2:
        return True
    return any(
        len([w for w in _WORD.findall(part) if w.lower() not in _TERMS]) >= 5
        and len(_HAN.findall(part)) < 3
        for part in re.split(r"[。！？.!?\n]", text)
    )


def prompt_language_issues(concept):
    issues = []
    for shot in concept.shots:
        for field, label in (("image_prompt", "图片"), ("video_prompt", "视频")):
            if is_foreign_prose(getattr(shot, field)):
                issues.append(f"分镜 {shot.index} {label}提示词")
        if any(is_foreign_prose(item) for item in shot.negative_constraints):
            issues.append(f"分镜 {shot.index} 负面约束")
    return issues


def require_chinese_prompts(concept):
    issues = prompt_language_issues(concept)
    if issues:
        raise CreativePromptLanguageError(issues)


def present_language_state(batch):
    issues = [
        issue
        for concept in batch.concepts
        if concept.strategy == "creative"
        for issue in prompt_language_issues(concept)
    ]
    return batch.model_copy(update={"language_issues": issues})
