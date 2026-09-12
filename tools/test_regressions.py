"""Run DFTTest2 contract regressions in fresh VapourSynth processes.

The default suite needs the built CPU DLL; CUDA DLL validation needs no GPU.
Pass --gpu on a compatible NVIDIA machine to execute both GPU backends.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_load_artifact import resolve_artifact, resolve_vapoursynth_paths
from vs_test_utils import assert_plugin_paths, test_core

ROOT = Path(__file__).resolve().parents[1]


def load_helper(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def frame_hash(clip, n=0) -> str:
    frame = clip.get_frame(n)
    return hashlib.sha256(b"".join(memoryview(frame[p]).tobytes() for p in range(frame.format.num_planes))).hexdigest()


def pattern_clip(core, vs):
    base = core.std.BlankClip(width=64, height=48, length=5, format=vs.YUV420P8)

    def fill(n, f):
        frame = f.copy()
        for p in range(frame.format.num_planes):
            plane = frame[p]
            for y in range(plane.shape[0]):
                for x in range(plane.shape[1]):
                    plane[y, x] = 16 + (x * 11 + y * 7 + n * 19 + p * 37 + x * y % 41) % 220
        return frame

    return core.std.ModifyFrame(base, clips=base, selector=fill)


def helper_contracts(core, vs) -> None:
    clip = pattern_clip(core, vs)
    options = [0]
    targets = core.dfttest2_cpu.Version()["dispatch_targets"]
    if isinstance(targets, list):
        for opt, target in enumerate(targets[1:], start=1):
            if target.lower() == "sse2" or (
                target.lower() == "avx2" and ctypes.windll.kernel32.IsProcessorFeaturePresent(40)
            ):
                options.append(opt)
    for index, relative in enumerate(("dfttest2.py", "dfttest2/_dfttest2.py")):
        helper = load_helper(ROOT / relative, f"regression_helper_{index}")
        calls = []

        def capture(*args, **kwargs):
            calls.append(kwargs)
            return core.dfttest2_cpu.DFTTest(*args, **kwargs)

        helper.core = SimpleNamespace(dfttest2_cpu=SimpleNamespace(RDFT=core.dfttest2_cpu.RDFT, DFTTest=capture))
        for opt in options:
            output = []
            for beta in (0.7, 2.0):
                result = helper.DFTTest(clip, backend=helper.Backend.CPU(opt=opt), f0beta=beta)
                # The exponent is dimensionless: it must reach native pmin unchanged.
                assert calls[-1]["filter_type"] == 5 and calls[-1]["pmin"] == beta, calls[-1]["pmin"]
                output.append(frame_hash(result, 2))
            assert output[0] != output[1], f"different exponents produced identical output with opt={opt}"

        # Multiplying all frequency coefficients by zero yields zero, unless
        # the mean was deliberately removed and restored by zero_mean=True.
        flat = core.std.BlankClip(width=64, height=48, format=vs.GRAY8, color=[96])
        for enabled, expected in ((False, 0), (True, 96)):
            result = helper.DFTTest(flat, backend=helper.Backend.CPU(), ftype=2, sigma=0, zmean=enabled)
            assert calls[-1]["zero_mean"] is enabled
            props = core.std.PlaneStats(result).get_frame(0).props
            assert props["PlaneStatsMin"] == props["PlaneStatsMax"] == expected, dict(props)


def native_contracts(core, vs) -> None:
    clip = core.std.BlankClip(width=64, height=48, format=vs.GRAY8)
    for radius in (0, 3):
        window_size = (2 * radius + 1) * 16 * 16
        spectrum_size = (2 * radius + 1) * 16 * 9
        params = dict(window=[1.] * window_size, sigma=[1.] * spectrum_size,
                      sigma2=1., pmin=0., pmax=1., filter_type=0, radius=radius)
        invalid = [("window_freq", None)]
        for key, length in (("window", window_size), ("sigma", spectrum_size), ("window_freq", spectrum_size * 2)):
            invalid.extend((key, [1.] * size) for size in (length - 1, length + 1))
        for key, value in invalid:
            arguments = {**params, "window_freq": [1.] * (spectrum_size * 2)}
            if value is None:
                arguments.pop(key)
            else:
                arguments[key] = value
            try:
                core.dfttest2_cpu.DFTTest(clip, **arguments)
            except vs.Error as error:
                assert key in str(error), str(error)
            else:
                raise AssertionError(f"accepted invalid {key} with radius={radius}")
        # Optional window_freq really is optional when mean removal is off.
        output = core.dfttest2_cpu.DFTTest(clip, **params, zero_mean=False)
        assert output.get_frame(0).width == 64

    # These calls must fail before cuInit or kernel compilation, so CI without
    # an NVIDIA driver also proves the native entrypoint guards execute first.
    variable_format = core.std.Splice([
        clip, core.std.BlankClip(width=64, height=48, format=vs.GRAY16)
    ], mismatch=True)
    variable_size = core.std.Splice([
        clip, core.std.BlankClip(width=80, height=48, format=vs.GRAY8)
    ], mismatch=True)
    float16 = core.std.BlankClip(width=64, height=48, format=vs.GRAYH)
    for backend in ("nvrtc", "cuda"):
        if not hasattr(core, "dfttest2_" + backend):
            continue
        native = getattr(core, "dfttest2_" + backend).DFTTest
        for bad_clip, message in ((variable_format, "constant format"), (variable_size, "constant format"),
                                  (float16, "32-bit float")):
            try:
                native(bad_clip, kernel="invalid code must not reach compilation", in_place=False)
            except vs.Error as error:
                assert message in str(error), str(error)
            else:
                raise AssertionError(f"{backend} accepted invalid format")


def gpu_contracts(core, vs) -> None:
    helper = load_helper(ROOT / "dfttest2/_dfttest2.py", "gpu_regression_helper")
    helper.core = core
    for backend_type in (helper.Backend.NVRTC, helper.Backend.cuFFT):
        # ftype=2,sigma=1 is identity. Non-byte-aligned depths must use uint16
        # storage while retaining their own scale and peak.
        for fmt, value in ((vs.GRAY8, 193), (vs.GRAY10, 773), (vs.GRAY16, 49157), (vs.GRAYS, 0.375)):
            clip = core.std.BlankClip(width=64, height=48, length=3, format=fmt, color=[value])
            output = helper.DFTTest(clip, backend=backend_type(), ftype=2, sigma=1, tbsize=1, zmean=False)
            frame = output.get_frame(0)
            for row in frame[0].tolist():
                assert all(abs(pixel - value) <= (1e-5 if fmt == vs.GRAYS else 1) for pixel in row), (backend_type, fmt, row)


def worker(args) -> None:
    package = resolve_artifact(Path(args.artifact_dir))
    sys_paths, dll_paths = resolve_vapoursynth_paths(Path(args.vapoursynth_root) if args.vapoursynth_root else None)
    for path in reversed(sys_paths):
        sys.path.insert(0, str(path))
    handles = [os.add_dll_directory(str(p)) for p in [package, package / "vsmlrt-cuda", *dll_paths] if p.is_dir()]
    try:
        import vapoursynth as vs
        if args.worker in ("isolation_off", "isolation_on"):
            # This *copied* CPU package is a sentinel. Autoload must either see
            # its exact path or see no DFTTest2 plugin before explicit loading.
            os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(package.parent)
            enabled = args.worker == "isolation_on"
            with test_core(vs, autoload=enabled) as core:
                if enabled:
                    assert_plugin_paths(core, package)
                else:
                    assert not hasattr(core, "dfttest2_cpu"), "sentinel autoloaded despite DISABLE_AUTO_LOADING"
                    core.std.LoadPlugin(str(package / "dfttest2_cpu.dll"))
                    assert_plugin_paths(core, package)
            return
        with test_core(vs, autoload=False) as core:
            core.num_threads = 2
            for path in sorted(package.glob("dfttest2_*.dll")):
                core.std.LoadPlugin(str(path))
            assert_plugin_paths(core, package)
            {"helper": helper_contracts, "native": native_contracts, "gpu": gpu_contracts}[args.worker](core, vs)
    finally:
        for handle in handles:
            handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--vapoursynth-root")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--suite", choices=("all", "helper", "native", "isolation"), default="all")
    parser.add_argument("--worker", choices=("helper", "native", "gpu", "isolation_off", "isolation_on"))
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return 0
    groups = ["helper", "native", "isolation_off", "isolation_on"] if args.suite == "all" else (
        ["isolation_off", "isolation_on"] if args.suite == "isolation" else [args.suite])
    if args.gpu:
        groups.append("gpu")
    results = []
    package = resolve_artifact(Path(args.artifact_dir))
    with tempfile.TemporaryDirectory(prefix="dfttest2-regressions-") as temporary:
        sentinel = Path(temporary) / "sentinel"
        sentinel.mkdir()
        shutil.copy2(package / "dfttest2_cpu.dll", sentinel / "dfttest2_cpu.dll")
        # CPU builds may carry compiler runtime DLLs alongside the plugin.
        for dependency in package.glob("*.dll"):
            if not dependency.name.startswith("dfttest2_"):
                shutil.copy2(dependency, sentinel / dependency.name)
        (sentinel / "manifest.vs").write_text("[VapourSynth Manifest V1]\ndfttest2_cpu\n", encoding="ascii")
        for group in groups:
            artifact = sentinel if group.startswith("isolation") else package
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", group, "--artifact-dir", str(artifact)]
            if args.vapoursynth_root:
                command.extend(["--vapoursynth-root", args.vapoursynth_root])
            try:
                process = subprocess.run(command, capture_output=True, text=True, timeout=180)
                item = dict(group=group, ok=process.returncode == 0, returncode=process.returncode,
                            stdout=process.stdout, stderr=process.stderr)
            except subprocess.TimeoutExpired:
                item = dict(group=group, ok=False, error="worker exceeded 180 seconds")
            results.append(item)
            print(json.dumps(item, indent=2), flush=True)
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
