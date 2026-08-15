from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    filename: str
    url: str
    sha256: str
    size_bytes: int


ARTIFACTS = (
    ModelArtifact(
        filename="yolox_l.onnx",
        url="https://huggingface.co/yzd-v/DWPose/resolve/main/yolox_l.onnx",
        sha256="7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411",
        size_bytes=216_746_733,
    ),
    ModelArtifact(
        filename="dw-ll_ucoco_384.onnx",
        url="https://huggingface.co/yzd-v/DWPose/resolve/main/dw-ll_ucoco_384.onnx",
        sha256="724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843",
        size_bytes=134_399_116,
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_model_root() -> Path:
    configured = os.getenv("VIRAL_DNA_DWPOSE_MODEL_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local_data = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local_data) if local_data else Path.home() / ".cache"
    return (base / "ViralDNA" / "models" / "dwpose" / "official-onnx-v1").resolve()


class DWPoseModelManager:
    """Versioned, checksum-pinned local model installation boundary."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_model_root()).resolve()
        self._validated_signature: tuple[tuple[str, int, int], ...] | None = None
        self._validated = False

    @property
    def detector_path(self) -> Path:
        return self.root / "yolox_l.onnx"

    @property
    def pose_path(self) -> Path:
        return self.root / "dw-ll_ucoco_384.onnx"

    def _signature(self) -> tuple[tuple[str, int, int], ...]:
        signature: list[tuple[str, int, int]] = []
        for artifact in ARTIFACTS:
            path = self.root / artifact.filename
            try:
                stat = path.stat()
                signature.append((artifact.filename, stat.st_size, stat.st_mtime_ns))
            except OSError:
                signature.append((artifact.filename, -1, -1))
        return tuple(signature)

    def validate(self, *, verify_hash: bool = True) -> tuple[bool, str]:
        signature = self._signature()
        if signature == self._validated_signature and self._validated:
            return True, "DWPose WholeBody 模型已通过完整性校验"
        for artifact in ARTIFACTS:
            path = self.root / artifact.filename
            if not path.is_file():
                return False, f"缺少 {artifact.filename}；请安装 DWPose WholeBody 模型"
            try:
                size = path.stat().st_size
            except OSError:
                return False, f"无法读取 {artifact.filename}"
            if size != artifact.size_bytes:
                return False, f"{artifact.filename} 文件大小不正确，请重新安装"
            if verify_hash and _sha256(path) != artifact.sha256:
                return False, f"{artifact.filename} 校验失败，请重新安装"
        self._validated_signature = signature
        self._validated = True
        return True, "DWPose WholeBody 模型已通过完整性校验"

    def install(
        self,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """Download pinned official artifacts atomically; never trust partial files."""

        self.root.mkdir(parents=True, exist_ok=True)
        total_bytes = sum(item.size_bytes for item in ARTIFACTS)
        downloaded_bytes = 0
        if progress is not None:
            progress(0, total_bytes, "准备下载 DWPose WholeBody 模型")
        with tempfile.TemporaryDirectory(prefix="viraldna-dwpose-install-") as temp:
            temp_root = Path(temp)
            staged: list[tuple[Path, Path]] = []
            for artifact in ARTIFACTS:
                pending = temp_root / artifact.filename
                request = urllib.request.Request(
                    artifact.url,
                    headers={"User-Agent": "ViralDNA/1.0 DWPose model installer"},
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    with pending.open("wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                            downloaded_bytes += len(chunk)
                            if progress is not None:
                                progress(
                                    min(downloaded_bytes, total_bytes),
                                    total_bytes,
                                    f"正在下载 {artifact.filename}",
                                )
                if pending.stat().st_size != artifact.size_bytes:
                    raise RuntimeError(f"{artifact.filename} 下载不完整")
                if _sha256(pending) != artifact.sha256:
                    raise RuntimeError(f"{artifact.filename} SHA-256 校验失败")
                staged.append((pending, self.root / artifact.filename))
            for source, destination in staged:
                os.replace(source, destination)
        self._validated_signature = None
        self._validated = False
        valid, note = self.validate()
        if not valid:
            raise RuntimeError(note)
        if progress is not None:
            progress(total_bytes, total_bytes, "模型下载与完整性校验完成")
