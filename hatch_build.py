from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging import tags


ROOT = Path(__file__).resolve().parent
PLUGIN_NAME = "dfttest2"
DEFAULT_REPOSITORY = "RyougiKukoc/vs-dfttest2-api4"
CUDA_VARIANTS = {"cu121", "cu129"}
SUPPORTED_VARIANTS = {"cpu", *CUDA_VARIANTS}
VARIANT_MARKER = ROOT / ".dfttest2-variant"


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"", "0", "false", "no", "off"})


def _run_text(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    except Exception:
        return ""
    return result.stdout.strip()


def _repository_from_remote(remote: str) -> str | None:
    remote = remote.strip()
    for pattern in (
        r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$",
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    ):
        match = re.match(pattern, remote)
        if match:
            return match.group("repo")
    return None


def _default_repository() -> str:
    override = os.environ.get("DFTTEST2_PREBUILT_REPOSITORY")
    if override:
        return override
    github_repository = os.environ.get("GITHUB_REPOSITORY")
    if github_repository:
        return github_repository
    remote = _run_text(["git", "config", "--get", "remote.origin.url"])
    return _repository_from_remote(remote) or DEFAULT_REPOSITORY


def _variant_from_environment() -> str | None:
    for name in ("DFTTEST2_VARIANT", "DFTTEST2_CUDA_VARIANT", "GITHUB_REF_NAME", "DFTTEST2_PREBUILT_TAG"):
        value = os.environ.get(name)
        if value in SUPPORTED_VARIANTS:
            return value
    return None


def _variant_from_marker() -> str | None:
    """Read the committed selector before consulting mutable tag metadata."""
    try:
        variant = VARIANT_MARKER.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    if variant not in SUPPORTED_VARIANTS:
        raise RuntimeError(
            f"invalid DFTTest2 variant marker {variant!r} in {VARIANT_MARKER}; "
            f"expected one of {sorted(SUPPORTED_VARIANTS)}"
        )
    return variant


def _variant_from_git() -> str | None:
    tags_at_head = _run_text(["git", "tag", "--points-at", "HEAD"])
    matches = [tag for tag in tags_at_head.splitlines() if tag in SUPPORTED_VARIANTS]
    if matches:
        return sorted(matches)[0]
    described = _run_text(["git", "describe", "--tags", "--exact-match"])
    return described if described in SUPPORTED_VARIANTS else None


def _selected_variant() -> str:
    # Pip checks out @cpu/@cu121/@cu129 in detached clones. The committed
    # marker keeps their asset identity independent of tag discovery details.
    return _variant_from_environment() or _variant_from_marker() or _variant_from_git() or "cu121"


def _native_suffix() -> str:
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def _asset_platform_suffix() -> str | None:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "win64"
    if sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
        return "linux-x86_64"
    return None


def _default_asset_name(variant: str) -> str:
    platform_suffix = _asset_platform_suffix()
    if platform_suffix is None:
        raise RuntimeError(f"no DFTTest2 Release payload exists for {sys.platform}/{platform.machine()}")
    return f"{PLUGIN_NAME}-{variant}-{platform_suffix}.zip"


def _default_prebuilt_url(variant: str) -> str:
    repository = _default_repository()
    tag = os.environ.get("DFTTEST2_PREBUILT_TAG") or variant
    asset = os.environ.get("DFTTEST2_PREBUILT_ASSET_NAME") or _default_asset_name(variant)
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(variant: str) -> tuple[str, bool]:
    explicit = os.environ.get("DFTTEST2_PREBUILT_URL")
    if explicit:
        return explicit, True
    return _default_prebuilt_url(variant), False


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        shutil.copy2(candidate, destination)
        return
    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-dfttest2-build-hook"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _runtime_patterns() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("cufft64_*.dll", "cudart64_*.dll")
    if sys.platform.startswith("linux"):
        return ("libcufft.so.*", "libcudart.so.*")
    return ()


def _stage_package_from_zip(archive_path: Path, target_dir: Path, variant: str) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        package_members = [
            name for name in zf.namelist()
            if name.replace("\\", "/").startswith(f"{PLUGIN_NAME}/") and not name.endswith("/")
        ]
        if not package_members:
            raise FileNotFoundError(f"prebuilt archive does not contain a {PLUGIN_NAME}/ package directory")
        for member in package_members:
            relative = member.replace("\\", "/").split("/", 1)[1]
            out_path = target_dir / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    suffix = _native_suffix()
    required = [target_dir / "manifest.vs", target_dir / f"dfttest2_cpu{suffix}"]
    if variant in CUDA_VARIANTS:
        required.extend([target_dir / f"dfttest2_cuda{suffix}", target_dir / f"dfttest2_nvrtc{suffix}"])
        for pattern in _runtime_patterns():
            if not list((target_dir / "vsmlrt-cuda").glob(pattern)):
                raise FileNotFoundError(f"prebuilt archive did not provide vsmlrt-cuda/{pattern}")
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"prebuilt archive did not provide {path.name}")

    manifest_text = (target_dir / "manifest.vs").read_text(encoding="ascii", errors="ignore")
    if variant in CUDA_VARIANTS:
        for plugin_name in ("dfttest2_nvrtc", "dfttest2_cuda", "dfttest2_cpu"):
            if plugin_name not in manifest_text:
                raise RuntimeError(f"CUDA prebuilt archive manifest does not list {plugin_name}")
    elif any((target_dir / f"dfttest2_{backend}{suffix}").exists() for backend in ("nvrtc", "cuda")):
        raise RuntimeError("cpu prebuilt archive unexpectedly contains a CUDA plugin")
    elif (target_dir / "vsmlrt-cuda").exists():
        raise RuntimeError("cpu prebuilt archive unexpectedly contains CUDA runtime files")


