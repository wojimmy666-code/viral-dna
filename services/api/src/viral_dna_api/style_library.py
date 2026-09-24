"""Platform-owned, versioned style prompts. Preview covers never become model inputs."""
from __future__ import annotations

import io
import json
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .access_context import account_access
from .visual_styles import BOUNDARY, PRESETS
from .workspace_catalog import default_account_catalog_path


class StyleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=60)
    category: str = Field(min_length=1, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=12)
    description: str = Field(default="", max_length=400)
    cover_id: UUID | None = None
    sample_ids: list[UUID] = Field(default_factory=list, max_length=4)
    applies_to: list[Literal["image", "video"]] = Field(default_factory=lambda: ["image", "video"], min_length=1, max_length=2)
    image_prompt: str = Field(default="", max_length=6000)
    video_prompt: str = Field(default="", max_length=6000)
    image_negative: str = Field(default="", max_length=2000)
    video_negative: str = Field(default="", max_length=2000)
    sort_order: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def validate_rules(self):
        if len(set(self.applies_to)) != len(self.applies_to):
            raise ValueError("适用类型不能重复")
        if any(not tag.strip() or len(tag) > 30 for tag in self.tags):
            raise ValueError("标签不能为空，且不能超过 30 字")
        for part in self.applies_to:
            if not getattr(self, f"{part}_prompt"):
                raise ValueError("请填写适用类型的风格提示词")
        return self


class StyleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    style: StyleDefinition


class StyleAction(BaseModel):
    expected_revision: int = Field(ge=1)


class FavoriteUpdate(BaseModel):
    favorite: bool


