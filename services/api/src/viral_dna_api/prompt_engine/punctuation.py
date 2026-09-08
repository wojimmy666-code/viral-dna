"""Conservative current-prompt projection; never touch immutable generation history."""

import re

# URLs and reference labels are identifiers, not prose. Conservatively keep
# reference clauses intact (labels may contain spaces and full stops).
_PROTECTED = re.compile(r"(?:https?://[^\s<>]+|@[^\r\n，,；;！？!?【】]+)")


def normalize_prompt_punctuation(value: str | None) -> str:
    text = str(value or "")
    parts, cursor = [], 0
    for match in _PROTECTED.finditer(text):
        parts.extend((re.sub(r"。{2,}", "。", text[cursor : match.start()]), match.group()))
        cursor = match.end()
    parts.append(re.sub(r"。{2,}", "。", text[cursor:]))
    return "".join(parts)
