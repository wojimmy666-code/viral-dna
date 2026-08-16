from __future__ import annotations

from ..base_compiler import render_prompt
from ..contracts import PromptShotDraft


def compile_minimax_prompt(draft: PromptShotDraft) -> str:
    """MiniMax accepts the same IR with a denser timeline dialect."""

    return render_prompt(draft, compact_timeline=True)