class StyleLibrary:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS styles (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, draft TEXT NOT NULL,
                    published_version INTEGER, enabled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS style_versions (
                    style_id TEXT, version INTEGER, payload TEXT NOT NULL,
                    PRIMARY KEY (style_id, version));
                CREATE TABLE IF NOT EXISTS style_media (id TEXT PRIMARY KEY, content BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS style_preferences (
                    principal TEXT, style_id TEXT, favorite INTEGER DEFAULT 0, used_at TEXT,
                    PRIMARY KEY (principal, style_id));
            """)
            # executescript commits its own schema transaction. Seed atomically too.
            db.execute("BEGIN IMMEDIATE")
            for index, (key, (name, description, image_rules, video)) in enumerate(PRESETS.items()):
                if key in {"original", "custom"}:
                    continue
                identifier = str(uuid5(NAMESPACE_URL, f"viraldna:style:{key}"))
                existing = db.execute("SELECT * FROM styles WHERE id=?", (identifier,)).fetchone()
                needs_seed_cover = existing and existing["revision"] == 1 and existing["published_version"] == 1 and not json.loads(existing["draft"]).get("cover_id")
                if existing and not needs_seed_cover:
                    continue
                preview = Path(__file__).with_name("style_previews") / f"{key}.png"
                cover_id = str(uuid5(NAMESPACE_URL, f"viraldna:style-cover:{key}:1")) if preview.is_file() else None
                if cover_id:
                    with Image.open(preview) as image:
                        image = image.convert("RGB")
                        image.thumbnail((960, 1200))
                        buffer = io.BytesIO()
                        image.save(buffer, format="JPEG", quality=88)
                    db.execute("INSERT OR IGNORE INTO style_media VALUES (?, ?)", (cover_id, buffer.getvalue()))
                style = StyleDefinition(name=name, category="写实摄影" if key in {"natural", "cinematic", "studio", "travel_vlog"} else "动漫与艺术",
                                        tags=["旅行", "Vlog", "日常随拍", "纪实"] if key == "travel_vlog" else [],
                                        description=description, image_prompt=image_rules, cover_id=cover_id,
                                        video_prompt=f"{image_rules}\n{video}", sort_order=index * 10)
                encoded = style.model_dump_json()
                if existing:
                    # Upgrade only untouched pre-cover built-ins; retain immutable v1.
                    old = StyleDefinition.model_validate_json(existing["draft"])
                    if cover_id and old == style.model_copy(update={"cover_id": None}):
                        db.execute("INSERT INTO style_versions VALUES (?, 2, ?)", (identifier, encoded))
                        db.execute("UPDATE styles SET revision=2, draft=?, published_version=2 WHERE id=?", (encoded, identifier))
                    continue
                inserted = db.execute("INSERT OR IGNORE INTO styles VALUES (?, 1, ?, 1, 1)", (identifier, encoded)).rowcount
                if inserted:
                    db.execute("INSERT INTO style_versions VALUES (?, 1, ?)", (identifier, encoded))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _view(row, definition, *, admin=False):
        data = json.loads(definition)
        prefix = "/api/v1/admin/visual-styles/media" if admin else "/api/v1/me/settings/visual-styles/media"
        return {**data, "id": row["id"], "revision": row["revision"],
                "version": row["published_version"], "enabled": bool(row["enabled"]),
                "cover_url": f"{prefix}/{data['cover_id']}" if data.get("cover_id") else None,
                "sample_urls": [f"{prefix}/{item}" for item in data.get("sample_ids", [])],
                "selection": {"catalog_id": row["id"], "catalog_version": row["published_version"]}}

    def catalog(self, *, admin=False, principal=""):
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM styles").fetchall()
            preferences = {row["style_id"]: dict(row) for row in db.execute("SELECT * FROM style_preferences WHERE principal=?", (principal,))}
            items = []
            for row in rows:
                if not admin and (not row["enabled"] or not row["published_version"]):
                    continue
                published = db.execute("SELECT payload FROM style_versions WHERE style_id=? AND version=?", (row["id"], row["published_version"])).fetchone()
                item = self._view(row, row["draft"] if admin else published["payload"], admin=admin)
                item["has_unpublished_changes"] = not published or published["payload"] != row["draft"]
                pref = preferences.get(row["id"], {})
                item.update(favorite=bool(pref.get("favorite")), used_at=pref.get("used_at"))
                items.append(item)
        items.sort(key=lambda item: (item["sort_order"], item["name"]))
        return {"version": "visual-style-library-v1", "items": items}

    def save(self, identifier: str, payload: StyleWrite):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM styles WHERE id=?", (identifier,)).fetchone()
            revision = row["revision"] if row else 0
            if payload.expected_revision != revision:
                raise HTTPException(409, "风格已在其他页面更新，请重新读取后核对")
            style = payload.style
            for media_id in [style.cover_id, *style.sample_ids]:
                if media_id and not db.execute("SELECT 1 FROM style_media WHERE id=?", (str(media_id),)).fetchone():
                    raise HTTPException(422, "预览图片不存在，请重新上传")
            db.execute("""INSERT INTO styles (id, revision, draft) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, draft=excluded.draft""",
                       (identifier, revision + 1, style.model_dump_json()))
        return next(item for item in self.catalog(admin=True)["items"] if item["id"] == identifier)

    def action(self, identifier, revision, action):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM styles WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise HTTPException(404, "风格不存在")
            if revision != row["revision"]:
                raise HTTPException(409, "风格已更新，请重新读取后核对")
            if action == "publish":
                style = StyleDefinition.model_validate_json(row["draft"])
                if not style.cover_id:
                    raise HTTPException(422, "请先上传风格封面，再发布新版本")
                version = (row["published_version"] or 0) + 1
                db.execute("INSERT INTO style_versions VALUES (?, ?, ?)", (identifier, version, row["draft"]))
                db.execute("UPDATE styles SET published_version=?, enabled=1, revision=revision+1 WHERE id=?", (version, identifier))
            else:
                db.execute("UPDATE styles SET enabled=0, revision=revision+1 WHERE id=?", (identifier,))
        return next(item for item in self.catalog(admin=True)["items"] if item["id"] == identifier)

    def frozen(self, identifier, version, *, selectable=False):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM styles WHERE id=?", (identifier,)).fetchone()
            result = db.execute("SELECT payload FROM style_versions WHERE style_id=? AND version=?", (identifier, version)).fetchone()
            if not row or not result:
                raise HTTPException(422, "风格版本不存在，请重新选择")
            if selectable and (not row["enabled"] or row["published_version"] != version):
                raise HTTPException(409, "风格已更新或停用，请重新读取风格库")
        from .prompt_engine.still_image import static_image_text
        style = StyleDefinition.model_validate_json(result["payload"])
        rules = {}
        for part in ("image", "video"):
            text = ""
            if part in style.applies_to:
                text = f"【画面风格：{style.name}】\n{BOUNDARY}\n{getattr(style, f'{part}_prompt')}"
                negative = getattr(style, f"{part}_negative")
                if negative:
                    text += f"\n【风格避免项】{negative}"
                if part == "image":
                    text = static_image_text(text)
            rules[f"{part}_prompt"] = text
        return {"version": "visual-style-library-v1", "selection": {"catalog_id": identifier, "catalog_version": version},
                "label": style.name, "applies_to": style.applies_to,
                "cover_url": f"/api/v1/me/settings/visual-styles/media/{style.cover_id}" if style.cover_id else None, **rules}

    def upload(self, content):
        if not content or len(content) > 10 * 1024 * 1024:
            raise HTTPException(422, "请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片")
        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"} or source.width * source.height > 24_000_000:
                    raise ValueError("unsupported")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1600, 1600))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "无法读取图片，请上传有效的 JPG、PNG 或 WebP") from exc
        identifier = str(uuid4())
        with self.transaction() as db:
            db.execute("INSERT INTO style_media VALUES (?, ?)", (identifier, output.getvalue()))
        return {"id": identifier, "url": f"/api/v1/admin/visual-styles/media/{identifier}"}

    def media(self, identifier, *, admin=False):
        with self.transaction() as db:
            if not admin:
                visible = any(identifier in [data.get("cover_id"), *data.get("sample_ids", [])]
                              for row in db.execute("SELECT payload FROM style_versions") for data in [json.loads(row["payload"])])
                if not visible:
                    raise HTTPException(404, "预览图片不存在")
            row = db.execute("SELECT content FROM style_media WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise HTTPException(404, "预览图片不存在")
        return Response(row["content"], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})

    def preference(self, principal, identifier, *, favorite=None, used=False):
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM styles WHERE id=? AND enabled=1 AND published_version IS NOT NULL", (identifier,)).fetchone():
                raise HTTPException(404, "风格已停用或不存在")
            db.execute("INSERT OR IGNORE INTO style_preferences (principal, style_id) VALUES (?, ?)", (principal, identifier))
            if favorite is not None:
                db.execute("UPDATE style_preferences SET favorite=? WHERE principal=? AND style_id=?", (int(favorite), principal, identifier))
            if used:
                db.execute("UPDATE style_preferences SET used_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE principal=? AND style_id=?", (principal, identifier))
        return {"ok": True}


@lru_cache(maxsize=8)
def _library(path):
    return StyleLibrary(path)


def get_style_library():
    return _library(default_account_catalog_path().with_name("visual-styles.sqlite3"))


def create_style_library_admin_router(require_admin):
    router = APIRouter(prefix="/admin/visual-styles", tags=["visual-styles"], dependencies=[Depends(require_admin)])

    @router.get("")
    def catalog():
        return get_style_library().catalog(admin=True)

    @router.post("")
    def create(payload: StyleWrite):
        if payload.expected_revision != 0:
            raise HTTPException(422, "新风格的初始版本必须为 0")
        return get_style_library().save(str(uuid4()), payload)

    @router.put("/{style_id}")
    def save(style_id: UUID, payload: StyleWrite):
        if payload.expected_revision < 1:
            raise HTTPException(422, "请先读取风格")
        return get_style_library().save(str(style_id), payload)

    @router.post("/{style_id}/{action}")
    def action(style_id: UUID, action: Literal["publish", "disable"], payload: StyleAction):
        return get_style_library().action(str(style_id), payload.expected_revision, action)

    @router.post("/media")
    async def upload(file: UploadFile):
        import asyncio
        try:
            content = await file.read(10 * 1024 * 1024 + 1)
            return await asyncio.to_thread(get_style_library().upload, content)
        finally:
            await file.close()

    @router.get("/media/{media_id}")
    def media(media_id: UUID):
        return get_style_library().media(str(media_id), admin=True)

    return router


def create_style_library_user_router(account_context):
    router = APIRouter(prefix="/me/settings/visual-styles", tags=["visual-styles"])

    async def principal():
        account = await account_context.current_account()
        access = account_access.get()
        return f"{account.id}:{access.user_id if access else account.id}"

    @router.get("/media/{media_id}")
    async def media(media_id: UUID):
        await principal()
        return get_style_library().media(str(media_id))

    @router.put("/{style_id}/favorite")
    async def favorite(style_id: UUID, payload: FavoriteUpdate):
        return get_style_library().preference(await principal(), str(style_id), favorite=payload.favorite)

    @router.post("/{style_id}/used")
    async def used(style_id: UUID):
        return get_style_library().preference(await principal(), str(style_id), used=True)

    return router
