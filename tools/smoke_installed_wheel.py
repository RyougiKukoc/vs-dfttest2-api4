from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path

# Portable Python may omit the script directory from sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vs_test_utils import assert_plugin_paths, test_core


PLUGIN_NAME = "dfttest2"


def add_existing_dll_dirs(paths: list[Path]) -> list[object]:
    return [os.add_dll_directory(str(path)) for path in paths if path.exists()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed vapoursynth-dfttest2 wheel.")
    parser.add_argument("--exercise-cpu-filter", action="store_true", help="Create a CPU DFTTest node and request one frame.")
    args = parser.parse_args(argv)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1

    vs_pkg = Path(vs.__file__).resolve().parent
    plugin_dir = vs_pkg / "plugins" / PLUGIN_NAME
    required = [
        plugin_dir / "dfttest2_cpu.dll",
        plugin_dir / "manifest.vs",
    ]
    for path in required:
        if not path.exists():
            print(f"missing installed file: {path}", file=sys.stderr)
            return 1
    has_nvrtc = (plugin_dir / "dfttest2_nvrtc.dll").exists()
    has_cuda = (plugin_dir / "dfttest2_cuda.dll").exists()

    cuda_path = os.environ.get("CUDA_PATH")
    cuda_dirs = []
    if cuda_path:
        cuda_root = Path(cuda_path)
        cuda_dirs.extend([cuda_root / "bin" / "x64", cuda_root / "bin"])

    dll_handles = add_existing_dll_dirs(
        [
            plugin_dir,
            plugin_dir / "vsmlrt-cuda",
            vs_pkg,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
            *cuda_dirs,
        ]
    )

    try:
        with test_core(vs, autoload=True) as core:
            assert_plugin_paths(core, plugin_dir)

            if not hasattr(core, "dfttest2_cpu") or not hasattr(core.dfttest2_cpu, "DFTTest"):
                print("core.dfttest2_cpu.DFTTest missing after installed-wheel autoload", file=sys.stderr)
                return 1
            if has_nvrtc and (not hasattr(core, "dfttest2_nvrtc") or not hasattr(core.dfttest2_nvrtc, "DFTTest")):
                print("core.dfttest2_nvrtc.DFTTest missing after installed-wheel autoload", file=sys.stderr)
                return 1
            if has_cuda and (not hasattr(core, "dfttest2_cuda") or not hasattr(core.dfttest2_cuda, "DFTTest")):
                print("core.dfttest2_cuda.DFTTest missing after installed-wheel autoload", file=sys.stderr)
                return 1
            print(core.dfttest2_cpu.DFTTest)
            if has_nvrtc:
                print(core.dfttest2_nvrtc.DFTTest)
            if has_cuda:
                print(core.dfttest2_cuda.DFTTest)

            if args.exercise_cpu_filter:
                try:
                    import dfttest2
                    import dfttest2._dfttest2 as helper

                    helper.core = core

                    clip = core.std.BlankClip(format=vs.YUV420P8, width=64, height=32, length=5, color=[96, 128, 128])
                    filtered = dfttest2.DFTTest(clip, backend=dfttest2.Backend.CPU())
                    frame = filtered.get_frame(2)
                    stats = core.std.PlaneStats(filtered).get_frame(2).props
                except Exception as exc:
                    print(f"CPU filter exercise failed: {exc}", file=sys.stderr)
                    return 1

                if filtered.width != 64 or filtered.height != 32 or frame.width != 64 or frame.height != 32:
                    print(
                        f"unexpected output size: node={filtered.width}x{filtered.height}, frame={frame.width}x{frame.height}",
                        file=sys.stderr,
                    )
                    return 1
                print(f"CPU filter exercise: {frame.width}x{frame.height}")
                print(f"PlaneStatsMin={stats['PlaneStatsMin']}")
                print(f"PlaneStatsMax={stats['PlaneStatsMax']}")
                print(f"PlaneStatsAverage={stats['PlaneStatsAverage']}")
            return 0
    finally:
        for handle in dll_handles:
            handle.close()



if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
