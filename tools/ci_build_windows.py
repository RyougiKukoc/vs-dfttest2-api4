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
                root / "Lib" / "site-packages" / "vapoursynth" / "include",
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


def find_cuda_runtime_dlls(cuda_root: Path) -> list[Path]:
    dll_dirs = [
        cuda_root / "bin" / "x64",
        cuda_root / "bin",
    ]
    patterns = [
        "cufft64_*.dll",
        "cudart64_*.dll",
        "nvJitLink_*.dll",
        "nvfatbin_*.dll",
        "nvptxcompiler_*.dll",
        "nvrtc64_*.dll",
    ]
    found: dict[str, Path] = {}
    for dll_dir in dll_dirs:
        if not dll_dir.exists():
            continue
        for pattern in patterns:
            for path in dll_dir.glob(pattern):
                found.setdefault(path.name.lower(), path)
    required_patterns = {
        "cufft64_": "cufft64_*.dll",
        "cudart64_": "cudart64_*.dll",
    }
    for prefix, pattern in required_patterns.items():
        if not any(name.startswith(prefix) for name in found):
            raise FileNotFoundError(cuda_root / "bin" / pattern)
    return [found[name] for name in sorted(found)]


def stage_package(build_dir: Path, package_parent: Path, variant: str, cuda_root: Path | None = None) -> Path:
    package_dir = package_parent / PLUGIN_NAME
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    plugin_names = ["dfttest2_cpu"]
    shutil.copy2(find_built_dll(build_dir, "dfttest2_cpu.dll"), package_dir / "dfttest2_cpu.dll")
    if variant in CUDA_VARIANTS:
        if cuda_root is None:
            raise RuntimeError("cuda_root is required for CUDA variants")
        shutil.copy2(find_built_dll(build_dir, "dfttest2_cuda.dll"), package_dir / "dfttest2_cuda.dll")
        shutil.copy2(find_built_dll(build_dir, "dfttest2_nvrtc.dll"), package_dir / "dfttest2_nvrtc.dll")
        runtime_dir = package_dir / "vsmlrt-cuda"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        for dll in find_cuda_runtime_dlls(cuda_root):
            shutil.copy2(dll, runtime_dir / dll.name)
        plugin_names.insert(0, "dfttest2_nvrtc")
        plugin_names.insert(1, "dfttest2_cuda")
    shutil.copy2(ROOT / "LICENSE", package_dir / "LICENSE")
    (package_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\n" + "\n".join(plugin_names) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return package_dir


def configure_common(
    build_dir: Path,
    vs_include: Path,
    extra: list[str],
    env: dict[str, str],
    *,
    enable_cuda: bool = False,
) -> None:
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
        f"ENABLE_CUDA={'ON' if enable_cuda else 'OFF'}",
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
    parser = argparse.ArgumentParser(description="Build a DFTTest2 Windows package variant.")
    default_variant = os.environ.get("DFTTEST2_VARIANT") or os.environ.get("DFTTEST2_CUDA_VARIANT", "cu121")
    parser.add_argument("--variant", choices=sorted(SUPPORTED_VARIANTS), default=default_variant)
    parser.add_argument("--build-dir", default=str(ROOT / "build-windows"))
    parser.add_argument("--dist-dir", default=str(ROOT / "dist" / "windows"))
    parser.add_argument("--vapoursynth-root", help="Extracted VapourSynth wheel root or portable root.")
    parser.add_argument("--cuda-root", help="CUDA toolkit root for cu121/cu129 variants.")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    variant = args.variant
    build_dir = Path(args.build_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    if args.clean:
        shutil.rmtree(build_dir, ignore_errors=True)
        shutil.rmtree(dist_dir / PLUGIN_NAME, ignore_errors=True)

    vs_include = resolve_vs_include(Path(args.vapoursynth_root) if args.vapoursynth_root else None)
    env = os.environ.copy()

    cuda_build_dir = build_dir / "cuda"
    cpu_build_dir = build_dir / "cpu"
    cuda_root: Path | None = None

    if variant in CUDA_VARIANTS:
        cuda_root = resolve_cuda_root(Path(args.cuda_root) if args.cuda_root else cuda_root_from_variant(variant))
        env["CUDA_PATH"] = str(cuda_root)
        cuda_bin = cuda_root / "bin"
        cuda_bin_x64 = cuda_bin / "x64"
        path_entries = [str(path) for path in (cuda_bin_x64, cuda_bin) if path.exists()]
        if path_entries:
            env["PATH"] = os.pathsep.join(path_entries + [env.get("PATH", "")])

        configure_common(
            cuda_build_dir,
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
            enable_cuda=True,
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

    package_dir = stage_package(build_dir, dist_dir, variant, cuda_root)
    print(f"Packaged {package_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
