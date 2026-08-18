from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypeVar, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from . import __version__
from .chinese import to_simplified
from .runtime_config import get_config_value, local_env_path
from .schema import WORKSPACE_SCHEMA_VERSION
from .workspace import WorkspaceError, WorkspaceManager, WorkspacePaths

ACCOUNT_CATALOG_SCHEMA_VERSION = 1
ModelT = TypeVar("ModelT", bound=BaseModel)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clone_model(model: ModelT) -> ModelT:
    return cast(ModelT, type(model).model_validate(model.model_dump(mode="json")))


class AccountCatalogError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class WorkspaceCatalogMode(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


class StoragePolicy(StrEnum):
    LOCAL_ONLY = "local_only"
    CLOUD_ONLY = "cloud_only"
    LOCAL_PREFERRED = "local_preferred"
    CLOUD_PREFERRED = "cloud_preferred"
    MIRRORED = "mirrored"
    ON_DEMAND_CACHE = "on_demand_cache"


class WorkspaceLocatorType(StrEnum):
    LOCAL_DIRECTORY = "local_directory"
    REMOTE_ENDPOINT = "remote_endpoint"


class WorkspaceAvailability(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class StorageProviderType(StrEnum):
    LOCAL_FILESYSTEM = "local_filesystem"
    OSS = "oss"
    COS = "cos"
    S3 = "s3"
    SERVER = "server"


class StorageLocationStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class StorageLocationScope(StrEnum):
    WORKSPACE = "workspace"
    ACCOUNT = "account"


class StorageCapability(StrEnum):
    READ = "read"
    WRITE = "write"
    SIGNED_URL = "signed_url"
    MULTIPART_UPLOAD = "multipart_upload"


class Account(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    display_name: str = Field(default="默认账户", min_length=1, max_length=120)
    status: AccountStatus = AccountStatus.ACTIVE
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    deleted_at: datetime | None = None


class DeviceInstallation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=80)
    app_version: str = Field(min_length=1, max_length=80)
    last_seen_at: datetime = Field(default_factory=_utc_now)
    created_at: datetime = Field(default_factory=_utc_now)


class Workspace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    name: str = Field(min_length=1, max_length=120)
    catalog_mode: WorkspaceCatalogMode = WorkspaceCatalogMode.LOCAL
    default_storage_policy: StoragePolicy = StoragePolicy.LOCAL_ONLY
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    deleted_at: datetime | None = None


class WorkspaceRegistration(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    device_id: UUID
    locator_type: WorkspaceLocatorType = WorkspaceLocatorType.LOCAL_DIRECTORY
    local_root: str = Field(min_length=1, max_length=2048)
    availability: WorkspaceAvailability = WorkspaceAvailability.ONLINE
    last_opened_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class StorageLocation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    account_id: UUID | None = None
    scope: StorageLocationScope = StorageLocationScope.WORKSPACE
    name: str = Field(min_length=1, max_length=120)
    provider_type: StorageProviderType = StorageProviderType.LOCAL_FILESYSTEM
    device_id: UUID | None = None
    status: StorageLocationStatus = StorageLocationStatus.ONLINE
    capabilities: list[StorageCapability] = Field(
        default_factory=lambda: [StorageCapability.READ, StorageCapability.WRITE],
        max_length=8,
    )
    config_reference: str | None = Field(default=None, max_length=500)
    priority: int = Field(default=100, ge=0, le=1000)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(
        cls,
        values: list[StorageCapability],
    ) -> list[StorageCapability]:
        if len(values) != len(set(values)):
            raise ValueError("存储位置能力不能重复")
        return values


class WorkspaceManifest(BaseModel):
    schema_version: int = WORKSPACE_SCHEMA_VERSION
    workspace_id: UUID
    account_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    catalog_mode: WorkspaceCatalogMode = WorkspaceCatalogMode.LOCAL
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class WorkspaceListItem(BaseModel):
    workspace: Workspace
    registration: WorkspaceRegistration | None = None
    storage_locations: list[StorageLocation] = Field(default_factory=list)
    active: bool = False


class AccountContextResponse(BaseModel):
    account: Account
    device: DeviceInstallation
    active_workspace: Workspace
    registration: WorkspaceRegistration
    storage_locations: list[StorageLocation] = Field(default_factory=list)


class WorkspaceLocalRegisterRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class ActiveWorkspaceRequest(BaseModel):
    workspace_id: UUID


class AccountCatalogState(BaseModel):
    schema_version: int = ACCOUNT_CATALOG_SCHEMA_VERSION
    accounts: list[Account] = Field(default_factory=list)
    devices: list[DeviceInstallation] = Field(default_factory=list)
    workspaces: list[Workspace] = Field(default_factory=list)
    registrations: list[WorkspaceRegistration] = Field(default_factory=list)
    storage_locations: list[StorageLocation] = Field(default_factory=list)
    active_account_id: UUID | None = None
    active_device_id: UUID | None = None
    active_workspace_id: UUID | None = None
    updated_at: datetime = Field(default_factory=_utc_now)


class AccountCatalogRepository(Protocol):
    async def load(self) -> AccountCatalogState: ...

    async def save(self, state: AccountCatalogState) -> None: ...


class WorkspaceSwitcher(Protocol):
    async def switch_workspace(self, path: str) -> None: ...


class InMemoryAccountCatalogRepository:
    def __init__(self) -> None:
        self._state = AccountCatalogState()
        self._lock = asyncio.Lock()

    async def load(self) -> AccountCatalogState:
        async with self._lock:
            return _clone_model(self._state)

    async def save(self, state: AccountCatalogState) -> None:
        async with self._lock:
            self._state = _clone_model(state)


class LocalAccountCatalogRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = asyncio.Lock()

    async def load(self) -> AccountCatalogState:
        async with self._lock:
            return await asyncio.to_thread(self._read)

    async def save(self, state: AccountCatalogState) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write, state)

    def _read(self) -> AccountCatalogState:
        if not self.path.is_file():
            return AccountCatalogState()
        try:
            payload = json.loads(self.path.read_text("utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AccountCatalogError("无法读取本机账户目录") from exc
        if not isinstance(payload, dict):
            raise AccountCatalogError("本机账户目录格式无效")
        try:
            schema_version = int(payload.get("schema_version") or 1)
        except (TypeError, ValueError) as exc:
            raise AccountCatalogError("本机账户目录版本无效") from exc
        if schema_version > ACCOUNT_CATALOG_SCHEMA_VERSION:
            raise AccountCatalogError(
                f"账户目录版本 {schema_version} 高于当前支持版本 {ACCOUNT_CATALOG_SCHEMA_VERSION}"
            )
        try:
            return AccountCatalogState.model_validate(payload)
        except ValueError as exc:
            raise AccountCatalogError("本机账户目录内容无效") from exc

    def _write(self, state: AccountCatalogState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            temporary_path = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(
                    json.dumps(
                        state.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            if os.name != "nt":
                self.path.chmod(0o600)
        except OSError as exc:
            raise AccountCatalogError("无法保存本机账户目录") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def default_account_catalog_path() -> Path:
    configured = get_config_value("VIRAL_DNA_ACCOUNT_CATALOG_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()
    app_data = os.getenv("LOCALAPPDATA", "").strip() or os.getenv("APPDATA", "").strip()
    if app_data:
        return (Path(app_data) / "ViralDNA" / "account-catalog.json").resolve()
    return (local_env_path().parent / ".viraldna" / "account-catalog.json").resolve()


def create_account_catalog_repository() -> AccountCatalogRepository:
    if os.getenv("VIRAL_DNA_STORE", "sqlite").lower() == "memory":
        return InMemoryAccountCatalogRepository()
    return LocalAccountCatalogRepository(default_account_catalog_path())


def _replace_by_id(items: list[ModelT], updated: ModelT) -> None:
    for index, item in enumerate(items):
        if getattr(item, "id", None) == getattr(updated, "id", None):
            items[index] = updated
            return
    items.append(updated)


class AccountContextService:
    def __init__(
        self,
        repository: AccountCatalogRepository,
        workspace_manager: WorkspaceManager,
    ) -> None:
        self.repository = repository
        self.workspace_manager = workspace_manager
        self._lock = asyncio.Lock()

    async def ensure_current(self) -> AccountContextResponse:
        try:
            paths = self.workspace_manager.initialize(self.workspace_manager.root)
        except WorkspaceError as exc:
            raise AccountCatalogError(str(exc), status_code=422) from exc
        registered = await self._register_paths(paths, make_active=True, touch_opened=True)
        return AccountContextResponse(
            account=registered[0],
            device=registered[1],
            active_workspace=registered[2],
            registration=registered[3],
            storage_locations=[registered[4]],
        )

    async def current_account(self) -> Account:
        return (await self.ensure_current()).account

    async def list_workspaces(self) -> list[WorkspaceListItem]:
        context = await self.ensure_current()
        state = await self.repository.load()
        items: list[WorkspaceListItem] = []
        for workspace in sorted(
            (
                item
                for item in state.workspaces
                if item.account_id == context.account.id and item.deleted_at is None
            ),
            key=lambda item: (item.name.casefold(), str(item.id)),
        ):
            registration = next(
                (
                    item
                    for item in state.registrations
                    if item.workspace_id == workspace.id
                    and item.device_id == context.device.id
                    and item.locator_type == WorkspaceLocatorType.LOCAL_DIRECTORY
                ),
                None,
            )
            locations = [
                item for item in state.storage_locations if item.workspace_id == workspace.id
            ]
            items.append(
                WorkspaceListItem(
                    workspace=workspace,
                    registration=registration,
                    storage_locations=locations,
                    active=state.active_workspace_id == workspace.id,
                )
            )
        return items

    async def register_local(
        self,
        raw_path: str,
        *,
        name: str | None = None,
    ) -> WorkspaceListItem:
        validation = self.workspace_manager.validate(raw_path)
        if not validation.valid:
            raise AccountCatalogError(
                validation.error or "工作区不可用",
                status_code=422,
            )
        try:
            paths = self.workspace_manager.initialize(Path(validation.normalized_path))
        except WorkspaceError as exc:
            raise AccountCatalogError(str(exc), status_code=422) from exc
        account, device, workspace, registration, location = await self._register_paths(
            paths,
            name=name,
            make_active=False,
            touch_opened=False,
        )
        state = await self.repository.load()
        return WorkspaceListItem(
            workspace=workspace,
            registration=registration,
            storage_locations=[location],
            active=state.active_workspace_id == workspace.id,
        )

    async def activate_local_path(
        self,
        raw_path: str,
        switcher: WorkspaceSwitcher,
    ) -> AccountContextResponse:
        item = await self.register_local(raw_path)
        return await self._activate_registered(item.workspace.id, switcher)

    async def activate_workspace(
        self,
        workspace_id: UUID,
        switcher: WorkspaceSwitcher,
    ) -> AccountContextResponse:
        await self.ensure_current()
        return await self._activate_registered(workspace_id, switcher)

    async def list_storage_locations(self, workspace_id: UUID) -> list[StorageLocation]:
        context = await self.ensure_current()
        state = await self.repository.load()
        workspace = next(
            (
                item
                for item in state.workspaces
                if item.id == workspace_id
                and item.account_id == context.account.id
                and item.deleted_at is None
            ),
            None,
        )
        if workspace is None:
            raise AccountCatalogError("找不到工作区", status_code=404)
        return [item for item in state.storage_locations if item.workspace_id == workspace_id]

    async def _activate_registered(
        self,
        workspace_id: UUID,
        switcher: WorkspaceSwitcher,
    ) -> AccountContextResponse:
        state = await self.repository.load()
        account = self._active_account(state)
        device = self._active_device(state, account.id)
        workspace = next(
            (
                item
                for item in state.workspaces
                if item.id == workspace_id
                and item.account_id == account.id
                and item.deleted_at is None
            ),
            None,
        )
        if workspace is None:
            raise AccountCatalogError("找不到工作区", status_code=404)
        registration = next(
            (
                item
                for item in state.registrations
                if item.workspace_id == workspace_id
                and item.device_id == device.id
                and item.locator_type == WorkspaceLocatorType.LOCAL_DIRECTORY
            ),
            None,
        )
        if registration is None:
            raise AccountCatalogError("当前设备没有该工作区的本地登记", status_code=409)
        local_root = Path(registration.local_root)
        if not await asyncio.to_thread(local_root.is_dir):
            await self._mark_registration_unavailable(registration.id)
            raise AccountCatalogError("该工作区在当前设备上不可用", status_code=409)
        try:
            await switcher.switch_workspace(str(local_root))
        except WorkspaceError as exc:
            status_code = 409 if "正在运行" in str(exc) else 422
            raise AccountCatalogError(str(exc), status_code=status_code) from exc
        account, device, workspace, registration, location = await self._register_paths(
            self.workspace_manager.paths,
            name=workspace.name,
            make_active=True,
            touch_opened=True,
        )
        return AccountContextResponse(
            account=account,
            device=device,
            active_workspace=workspace,
            registration=registration,
            storage_locations=[location],
        )

    async def _register_paths(
        self,
        paths: WorkspacePaths,
        *,
        name: str | None = None,
        make_active: bool,
        touch_opened: bool,
    ) -> tuple[
        Account,
        DeviceInstallation,
        Workspace,
        WorkspaceRegistration,
        StorageLocation,
    ]:
        async with self._lock:
            state = await self.repository.load()
            preliminary = WorkspaceManifest.model_validate(
                self.workspace_manager.ensure_identity(paths=paths)
            )
            source_name = name or preliminary.name or paths.root.name or "ViralDNA 工作区"
            normalized_name = " ".join(to_simplified(source_name).split()).strip()
            normalized_name = normalized_name or "ViralDNA 工作区"

            account = self._ensure_account(state, preferred_id=preliminary.account_id)
            manifest = WorkspaceManifest.model_validate(
                self.workspace_manager.ensure_identity(
                    paths=paths,
                    account_id=account.id,
                    name=normalized_name,
                )
            )
            device = self._ensure_device(state, account.id)
            now = _utc_now()

            workspace = next(
                (item for item in state.workspaces if item.id == manifest.workspace_id),
                None,
            )
            workspace_name = " ".join(
                to_simplified(normalized_name or manifest.name or paths.root.name).split()
            ).strip()
            if workspace is None:
                workspace = Workspace(
                    id=manifest.workspace_id,
                    account_id=account.id,
                    name=workspace_name,
                    catalog_mode=manifest.catalog_mode,
                    created_at=manifest.created_at,
                    updated_at=now,
                )
            elif workspace.account_id != account.id:
                raise AccountCatalogError("工作区属于另一个账户", status_code=409)
            else:
                workspace = workspace.model_copy(
                    update={
                        "name": workspace_name,
                        "catalog_mode": manifest.catalog_mode,
                        "updated_at": now,
                    }
                )
            _replace_by_id(state.workspaces, workspace)

            normalized_root = str(paths.root.resolve())
            registration = next(
                (
                    item
                    for item in state.registrations
                    if item.workspace_id == workspace.id
                    and item.device_id == device.id
                    and item.locator_type == WorkspaceLocatorType.LOCAL_DIRECTORY
                ),
                None,
            )
            if registration is None:
                registration = WorkspaceRegistration(
                    workspace_id=workspace.id,
                    device_id=device.id,
                    local_root=normalized_root,
                    last_opened_at=now if touch_opened else None,
                )
            else:
                registration = registration.model_copy(
                    update={
                        "local_root": normalized_root,
                        "availability": WorkspaceAvailability.ONLINE,
                        "last_opened_at": now if touch_opened else registration.last_opened_at,
                        "updated_at": now,
                    }
                )
            _replace_by_id(state.registrations, registration)

            location = next(
                (
                    item
                    for item in state.storage_locations
                    if item.workspace_id == workspace.id
                    and item.device_id == device.id
                    and item.provider_type == StorageProviderType.LOCAL_FILESYSTEM
                ),
                None,
            )
            if location is None:
                location = StorageLocation(
                    workspace_id=workspace.id,
                    account_id=account.id,
                    name=f"{device.name} 本地存储",
                    device_id=device.id,
                    config_reference=f"workspace-registration:{registration.id}",
                )
            else:
                location = location.model_copy(
                    update={
                        "account_id": location.account_id or account.id,
                        "scope": StorageLocationScope.WORKSPACE,
                        "status": StorageLocationStatus.ONLINE,
                        "config_reference": f"workspace-registration:{registration.id}",
                        "updated_at": now,
                    }
                )
            _replace_by_id(state.storage_locations, location)

            if make_active:
                state.active_account_id = account.id
                state.active_device_id = device.id
                state.active_workspace_id = workspace.id
            state.updated_at = now
            await self.repository.save(state)
            return account, device, workspace, registration, location

    @staticmethod
    def _ensure_account(
        state: AccountCatalogState,
        *,
        preferred_id: UUID | None,
    ) -> Account:
        account = None
        if state.active_account_id is not None:
            account = next(
                (
                    item
                    for item in state.accounts
                    if item.id == state.active_account_id and item.deleted_at is None
                ),
                None,
            )
        if account is None and preferred_id is not None:
            account = next(
                (
                    item
                    for item in state.accounts
                    if item.id == preferred_id and item.deleted_at is None
                ),
                None,
            )
        if account is None:
            account = next(
                (item for item in state.accounts if item.deleted_at is None),
                None,
            )
        if account is None:
            account = Account(id=preferred_id or uuid4())
            state.accounts.append(account)
        elif preferred_id is not None and preferred_id != account.id:
            raise AccountCatalogError("工作区属于另一个账户", status_code=409)
        state.active_account_id = account.id
        return account

    @staticmethod
    def _ensure_device(
        state: AccountCatalogState,
        account_id: UUID,
    ) -> DeviceInstallation:
        device = None
        if state.active_device_id is not None:
            device = next(
                (
                    item
                    for item in state.devices
                    if item.id == state.active_device_id and item.account_id == account_id
                ),
                None,
            )
        if device is None:
            device = next(
                (item for item in state.devices if item.account_id == account_id),
                None,
            )
        now = _utc_now()
        if device is None:
            device = DeviceInstallation(
                account_id=account_id,
                name=(socket.gethostname().strip() or "当前设备")[:120],
                platform=(platform.system().strip() or os.name)[:80],
                app_version=__version__,
                last_seen_at=now,
            )
        else:
            device = device.model_copy(update={"last_seen_at": now, "app_version": __version__})
        _replace_by_id(state.devices, device)
        state.active_device_id = device.id
        return device

    @staticmethod
    def _active_account(state: AccountCatalogState) -> Account:
        account = next(
            (
                item
                for item in state.accounts
                if item.id == state.active_account_id and item.deleted_at is None
            ),
            None,
        )
        if account is None:
            raise AccountCatalogError("当前账户尚未初始化")
        return account

    @staticmethod
    def _active_device(
        state: AccountCatalogState,
        account_id: UUID,
    ) -> DeviceInstallation:
        device = next(
            (
                item
                for item in state.devices
                if item.id == state.active_device_id and item.account_id == account_id
            ),
            None,
        )
        if device is None:
            raise AccountCatalogError("当前设备尚未初始化")
        return device

    async def _mark_registration_unavailable(self, registration_id: UUID) -> None:
        async with self._lock:
            state = await self.repository.load()
            registration = next(
                (item for item in state.registrations if item.id == registration_id),
                None,
            )
            if registration is None:
                return
            updated = registration.model_copy(
                update={
                    "availability": WorkspaceAvailability.OFFLINE,
                    "updated_at": _utc_now(),
                }
            )
            _replace_by_id(state.registrations, updated)
            state.updated_at = _utc_now()
            await self.repository.save(state)


def create_account_context_service(
    workspace_manager: WorkspaceManager,
) -> AccountContextService:
    return AccountContextService(create_account_catalog_repository(), workspace_manager)
