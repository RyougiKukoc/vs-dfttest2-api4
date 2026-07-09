from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "dfttest2"
SUPPORTED_VARIANTS = {"cu121", "cu129"}


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def resolve_vs_include(vapoursynth_root: Path | None) -> Path:
    candidates: list[Path] = []
    if vapoursynth_root:
        root = vapoursynth_root.resolve()
        candidates.extend(
            [
                root / "vapoursynth" / "include",
                root / "include",
            ]
        )
    candidates.append(ROOT / "_deps" / "vapoursynth-wheel-R77" / "vapoursynth" / "include")
    for candidate in candidates:
        if (candidate / "VapourSynth4.h").exists():
            return candidate
    raise FileNotFoundError("VapourSynth4.h")


def cuda_root_from_variant(variant: str) -> Path:
    env_root = os.environ.get("CUDA_PATH")
    if env_root:
        return Path(env_root)
    version = {"cu121": "v12.1", "cu129": "v12.9"}[variant]
    return Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA") / version


def resolve_cuda_root(candidate: Path) -> Path:
    candidates = [candidate.resolve()]
    candidates.append(candidates[0] / "Library")
    for root in candidates:
        if (root / "include" / "nvrtc.h").exists():
            return root
    raise FileNotFoundError(candidate / "include" / "nvrtc.h")


def find_built_dll(build_dir: Path, name: str) -> Path:
    matches = sorted(build_dir.rglob(name))
    if matches:
        return matches[0]
    raise FileNotFoundError(build_dir / name)


def stage_package(build_dir: Path, package_parent: Path) -> Path:
    package_dir = package_parent / PLUGIN_NAME
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    for dll_name in ("dfttest2_cpu.dll", "dfttest2_nvrtc.dll"):
        shutil.copy2(find_built_dll(build_dir, dll_name), package_dir / dll_name)
    shutil.copy2(ROOT / "LICENSE", package_dir / "LICENSE")
    (package_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\ndfttest2_nvrtc\ndfttest2_cpu\n",
        encoding="ascii",
        newline="\n",
    )
    return package_dir


def configure_common(build_dir: Path, vs_include: Path, extra: list[str], env: dict[str, str]) -> None:
    configure = [
        "cmake",
        "-S",
        str(ROOT),
        "-B",
        str(build_dir),
        "-G",
        "Ninja",
        "-D",
        "CMAKE_BUILD_TYPE=Release",
        "-D",
        "ENABLE_CUDA=OFF",
        "-D",
        "ENABLE_GCC=OFF",
        "-D",
        "ENABLE_HIP=OFF",
        "-D",
        f"VS_INCLUDE_DIR={vs_include}",
        *extra,
    ]
    run(configure, env=env)
    run(["cmake", "--build", str(build_dir), "--verbose"], env=env)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the DFTTest2 CPU/NVRTC package on Windows.")
    parser.add_argument("--variant", choices=sorted(SUPPORTED_VARIANTS), default=os.environ.get("DFTTEST2_CUDA_VARIANT", "cu121"))
    parser.add_argument("--build-dir", default=str(ROOT / "build-windows"))
    parser.add_argument("--dist-dir", default=str(ROOT / "dist" / "windows"))
    parser.add_argument("--vapoursynth-root", help="Extracted VapourSynth wheel root or portable root.")
    parser.add_argument("--cuda-root", help="CUDA toolkit root, for example C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v12.1.")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    variant = args.variant
    build_dir = Path(args.build_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    if args.clean:
        shutil.rmtree(build_dir, ignore_errors=True)
        shutil.rmtree(dist_dir / PLUGIN_NAME, ignore_errors=True)

    vs_include = resolve_vs_include(Path(args.vapoursynth_root) if args.vapoursynth_root else None)
    cuda_root = resolve_cuda_root(Path(args.cuda_root) if args.cuda_root else cuda_root_from_variant(variant))

    env = os.environ.copy()
    env["CUDA_PATH"] = str(cuda_root)
    cuda_bin = cuda_root / "bin"
    cuda_bin_x64 = cuda_bin / "x64"
    path_entries = [str(path) for path in (cuda_bin_x64, cuda_bin) if path.exists()]
    if path_entries:
        env["PATH"] = os.pathsep.join(path_entries + [env.get("PATH", "")])

    nvrtc_build_dir = build_dir / "nvrtc"
    cpu_build_dir = build_dir / "cpu"

    configure_common(
        nvrtc_build_dir,
        vs_include,
        [
            "-D",
            "ENABLE_NVRTC=ON",
            "-D",
            "USE_NVRTC_STATIC=ON",
            "-D",
            "ENABLE_CPU=OFF",
            "-D",
            f"CUDAToolkit_ROOT={cuda_root}",
            "-D",
            "CMAKE_CXX_FLAGS=/fp:fast /EHsc",
            "-D",
            "CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
        ],
        env,
    )

    configure_common(
        cpu_build_dir,
        vs_include,
        [
            "-D",
            "ENABLE_NVRTC=OFF",
            "-D",
            "ENABLE_CPU=ON",
            "-D",
            "CMAKE_CXX_COMPILER=clang++",
            "-D",
            "CMAKE_CXX_FLAGS=-ffast-math",
            "-D",
            "CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
        ],
        env,
    )

    package_dir = stage_package(build_dir, dist_dir)
    print(f"Packaged {package_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
