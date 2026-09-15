from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "dfttest2"
CUDA_VARIANTS = {"cu121", "cu129"}
SUPPORTED_VARIANTS = {"cpu", *CUDA_VARIANTS}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create a DFTTest2 plugin package zip.")
    parser.add_argument("--input-dir", default=str(ROOT / "dist" / "windows"))
    parser.add_argument("--output", default=str(ROOT / "dist" / "dfttest2-cu121-win64.zip"))
    parser.add_argument("--variant", choices=sorted(SUPPORTED_VARIANTS), default="cu121")
    parser.add_argument("--platform", choices=("win64", "linux-x86_64"), default="win64")
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    package_dir = input_dir / PLUGIN_NAME
    suffix = ".dll" if args.platform == "win64" else ".so"
    required = [package_dir / ("dfttest2_cpu" + suffix), package_dir / "manifest.vs"]
    if args.variant in CUDA_VARIANTS:
        required.append(package_dir / ("dfttest2_cuda" + suffix))
        required.append(package_dir / ("dfttest2_nvrtc" + suffix))
        runtime_patterns = ("cufft64_*.dll", "cudart64_*.dll") if args.platform == "win64" else ("libcufft.so.*", "libcudart.so.*")
        for pattern in runtime_patterns:
            if not list((package_dir / "vsmlrt-cuda").glob(pattern)):
                raise FileNotFoundError(package_dir / "vsmlrt-cuda" / pattern)
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    manifest_text = (package_dir / "manifest.vs").read_text(encoding="ascii", errors="ignore")
    if args.variant in CUDA_VARIANTS:
        for plugin_name in ("dfttest2_nvrtc", "dfttest2_cuda", "dfttest2_cpu"):
            if plugin_name not in manifest_text:
                raise RuntimeError(f"CUDA package manifest does not list {plugin_name}")
    if args.variant == "cpu" and (package_dir / ("dfttest2_nvrtc" + suffix)).exists():
        raise RuntimeError(f"cpu package unexpectedly contains dfttest2_nvrtc{suffix}")
    if args.variant == "cpu" and (package_dir / ("dfttest2_cuda" + suffix)).exists():
        raise RuntimeError(f"cpu package unexpectedly contains dfttest2_cuda{suffix}")
    if args.variant == "cpu" and (package_dir / "vsmlrt-cuda").exists():
        raise RuntimeError(f"cpu package unexpectedly contains {package_dir / 'vsmlrt-cuda'}")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(input_dir))

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
