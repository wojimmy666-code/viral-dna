from __future__ import annotations

from ..base_compiler import render_prompt
from ..contracts import PromptShotDraft


def compile_seedance_prompt(draft: PromptShotDraft) -> str:
    """Seedance benefits from explicit, line-broken temporal instructions."""

    return render_prompt(draft, compact_timeline=False)
