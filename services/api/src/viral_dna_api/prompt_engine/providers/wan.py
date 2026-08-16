from __future__ import annotations

from ..base_compiler import render_prompt
from ..contracts import PromptShotDraft


def compile_wan_prompt(draft: PromptShotDraft) -> str:
    """Wan keeps explicit sections while provider-specific mapping evolves."""

    return render_prompt(draft, compact_timeline=False)
