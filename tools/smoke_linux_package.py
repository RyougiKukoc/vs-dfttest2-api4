"""Explicit-load or installed-wheel smoke test for a Linux DFTTest2 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "dfttest2"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vs_test_utils import assert_plugin_paths, test_core


def resolve_artifact(root: Path) -> Path:
    for candidate in (root, root / PLUGIN_NAME, root / "vapoursynth" / "plugins" / PLUGIN_NAME):
        if (candidate / "dfttest2_cpu.so").is_file():
            return candidate
    raise FileNotFoundError(root / PLUGIN_NAME / "dfttest2_cpu.so")


def frame_hash(frame) -> str:
    return hashlib.sha256(b"".join(memoryview(frame[p]).tobytes() for p in range(frame.format.num_planes))).hexdigest()


def pattern_clip(core, vs):
    base = core.std.BlankClip(width=64, height=48, length=12, format=vs.YUV420P8)

    def fill(n, f):
        frame = f.copy()
        for p in range(frame.format.num_planes):
            plane = frame[p]
            for y in range(plane.shape[0]):
                for x in range(plane.shape[1]):
                    plane[y, x] = 16 + (x * 11 + y * 7 + n * 19 + p * 37 + x * y % 41) % 220
        return frame

    return core.std.ModifyFrame(base, clips=base, selector=fill)


def report_clip(core, clip, frames: list[int]) -> list[dict[str, object]]:
    stats = core.std.PlaneStats(clip)
    report = []
    for n in frames:
        frame = clip.get_frame(n)
        props = stats.get_frame(n).props
        report.append({
            "frame": n,
            "sha256": frame_hash(frame),
            "width": frame.width,
            "height": frame.height,
            "format": frame.format.name,
            "PlaneStatsMin": float(props["PlaneStatsMin"]),
            "PlaneStatsMax": float(props["PlaneStatsMax"]),
            "PlaneStatsAverage": float(props["PlaneStatsAverage"]),
        })
    return report


def test_invalid_input(core, vs, helper) -> str:
    invalid = core.std.BlankClip(width=64, height=48, length=1, format=vs.GRAYH)
    try:
        helper.DFTTest(invalid, backend=helper.Backend.CPU())
    except (ValueError, vs.Error) as error:
        message = str(error)
        if "32 bit float" not in message:
            raise RuntimeError(f"unexpected invalid-input error: {message}")
        return message
    raise RuntimeError("dfttest2_cpu accepted unsupported GRAYH input")


def test_gpu(core, vs, helper) -> dict[str, list[dict[str, object]]]:
    clip = pattern_clip(core, vs)
    report: dict[str, list[dict[str, object]]] = {}
    for name, backend in (("nvrtc", helper.Backend.NVRTC()), ("cuda", helper.Backend.cuFFT())):
        output = helper.DFTTest(clip, backend=backend, ftype=2, sigma=1, tbsize=1, zmean=False)
        report[name] = report_clip(core, output, [0, 3, 11])
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact-dir")
    source.add_argument("--artifact-zip")
    source.add_argument("--installed", action="store_true", help="Use the installed VapourSynth plugin directory and autoload.")
    parser.add_argument("--gpu", action="store_true", help="Compile and execute NVRTC and cuFFT backends.")
    parser.add_argument("--skip-cuda", action="store_true", help="Load only the CPU plugin when a runner has no NVIDIA driver.")
    args = parser.parse_args(argv)
    if args.gpu and args.skip_cuda:
        parser.error("--gpu and --skip-cuda cannot be used together")
    if args.installed and args.skip_cuda:
        parser.error("--skip-cuda only applies to explicit loading; installed autoload loads the manifest")

    if args.installed:
        args.artifact_dir = None
        args.artifact_zip = None
        package = Path(sysconfig.get_paths()["platlib"]) / "vapoursynth" / "plugins" / PLUGIN_NAME
        os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(package.parent)
    elif args.artifact_dir:
        args.artifact_dir = str(Path(args.artifact_dir).resolve())

    with tempfile.TemporaryDirectory(prefix="dfttest2-linux-smoke-") as temporary:
        if args.artifact_zip:
            with zipfile.ZipFile(args.artifact_zip) as archive:
                archive.extractall(temporary)
            package = resolve_artifact(Path(temporary))
        elif args.installed:
            pass
        else:
            package = resolve_artifact(Path(args.artifact_dir))

        required = [package / "manifest.vs", package / "dfttest2_cpu.so"]
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(path)
        has_cuda = (package / "dfttest2_cuda.so").is_file()
        has_nvrtc = (package / "dfttest2_nvrtc.so").is_file()
        if has_cuda != has_nvrtc:
            raise RuntimeError("CUDA package must contain both dfttest2_cuda.so and dfttest2_nvrtc.so")
        if has_cuda:
            for pattern in ("libcufft.so.*", "libcudart.so.*"):
                if not list((package / "vsmlrt-cuda").glob(pattern)):
                    raise FileNotFoundError(package / "vsmlrt-cuda" / pattern)

        if not args.installed:
            # Release zips intentionally carry native plugins only; import the
            # source helper solely to construct the documented filter call.
            sys.path.insert(0, str(ROOT))
        import vapoursynth as vs
        import dfttest2
        import dfttest2._dfttest2 as helper

        with test_core(vs, autoload=args.installed) as core:
            if not args.installed:
                core.std.LoadPlugin(str(package / "dfttest2_cpu.so"))
                if has_nvrtc and not args.skip_cuda:
                    core.std.LoadPlugin(str(package / "dfttest2_nvrtc.so"))
                    core.std.LoadPlugin(str(package / "dfttest2_cuda.so"))
            assert_plugin_paths(core, package, expected_backends=("cpu",) if args.skip_cuda else None)
            helper.core = core
            cpu = dfttest2.DFTTest(pattern_clip(core, vs), backend=dfttest2.Backend.CPU())
            report: dict[str, object] = {
                "plugin_path": str(package),
                "manifest": (package / "manifest.vs").read_text(encoding="ascii"),
                "cpu": report_clip(core, cpu, [0, 3, 11]),
                "invalid_input": test_invalid_input(core, vs, helper),
            }
            if args.gpu:
                if not has_cuda:
                    raise RuntimeError("--gpu requires a CUDA package")
                report["gpu"] = test_gpu(core, vs, helper)
            print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
