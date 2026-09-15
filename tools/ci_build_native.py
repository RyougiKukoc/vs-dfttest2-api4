"""Build a platform-native DFTTest2 package directory for a wheel fallback."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "dfttest2"
CUDA_VARIANTS = {"cu121", "cu129"}
SUPPORTED_VARIANTS = {"cpu", *CUDA_VARIANTS}


def native_suffix() -> str:
    return ".dylib" if sys.platform == "darwin" else ".so"


def run(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def resolve_vapoursynth_root(explicit: str | None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        candidates = (root / "vapoursynth", root)
    else:
        import vapoursynth

        candidates = (Path(vapoursynth.__file__).resolve().parent,)
    for candidate in candidates:
        if (candidate / "include" / "VapourSynth4.h").is_file():
            return candidate
    raise FileNotFoundError("VapourSynth4.h was not found in the supplied SDK or build environment")


def prepend_pkgconfig(env: dict[str, str], vs_root: Path) -> None:
    pkgconfig = vs_root / "pkgconfig"
    if not (pkgconfig / "vapoursynth.pc").is_file():
        raise FileNotFoundError(pkgconfig / "vapoursynth.pc")
    existing = env.get("PKG_CONFIG_PATH")
    env["PKG_CONFIG_PATH"] = str(pkgconfig) if not existing else str(pkgconfig) + os.pathsep + existing


def resolve_cuda_root(explicit: str | None) -> Path:
    candidates = [Path(value) for value in (explicit, os.environ.get("CUDA_PATH"), os.environ.get("CUDA_HOME")) if value]
    candidates.append(Path("/usr/local/cuda"))
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "include" / "nvrtc.h").is_file():
            return root
    raise FileNotFoundError("CUDA toolkit with include/nvrtc.h was not found")


def configure_and_build(build_dir: Path, env: dict[str, str], vs_root: Path, *, cuda: bool, cuda_root: Path | None) -> None:
    configure = [
        "cmake", "-S", str(ROOT), "-B", str(build_dir), "-G", "Ninja",
        "-D", "CMAKE_BUILD_TYPE=Release",
        "-D", f"ENABLE_CPU={'OFF' if cuda else 'ON'}",
        "-D", f"ENABLE_CUDA={'ON' if cuda else 'OFF'}",
        "-D", f"ENABLE_NVRTC={'ON' if cuda else 'OFF'}",
        "-D", "ENABLE_GCC=OFF", "-D", "ENABLE_HIP=OFF",
        "-D", "USE_NVRTC_STATIC=ON",
        "-D", f"VS_INCLUDE_DIR={vs_root / 'include'}",
    ]
    if cuda_root:
        configure.extend(["-D", f"CUDAToolkit_ROOT={cuda_root}"])
    run(configure, env=env)
    run(["cmake", "--build", str(build_dir), "--verbose"], env=env)


def find_output(build_dir: Path, name: str) -> Path:
    matches = sorted(build_dir.rglob(name))
    if not matches:
        raise FileNotFoundError(build_dir / name)
    return matches[0]


def find_cuda_runtime(cuda_root: Path, stem: str) -> Path:
    search_dirs = (cuda_root / "lib64", cuda_root / "lib", cuda_root / "targets" / "x86_64-linux" / "lib")
    for directory in search_dirs:
        candidates = sorted(directory.glob(stem + ".*"))
        if candidates:
            # Prefer the SONAME symlink, then copy its bytes under that name.
            return candidates[0]
    raise FileNotFoundError(cuda_root / "lib64" / (stem + ".*"))


def stage_package(build_dir: Path, package_parent: Path, variant: str, cuda_root: Path | None) -> Path:
    suffix = native_suffix()
    package_dir = package_parent / PLUGIN_NAME
    shutil.rmtree(package_dir, ignore_errors=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(find_output(build_dir / "cpu", "dfttest2_cpu" + suffix), package_dir / ("dfttest2_cpu" + suffix))

    plugin_names = ["dfttest2_cpu"]
    if variant in CUDA_VARIANTS and sys.platform != "darwin":
        if cuda_root is None:
            raise RuntimeError("CUDA root is required for a CUDA package")
        cuda_build = build_dir / "cuda"
        for name in ("dfttest2_nvrtc", "dfttest2_cuda"):
            shutil.copy2(find_output(cuda_build, name + suffix), package_dir / (name + suffix))
        runtime_dir = package_dir / "vsmlrt-cuda"
        runtime_dir.mkdir()
        for stem in ("libcufft.so", "libcudart.so"):
            runtime = find_cuda_runtime(cuda_root, stem)
            shutil.copy2(runtime, runtime_dir / runtime.name)
        plugin_names = ["dfttest2_nvrtc", "dfttest2_cuda", *plugin_names]

    shutil.copy2(ROOT / "LICENSE", package_dir / "LICENSE")
    with (package_dir / "manifest.vs").open("w", encoding="ascii", newline="\n") as manifest:
        manifest.write("[VapourSynth Manifest V1]\n" + "\n".join(plugin_names) + "\n")
    return package_dir


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(SUPPORTED_VARIANTS), default=os.environ.get("DFTTEST2_VARIANT", "cu121"))
    parser.add_argument("--build-dir", default=str(ROOT / "build-native"))
    parser.add_argument("--dist-dir", default=str(ROOT / "dist" / "native"))
    parser.add_argument("--vapoursynth-root", help="Installed/extracted wheel root containing vapoursynth/.")
    parser.add_argument("--cuda-root", help="CUDA toolkit root for cu121/cu129.")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        raise RuntimeError("ci_build_native.py is for Linux/macOS; use ci_build_windows.py on Windows")
    build_dir = Path(args.build_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    if args.clean:
        shutil.rmtree(build_dir, ignore_errors=True)
        shutil.rmtree(dist_dir / PLUGIN_NAME, ignore_errors=True)

    env = os.environ.copy()
    vs_root = resolve_vapoursynth_root(args.vapoursynth_root)
    prepend_pkgconfig(env, vs_root)
    cuda_root = resolve_cuda_root(args.cuda_root) if args.variant in CUDA_VARIANTS and sys.platform != "darwin" else None
    if cuda_root:
        env["CUDA_PATH"] = str(cuda_root)
        env["PATH"] = str(cuda_root / "bin") + os.pathsep + env.get("PATH", "")

    configure_and_build(build_dir / "cpu", env, vs_root, cuda=False, cuda_root=None)
    if cuda_root:
        configure_and_build(build_dir / "cuda", env, vs_root, cuda=True, cuda_root=cuda_root)
    package_dir = stage_package(build_dir, dist_dir, args.variant, cuda_root)
    print(f"Packaged {package_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
