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
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    package_dir = input_dir / PLUGIN_NAME
    required = [
        package_dir / "dfttest2_cpu.dll",
        package_dir / "manifest.vs",
    ]
    if args.variant in CUDA_VARIANTS:
        required.append(package_dir / "dfttest2_cuda.dll")
        required.append(package_dir / "dfttest2_nvrtc.dll")
        for pattern in ("cufft64_*.dll", "cudart64_*.dll"):
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
    if args.variant == "cpu" and (package_dir / "dfttest2_nvrtc.dll").exists():
        raise RuntimeError(f"cpu package unexpectedly contains {package_dir / 'dfttest2_nvrtc.dll'}")
    if args.variant == "cpu" and (package_dir / "dfttest2_cuda.dll").exists():
        raise RuntimeError(f"cpu package unexpectedly contains {package_dir / 'dfttest2_cuda.dll'}")
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
