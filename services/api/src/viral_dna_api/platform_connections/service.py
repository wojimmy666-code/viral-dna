from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from yt_dlp import YoutubeDL

from ..link_ingestion import (
    LinkCredentialError,
    LinkCredentialSession,
    identify_platform,
    normalize_platform_url,
)
from ..models import SourceType
from ..runtime_config import get_config_value
from .browser import BrowserCookieError, BrowserProfileDetector
from .cookies import CookieFileError, filter_netscape_cookie_file
from .models import (
    PLATFORM_LABELS,
    BrowserDiscoveryResponse,
    PlatformBrowserConnectionUpdate,
    PlatformConnection,
    PlatformConnectionHealth,
    PlatformConnectionListResponse,
    PlatformConnectionSource,
    PlatformConnectionState,
    PlatformConnectionStrategyUpdate,
    PlatformConnectionSummary,
    PlatformConnectionValidationResponse,
    PlatformKind,
    PlatformUsageStrategy,
    utc_now,
)
from .repository import (
    PlatformConnectionRepository,
    PlatformConnectionRepositoryError,
    create_platform_connection_repository,
)
from .secret_store import (
    PlatformSecretStore,
    PlatformSecretStoreError,
    create_platform_secret_store,
)


class PlatformConnectionServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        retryable: bool = False,
        platform: PlatformKind | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.platform = platform


def normalize_platform(value: PlatformKind | SourceType | str) -> PlatformKind:
    normalized = value.value if hasattr(value, "value") else str(value)
    try:
        return PlatformKind(normalized)
    except ValueError as exc:
        raise PlatformConnectionServiceError(
            "platform_connection_unsupported",
            "当前只支持抖音和小红书平台连接",
            status_code=404,
        ) from exc


