"""Private yt-dlp worker. Credentials travel over stdin, never command arguments."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from yt_dlp.utils import YoutubeDLError

from .link_ingestion import (
    LinkCollector,
    LinkCredentialSession,
    LinkIngestionError,
    _YtDlpLogger,
)


def download(request: dict[str, Any]) -> dict[str, Any]:
    collector = LinkCollector()
    collector.max_download_bytes = request["max_download_bytes"]
    collector.socket_timeout = request["socket_timeout"]
    collector.retries = request["retries"]
    logger = _YtDlpLogger()
    session = LinkCredentialSession(
        configured=True, strategy="always", source_label="worker",
        cookie_file=Path(request["cookie_file"]) if request.get("cookie_file") else None,
        cookies_from_browser=(
            tuple(request["cookies_from_browser"]) if request.get("cookies_from_browser") else None
        ),
    )
    try:
        try:
            info = collector._download_sync(
                request["source_url"], Path(request["target_dir"]), logger, session,
                use_legacy_cookie=request["use_legacy_cookie"],
                metadata_only=request.get("metadata_only", False),
            )
        except YoutubeDLError as exc:
            raise collector._translate_download_error(exc, logger) from exc
        except OSError as exc:
            raise LinkIngestionError(
                "link_storage_failed", "链接视频无法写入本地存储", retryable=True,
            ) from exc
        # Never return yt-dlp's HTTP headers, Cookie values or full extractor payload.
        keys = (
            "id", "title", "uploader", "creator", "channel", "uploader_id", "duration",
            "webpage_url", "original_url", "filepath", "_filename",
        )
        return {"info": {key: info[key] for key in keys if key in info}}
    except LinkIngestionError as exc:
        return {"error": {"code": exc.code, "message": str(exc), "retryable": exc.retryable}}
    except Exception:
        return {"error": {
            "code": "link_download_failed",
            "message": "无法从平台获取视频，请检查平台登录状态或直接上传视频文件。",
            "retryable": True,
        }}


def main() -> None:
    request = json.loads(sys.stdin.buffer.read())
    with redirect_stdout(sys.stderr):
        response = download(request)
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
