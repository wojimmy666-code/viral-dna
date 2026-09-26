"""Materialize only versioned platform style inputs, never display covers or caller paths."""
from __future__ import annotations

import hashlib
import os
from uuid import UUID, uuid4

from fastapi import HTTPException

from .image_generation.contracts import ImageReferenceInput
from .reference_purposes import STYLE_REFERENCE_INSTRUCTION
from .style_library import get_style_library


def image_style_reference(workspace, snapshot, part):
    reference = (snapshot or {}).get("reference_image")
    if not reference or part not in snapshot.get("applies_to", []):
        return None
    selection = snapshot.get("selection", {})
    library = get_style_library()
    frozen = library.frozen(selection.get("catalog_id"), selection.get("catalog_version"))
    if frozen.get("reference_image") != reference or part not in frozen.get("applies_to", []):
        raise HTTPException(409, "风格参考图与已冻结版本不符，请重新选择风格")
    content = library.reference_content(reference["id"])
    digest = hashlib.sha256(content).hexdigest()
    if digest != reference["sha256"]:
        raise HTTPException(409, "风格参考图内容已变化，不能继续生成")
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[reference["media_type"]]
    path = workspace.paths.metadata_dir / "style-references" / f"{digest}.{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        temporary = path.with_name(f"{digest}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return ImageReferenceInput(asset_id=UUID(reference["id"]), name=f"{frozen['label']} · 风格参考",
                               role="style", path=path, relative_path=workspace.relative(path),
                               sha256=digest, weight=1, notes=STYLE_REFERENCE_INSTRUCTION)