class PlatformConnectionService:
    def __init__(
        self,
        account_context_service: Any,
        repository: PlatformConnectionRepository,
        secret_store: PlatformSecretStore,
        browser_detector: BrowserProfileDetector | None = None,
        *,
        legacy_cookie_path: str = "",
    ) -> None:
        self.account_context_service = account_context_service
        self.repository = repository
        self.secret_store = secret_store
        self.browser_detector = browser_detector or BrowserProfileDetector()
        normalized_legacy_path = legacy_cookie_path.strip()
        self.legacy_cookie_path = (
            Path(normalized_legacy_path).expanduser() if normalized_legacy_path else None
        )
        self._lock = asyncio.Lock()
        self._initialized_keys: set[tuple[UUID, UUID]] = set()

    async def initialize(self) -> None:
        context = await self.account_context_service.ensure_current()
        key = (context.account.id, context.device.id)
        if key in self._initialized_keys:
            return
        async with self._lock:
            if key in self._initialized_keys:
                return
            await self._migrate_legacy(context.account.id, context.device.id)
            self._initialized_keys.add(key)

    async def list_connections(self) -> PlatformConnectionListResponse:
        await self.initialize()
        context = await self.account_context_service.ensure_current()
        state = await self._load_state()
        current = {
            item.platform: item
            for item in state.connections
            if item.account_id == context.account.id and item.device_id == context.device.id
        }
        return PlatformConnectionListResponse(
            account_id=context.account.id,
            device_id=context.device.id,
            device_name=context.device.name,
            items=[
                self._summary(platform, current.get(platform))
                for platform in PlatformKind
            ],
        )

    async def discover_browsers(self) -> BrowserDiscoveryResponse:
        return await asyncio.to_thread(self.browser_detector.discover)

    async def configure_browser(
        self,
        platform_value: PlatformKind | str,
        payload: PlatformBrowserConnectionUpdate,
    ) -> PlatformConnectionSummary:
        platform = normalize_platform(platform_value)
        if not payload.consent_confirmed:
            raise PlatformConnectionServiceError(
                "platform_connection_consent_required",
                "请先确认授权 ViralDNA 在本机读取该平台登录状态",
                platform=platform,
            )
        try:
            location = await asyncio.to_thread(
                self.browser_detector.resolve_profile,
                payload.browser,
                payload.profile_key,
            )
            metadata = await asyncio.to_thread(
                self.browser_detector.inspect_cookies,
                payload.browser,
                payload.profile_key,
                platform,
            )
        except BrowserCookieError as exc:
            raise self._from_browser_error(exc, platform) from exc

        context = await self.account_context_service.ensure_current()
        now = utc_now()
        async with self._lock:
            state = await self._load_state()
            existing = self._find(state, context.account.id, context.device.id, platform)
            connection = PlatformConnection(
                id=existing.id if existing else uuid4(),
                account_id=context.account.id,
                device_id=context.device.id,
                platform=platform,
                source=PlatformConnectionSource.BROWSER_PROFILE,
                usage_strategy=payload.usage_strategy,
                browser=payload.browser,
                browser_profile_key=payload.profile_key,
                browser_profile_label=location.label,
                cookie_count=metadata.cookie_count,
                session_cookie_count=metadata.session_cookie_count,
                earliest_expiry_at=metadata.earliest_expiry_at,
                health=PlatformConnectionHealth.READY,
                last_validated_at=now,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._replace(state, connection)
            await self._save_state(state)
        if existing and existing.source == PlatformConnectionSource.NETSCAPE_FILE:
            await self.secret_store.delete(context.account.id, context.device.id, platform)
        return self._summary(platform, connection)

    async def import_cookie_file(
        self,
        platform_value: PlatformKind | str,
        payload: bytes,
        *,
        usage_strategy: PlatformUsageStrategy = PlatformUsageStrategy.ON_AUTH_REQUIRED,
    ) -> PlatformConnectionSummary:
        platform = normalize_platform(platform_value)
        if not self.secret_store.available:
            raise PlatformConnectionServiceError(
                "platform_secret_store_unavailable",
                "当前系统尚不支持安全保存 Cookie 文件",
                status_code=501,
                platform=platform,
            )
        try:
            filtered, metadata = filter_netscape_cookie_file(payload, platform)
        except CookieFileError as exc:
            raise PlatformConnectionServiceError(
                exc.code,
                str(exc),
                platform=platform,
            ) from exc
        context = await self.account_context_service.ensure_current()
        try:
            await self.secret_store.save(
                context.account.id,
                context.device.id,
                platform,
                filtered,
            )
        except PlatformSecretStoreError as exc:
            raise self._from_secret_error(exc, platform) from exc

        now = utc_now()
        async with self._lock:
            state = await self._load_state()
            existing = self._find(state, context.account.id, context.device.id, platform)
            connection = PlatformConnection(
                id=existing.id if existing else uuid4(),
                account_id=context.account.id,
                device_id=context.device.id,
                platform=platform,
                source=PlatformConnectionSource.NETSCAPE_FILE,
                usage_strategy=usage_strategy,
                cookie_count=metadata.cookie_count,
                session_cookie_count=metadata.session_cookie_count,
                earliest_expiry_at=metadata.earliest_expiry_at,
                health=PlatformConnectionHealth.READY,
                last_validated_at=now,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._replace(state, connection)
            await self._save_state(state)
        return self._summary(platform, connection)

    async def update_strategy(
        self,
        platform_value: PlatformKind | str,
        payload: PlatformConnectionStrategyUpdate,
    ) -> PlatformConnectionSummary:
        platform = normalize_platform(platform_value)
        context = await self.account_context_service.ensure_current()
        async with self._lock:
            state = await self._load_state()
            connection = self._find(state, context.account.id, context.device.id, platform)
            if connection is None:
                raise PlatformConnectionServiceError(
                    "platform_connection_missing",
                    "该平台尚未配置登录信息",
                    status_code=404,
                    platform=platform,
                )
            updated = connection.model_copy(
                update={"usage_strategy": payload.usage_strategy, "updated_at": utc_now()}
            )
            self._replace(state, updated)
            await self._save_state(state)
        return self._summary(platform, updated)

    async def validate(
        self,
        platform_value: PlatformKind | str,
        *,
        test_url: str | None = None,
    ) -> PlatformConnectionValidationResponse:
        platform = normalize_platform(platform_value)
        context = await self.account_context_service.ensure_current()
        state = await self._load_state()
        connection = self._find(state, context.account.id, context.device.id, platform)
        if connection is None:
            raise PlatformConnectionServiceError(
                "platform_connection_missing",
                "该平台尚未配置登录信息",
                status_code=404,
                platform=platform,
            )

        try:
            metadata = await self._inspect_connection(connection)
            network_tested = False
            if test_url:
                normalized_test_url = normalize_platform_url(test_url)
                expected = identify_platform(normalized_test_url)
                if expected.value != platform.value:
                    raise PlatformConnectionServiceError(
                        "platform_connection_test_url_mismatch",
                        "测试链接与当前平台不一致",
                        platform=platform,
                    )
                async with self.session_for(platform) as session:
                    await asyncio.to_thread(
                        self._probe_url,
                        normalized_test_url,
                        session,
                    )
                network_tested = True
        except PlatformConnectionServiceError:
            raise
        except (BrowserCookieError, CookieFileError, PlatformSecretStoreError) as exc:
            await self.report_failure(
                platform,
                getattr(exc, "code", "platform_connection_error"),
                str(exc),
            )
            if isinstance(exc, BrowserCookieError):
                raise self._from_browser_error(exc, platform) from exc
            if isinstance(exc, PlatformSecretStoreError):
                raise self._from_secret_error(exc, platform) from exc
            raise PlatformConnectionServiceError(exc.code, str(exc), platform=platform) from exc
        except Exception as exc:
            translated = self._translate_probe_error(exc, platform)
            await self.report_failure(platform, translated.code, str(translated))
            raise translated from exc

        now = utc_now()
        updated = connection.model_copy(
            update={
                "cookie_count": metadata.cookie_count,
                "session_cookie_count": metadata.session_cookie_count,
                "earliest_expiry_at": metadata.earliest_expiry_at,
                "health": (
                    PlatformConnectionHealth.VALID
                    if network_tested
                    else PlatformConnectionHealth.READY
                ),
                "last_validated_at": now,
                "last_success_at": now if network_tested else connection.last_success_at,
                "last_error_code": None,
                "last_error_message": None,
                "updated_at": now,
            }
        )
        async with self._lock:
            current_state = await self._load_state()
            self._replace(current_state, updated)
            await self._save_state(current_state)
        message = (
            "平台链接测试通过，登录状态可用"
            if network_tested
            else "已读取该平台登录信息，实际可用性将在采集时继续验证"
        )
        return PlatformConnectionValidationResponse(
            connection=self._summary(platform, updated),
            message=message,
            network_tested=network_tested,
        )

    async def disconnect(self, platform_value: PlatformKind | str) -> None:
        platform = normalize_platform(platform_value)
        context = await self.account_context_service.ensure_current()
        async with self._lock:
            state = await self._load_state()
            state.connections = [
                item
                for item in state.connections
                if not (
                    item.account_id == context.account.id
                    and item.device_id == context.device.id
                    and item.platform == platform
                )
            ]
            state.updated_at = utc_now()
            await self._save_state(state)
        await self.secret_store.delete(context.account.id, context.device.id, platform)

    @asynccontextmanager
    async def session_for(
        self,
        platform_value: PlatformKind | SourceType | str,
    ) -> AsyncIterator[LinkCredentialSession]:
        platform = normalize_platform(platform_value)
        await self.initialize()
        context = await self.account_context_service.ensure_current()
        state = await self._load_state()
        connection = self._find(state, context.account.id, context.device.id, platform)
        if connection is None or connection.usage_strategy == PlatformUsageStrategy.DISABLED:
            yield LinkCredentialSession(
                configured=False,
                strategy=PlatformUsageStrategy.DISABLED.value,
                source_label="未配置",
            )
            return

        if connection.source == PlatformConnectionSource.BROWSER_PROFILE:
            if not connection.browser or not connection.browser_profile_key:
                raise LinkCredentialError(
                    "platform_browser_profile_missing",
                    "浏览器用户配置不完整，请重新配置",
                )
            try:
                browser_spec = await asyncio.to_thread(
                    self.browser_detector.browser_spec,
                    connection.browser,
                    connection.browser_profile_key,
                )
            except BrowserCookieError as exc:
                raise LinkCredentialError(exc.code, str(exc), retryable=exc.retryable) from exc
            profile_label = connection.browser_profile_label or connection.browser_profile_key
            yield LinkCredentialSession(
                configured=True,
                strategy=connection.usage_strategy.value,
                cookies_from_browser=browser_spec,
                source_label=f"{connection.browser.value} · {profile_label}",
            )
            return

        try:
            encrypted_payload = await self.secret_store.read(
                context.account.id,
                context.device.id,
                platform,
            )
            filtered, _metadata = filter_netscape_cookie_file(encrypted_payload, platform)
        except (PlatformSecretStoreError, CookieFileError) as exc:
            raise LinkCredentialError(
                getattr(exc, "code", "platform_cookie_read_failed"),
                str(exc),
            ) from exc

        materialized = await asyncio.to_thread(self._materialize_cookie, filtered)
        try:
            yield LinkCredentialSession(
                configured=True,
                strategy=connection.usage_strategy.value,
                cookie_file=materialized,
                source_label="本机加密 cookies.txt",
            )
        finally:
            await asyncio.to_thread(materialized.unlink, missing_ok=True)

    async def report_success(self, platform_value: PlatformKind | SourceType | str) -> None:
        platform = normalize_platform(platform_value)
        await self._update_health(platform, success=True)

    async def report_failure(
        self,
        platform_value: PlatformKind | SourceType | str,
        code: str,
        message: str,
    ) -> None:
        platform = normalize_platform(platform_value)
        await self._update_health(platform, success=False, code=code, message=message)

    async def _inspect_connection(self, connection: PlatformConnection):
        if connection.source == PlatformConnectionSource.BROWSER_PROFILE:
            if not connection.browser or not connection.browser_profile_key:
                raise BrowserCookieError(
                    "platform_browser_profile_missing",
                    "浏览器用户配置不完整，请重新配置",
                )
            return await asyncio.to_thread(
                self.browser_detector.inspect_cookies,
                connection.browser,
                connection.browser_profile_key,
                connection.platform,
            )
        payload = await self.secret_store.read(
            connection.account_id,
            connection.device_id,
            connection.platform,
        )
        _filtered, metadata = filter_netscape_cookie_file(payload, connection.platform)
        return metadata

    async def _migrate_legacy(self, account_id: UUID, device_id: UUID) -> None:
        if self.legacy_cookie_path is None or not self.secret_store.available:
            return
        path = self.legacy_cookie_path
        if not await asyncio.to_thread(path.is_file):
            return
        try:
            payload = await asyncio.to_thread(path.read_bytes)
        except OSError:
            return
        state = await self._load_state()
        changed = False
        for platform in PlatformKind:
            if self._find(state, account_id, device_id, platform) is not None:
                continue
            try:
                filtered, metadata = filter_netscape_cookie_file(payload, platform)
                await self.secret_store.save(account_id, device_id, platform, filtered)
            except (CookieFileError, PlatformSecretStoreError):
                continue
            now = utc_now()
            state.connections.append(
                PlatformConnection(
                    account_id=account_id,
                    device_id=device_id,
                    platform=platform,
                    source=PlatformConnectionSource.NETSCAPE_FILE,
                    cookie_count=metadata.cookie_count,
                    session_cookie_count=metadata.session_cookie_count,
                    earliest_expiry_at=metadata.earliest_expiry_at,
                    health=PlatformConnectionHealth.READY,
                    last_validated_at=now,
                    legacy_imported=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True
        if changed:
            state.updated_at = utc_now()
            await self._save_state(state)

    async def _update_health(
        self,
        platform: PlatformKind,
        *,
        success: bool,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        context = await self.account_context_service.ensure_current()
        async with self._lock:
            state = await self._load_state()
            connection = self._find(state, context.account.id, context.device.id, platform)
            if connection is None:
                return
            now = utc_now()
            expired_codes = {
                "link_auth_required",
                "platform_cookie_expired",
                "platform_browser_cookie_missing",
            }
            updated = connection.model_copy(
                update={
                    "health": (
                        PlatformConnectionHealth.VALID
                        if success
                        else PlatformConnectionHealth.EXPIRED
                        if code in expired_codes
                        else PlatformConnectionHealth.ERROR
                    ),
                    "last_success_at": now if success else connection.last_success_at,
                    "last_validated_at": now,
                    "last_error_code": None if success else code,
                    "last_error_message": None if success else (message or "平台连接不可用")[:300],
                    "updated_at": now,
                }
            )
            self._replace(state, updated)
            await self._save_state(state)

    def _summary(
        self,
        platform: PlatformKind,
        connection: PlatformConnection | None,
    ) -> PlatformConnectionSummary:
        if connection is None:
            return PlatformConnectionSummary(
                platform=platform,
                label=PLATFORM_LABELS[platform],
                secure_store_available=self.secret_store.available,
            )
        return PlatformConnectionSummary(
            platform=platform,
            label=PLATFORM_LABELS[platform],
            configured=True,
            source=connection.source,
            usage_strategy=connection.usage_strategy,
            browser=connection.browser,
            browser_profile_key=connection.browser_profile_key,
            browser_profile_label=connection.browser_profile_label,
            cookie_count=connection.cookie_count,
            session_cookie_count=connection.session_cookie_count,
            earliest_expiry_at=connection.earliest_expiry_at,
            health=connection.health,
            last_validated_at=connection.last_validated_at,
            last_success_at=connection.last_success_at,
            last_error_code=connection.last_error_code,
            last_error_message=connection.last_error_message,
            legacy_imported=connection.legacy_imported,
            secure_store_available=self.secret_store.available,
        )

    async def _load_state(self) -> PlatformConnectionState:
        try:
            return await self.repository.load()
        except PlatformConnectionRepositoryError as exc:
            raise PlatformConnectionServiceError(
                "platform_connection_store_read_failed",
                str(exc),
                status_code=500,
            ) from exc

    async def _save_state(self, state: PlatformConnectionState) -> None:
        state.updated_at = utc_now()
        try:
            await self.repository.save(state)
        except PlatformConnectionRepositoryError as exc:
            raise PlatformConnectionServiceError(
                "platform_connection_store_save_failed",
                str(exc),
                status_code=500,
            ) from exc

    @staticmethod
    def _find(
        state: PlatformConnectionState,
        account_id: UUID,
        device_id: UUID,
        platform: PlatformKind,
    ) -> PlatformConnection | None:
        return next(
            (
                item
                for item in state.connections
                if item.account_id == account_id
                and item.device_id == device_id
                and item.platform == platform
            ),
            None,
        )

    @staticmethod
    def _replace(state: PlatformConnectionState, connection: PlatformConnection) -> None:
        for index, existing in enumerate(state.connections):
            if existing.id == connection.id:
                state.connections[index] = connection
                return
        state.connections.append(connection)

    @staticmethod
    def _from_browser_error(
        error: BrowserCookieError,
        platform: PlatformKind,
    ) -> PlatformConnectionServiceError:
        return PlatformConnectionServiceError(
            error.code,
            str(error),
            retryable=error.retryable,
            platform=platform,
        )

    @staticmethod
    def _from_secret_error(
        error: PlatformSecretStoreError,
        platform: PlatformKind,
    ) -> PlatformConnectionServiceError:
        return PlatformConnectionServiceError(
            error.code,
            str(error),
            status_code=500,
            platform=platform,
        )

    @staticmethod
    def _probe_url(url: str, session: LinkCredentialSession) -> None:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "playlist_items": "1",
            "socket_timeout": 20,
            "retries": 1,
        }
        if session.cookie_file is not None:
            options["cookiefile"] = str(session.cookie_file)
        if session.cookies_from_browser is not None:
            options["cookiesfrombrowser"] = session.cookies_from_browser
        with YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=False)

    @staticmethod
    def _materialize_cookie(payload: bytes) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix="viraldna-cookie-", suffix=".txt")
        materialized = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if os.name != "nt":
                materialized.chmod(0o600)
            return materialized
        except Exception:
            materialized.unlink(missing_ok=True)
            raise

    @staticmethod
    def _translate_probe_error(
        error: Exception,
        platform: PlatformKind,
    ) -> PlatformConnectionServiceError:
        details = str(error).lower()
        if any(marker in details for marker in ("login", "cookie", "captcha", "verify")):
            return PlatformConnectionServiceError(
                "platform_connection_auth_required",
                "平台仍要求登录或人机验证，请更新登录状态后重试",
                retryable=True,
                platform=platform,
            )
        if any(marker in details for marker in ("decrypt", "dpapi", "app-bound")):
            return PlatformConnectionServiceError(
                "platform_browser_cookie_decryption_failed",
                "浏览器安全保护阻止了 Cookie 解密，请改用 cookies.txt 导入",
                platform=platform,
            )
        return PlatformConnectionServiceError(
            "platform_connection_test_failed",
            "平台连接测试失败，请确认链接可访问后重试",
            retryable=True,
            platform=platform,
        )


def create_platform_connection_service(account_context_service: Any) -> PlatformConnectionService:
    memory_store = os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory"
    legacy_path = "" if memory_store else get_config_value("VIRAL_DNA_YTDLP_COOKIE_FILE", "")
    return PlatformConnectionService(
        account_context_service,
        create_platform_connection_repository(),
        create_platform_secret_store(),
        legacy_cookie_path=legacy_path,
    )
