from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PLUGIN_NAME = "dfttest2"
ROOT = Path(__file__).resolve().parents[1]


def resolve_vapoursynth_paths(root: Path | None) -> tuple[list[Path], list[Path]]:
    if root is None:
        return [], []

    root = root.resolve()
    candidates = [
        (root, root / "vapoursynth"),
        (root / "Lib" / "site-packages", root / "Lib" / "site-packages" / "vapoursynth"),
        (root.parent, root),
    ]
    for sys_path, dll_path in candidates:
        if (dll_path / "libvapoursynth.dll").exists() and (dll_path / "__init__.py").exists():
            return [sys_path], [dll_path]
    return [root], [root]


def resolve_artifact(root: Path) -> Path:
    root = root.resolve()
    candidates = [
        root,
        root / PLUGIN_NAME,
        root / "vapoursynth" / "plugins" / PLUGIN_NAME,
    ]
    for candidate in candidates:
        if (candidate / "dfttest2_cpu.dll").exists():
            return candidate
    raise FileNotFoundError(root / PLUGIN_NAME / "dfttest2_cpu.dll")


def add_existing_dll_dirs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            os.add_dll_directory(str(path))


def has_filter(core: object, namespace: str, function: str) -> bool:
    return hasattr(core, namespace) and hasattr(getattr(core, namespace), function)


def make_core(vs: object, *, autoload: bool) -> object:
    flags = 0 if autoload else vs.DISABLE_AUTO_LOADING
    create_environment = getattr(vs, "create_environment", None)
    if create_environment is not None:
        for factory in (
            lambda: create_environment(flags=flags),
            lambda: create_environment(flags),
        ):
            try:
                env = factory()
                return env.get_core()
            except Exception:
                continue

    create_core = getattr(vs, "create_core", None)
    if create_core is not None:
        for factory in (
            lambda: create_core(flags=flags),
            lambda: create_core(flags),
        ):
            try:
                return factory()
            except Exception:
                continue

    core_type = getattr(vs, "Core", None)
    if core_type is not None:
        for factory in (
            lambda: core_type(flags=flags),
            lambda: core_type(flags),
            lambda: core_type(),
        ):
            try:
                return factory()
            except Exception:
                continue

    return vs.core


def exercise_cpu_filter(core: object, vs: object) -> None:
    import dfttest2
    import dfttest2._dfttest2 as helper

    helper.core = core

    clip = core.std.BlankClip(format=vs.YUV420P8, width=64, height=32, length=5, color=[96, 128, 128])
    filtered = dfttest2.DFTTest(clip, backend=dfttest2.Backend.CPU())
    frame = filtered.get_frame(2)
    stats = core.std.PlaneStats(filtered).get_frame(2).props
    if filtered.width != 64 or filtered.height != 32 or frame.width != 64 or frame.height != 32:
        raise RuntimeError(f"unexpected output size: node={filtered.width}x{filtered.height}, frame={frame.width}x{frame.height}")
    print(f"CPU filter exercise: {frame.width}x{frame.height}")
    print(f"PlaneStatsMin={stats['PlaneStatsMin']}")
    print(f"PlaneStatsMax={stats['PlaneStatsMax']}")
    print(f"PlaneStatsAverage={stats['PlaneStatsAverage']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-load a built DFTTest2 artifact with VapourSynth.")
    parser.add_argument("--vapoursynth-root", help="VapourSynth portable root or extracted wheel root.")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--autoload", action="store_true", help="Load through VAPOURSYNTH_EXTRA_PLUGIN_PATH instead of std.LoadPlugin.")
    parser.add_argument("--exercise-cpu-filter", action="store_true", help="Create a CPU DFTTest node and request one frame.")
    args = parser.parse_args(argv)

    vs_root = Path(args.vapoursynth_root).resolve() if args.vapoursynth_root else None
    artifact_root = Path(args.artifact_dir).resolve()
    artifact = resolve_artifact(artifact_root)

    required = [
        artifact / "dfttest2_cpu.dll",
        artifact / "manifest.vs",
    ]
    for path in required:
        if not path.exists():
            print(f"missing required path: {path}", file=sys.stderr)
            return 1
    has_nvrtc = (artifact / "dfttest2_nvrtc.dll").exists()
    has_cuda = (artifact / "dfttest2_cuda.dll").exists()

    sys_paths, dll_paths = resolve_vapoursynth_paths(vs_root)
    sys.path.insert(0, str(ROOT))
    for path in reversed(sys_paths):
        if path.exists():
            sys.path.insert(0, str(path))

    cuda_path = os.environ.get("CUDA_PATH")
    cuda_dirs = []
    if cuda_path:
        cuda_root = Path(cuda_path)
        cuda_dirs.extend([cuda_root / "bin" / "x64", cuda_root / "bin"])
    packaged_cuda_dir = artifact / "vsmlrt-cuda"

    add_existing_dll_dirs(
        [
            artifact,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
            *dll_paths,
            packaged_cuda_dir,
            *cuda_dirs,
        ]
    )

    if args.autoload:
        plugin_root = artifact.parent
        if artifact_root.joinpath("vapoursynth", "plugins").exists():
            plugin_root = artifact_root / "vapoursynth" / "plugins"
        elif artifact_root.joinpath(PLUGIN_NAME).exists():
            plugin_root = artifact_root
        os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(plugin_root)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1

    core = make_core(vs, autoload=args.autoload)

    if not args.autoload:
        core.std.LoadPlugin(str(artifact / "dfttest2_cpu.dll"))
        if has_nvrtc:
            core.std.LoadPlugin(str(artifact / "dfttest2_nvrtc.dll"))
        if has_cuda:
            core.std.LoadPlugin(str(artifact / "dfttest2_cuda.dll"))

    expected_namespaces = ["dfttest2_cpu"]
    if has_nvrtc:
        expected_namespaces.append("dfttest2_nvrtc")
    if has_cuda:
        expected_namespaces.append("dfttest2_cuda")
    missing = [name for name in expected_namespaces if not has_filter(core, name, "DFTTest")]
    if missing:
        print(f"missing plugin namespaces after loading artifact: {missing}", file=sys.stderr)
        return 1
    print(core.dfttest2_cpu.DFTTest)
    if has_nvrtc:
        print(core.dfttest2_nvrtc.DFTTest)
    if has_cuda:
        print(core.dfttest2_cuda.DFTTest)

    if args.exercise_cpu_filter:
        try:
            exercise_cpu_filter(core, vs)
        except Exception as exc:
            print(f"CPU filter exercise failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