def _stage_prebuilt_plugin(variant: str, target_dir: Path) -> bool:
    if _truthy(os.environ.get("DFTTEST2_FORCE_BUILD")):
        print("DFTTest2 wheel build: skipping prebuilt asset because DFTTEST2_FORCE_BUILD is set")
        return False
    if _asset_platform_suffix() is None:
        print("DFTTest2 wheel build: no matching platform Release asset; falling back to a native build")
        return False

    source, explicit = _prebuilt_source(variant)
    asset_name = Path(source).name or _default_asset_name(variant)
    try:
        with tempfile.TemporaryDirectory(prefix="dfttest2-prebuilt-") as temp_dir_text:
            archive_path = Path(temp_dir_text) / asset_name
            _fetch_prebuilt_archive(source, archive_path)
            _stage_package_from_zip(archive_path, target_dir, variant)
    except Exception as exc:
        if explicit:
            raise RuntimeError(f"failed to use explicit DFTTest2 prebuilt asset {source!r}") from exc
        print(f"DFTTest2 wheel build: prebuilt asset unavailable at {source}; falling back to local build ({exc})")
        return False

    print(f"DFTTest2 wheel build: using {variant} prebuilt release asset {source}")
    return True


def _run(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def _stage_local_build(variant: str, target_dir: Path) -> None:
    env = os.environ.copy()
    plugins_root = target_dir.parent
    if sys.platform == "win32":
        _run([sys.executable, "tools/ci_prepare_windows.py"], env=env)
        _run(
            [sys.executable, "tools/ci_build_windows.py", "--clean", "--variant", variant,
             "--build-dir", str(ROOT / f"build-wheel-{variant}"), "--dist-dir", str(plugins_root)],
            env=env,
        )
    else:
        _run(
            [sys.executable, "tools/ci_build_native.py", "--clean", "--variant", variant,
             "--build-dir", str(ROOT / f"build-wheel-native-{variant}"), "--dist-dir", str(plugins_root)],
            env=env,
        )

    suffix = _native_suffix()
    required = [target_dir / f"dfttest2_cpu{suffix}"]
    if variant in CUDA_VARIANTS and sys.platform != "darwin":
        required.extend([target_dir / f"dfttest2_cuda{suffix}", target_dir / f"dfttest2_nvrtc{suffix}"])
        for pattern in _runtime_patterns():
            if not list((target_dir / "vsmlrt-cuda").glob(pattern)):
                raise FileNotFoundError(target_dir / "vsmlrt-cuda" / pattern)
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)


class CustomHook(BuildHookInterface[Any]):
    build_dir = ROOT / "build-wheel"
    dist_dir = ROOT / "vapoursynth" / "plugins" / PLUGIN_NAME

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        build_data["pure_python"] = False
        platform_tag = os.environ.get("DFTTEST2_WHEEL_PLATFORM_TAG") or next(tags.platform_tags())
        build_data["tag"] = f"py3-none-{platform_tag}"
        variant = _selected_variant()

        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        if not _stage_prebuilt_plugin(variant, self.dist_dir):
            _stage_local_build(variant, self.dist_dir)

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
