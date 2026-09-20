"""Bounded structural diagnostics; never serialize validation inputs or model text."""

import hashlib
import json
import re

from pydantic import BaseModel, ValidationError

from ..models import ModelResponseDiagnostics, ModelResponseIssue


def response_diagnostics(
    error: Exception, schema: type[BaseModel], content: str, finish_reason: object = None
) -> ModelResponseDiagnostics:
    fields: set[str] = set()

    def collect_fields(node):
        if isinstance(node, dict):
            fields.update(node.get("properties", {}))
            for child in node.values():
                collect_fields(child)
        elif isinstance(node, list):
            for child in node:
                collect_fields(child)

    collect_fields(schema.model_json_schema())

    def safe_path(location):
        path = ""
        for part in location:
            if isinstance(part, int):
                path += f"[{part}]"
            else:
                # Dictionary keys can be supplied by a model. Only allow schema field names.
                name = part if isinstance(part, str) and part in fields else "field"
                path += ("." if path else "") + name
        return path[:200] or "response"

    diagnostics = ModelResponseDiagnostics(
        stage="response_envelope",
        response_sha256=hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest(),
        response_chars=len(content),
        finish_reason=(
            finish_reason
            if isinstance(finish_reason, str)
            and finish_reason in {"stop", "length", "content_filter", "tool_calls"}
            else ("other" if finish_reason is not None else None)
        ),
    )
    if isinstance(error, ValidationError):
        diagnostics.stage = "schema_validation"
        for issue in error.errors(include_input=False, include_context=False, include_url=False)[
            :12
        ]:
            code = issue["type"]
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
                code = "validation_error"
            diagnostics.issues.append(ModelResponseIssue(path=safe_path(issue["loc"]), code=code))
        # Only numeric bounds are useful here; messages/ctx can contain user text or secrets.
        for output, issue in zip(
            diagnostics.issues, error.errors(include_input=False), strict=False
        ):
            context = issue.get("ctx") or {}
            limit = context.get("max_length", context.get("min_length"))
            if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
                output.limit = limit
    elif isinstance(error, json.JSONDecodeError):
        diagnostics.stage = "json_parse"
        diagnostics.json_line = error.lineno
        diagnostics.json_column = error.colno
        diagnostics.issues = [ModelResponseIssue(path="response", code="json_invalid")]
    else:
        diagnostics.issues = [ModelResponseIssue(path="response", code="response_shape_invalid")]
    return diagnostics
