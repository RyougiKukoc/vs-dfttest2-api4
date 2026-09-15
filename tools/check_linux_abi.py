"""Report and enforce package-wide ELF GLIBC/GLIBCXX symbol floors."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


GLIBC = re.compile(r"\bGLIBC_(\d+(?:\.\d+)+)")
GLIBCXX = re.compile(r"\bGLIBCXX_(\d+(?:\.\d+)+)")


def version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def maximum(values: list[str]) -> str | None:
    return max(values, key=version_key) if values else None


def versions(path: Path) -> tuple[str | None, str | None]:
    result = subprocess.run(["readelf", "--version-info", str(path)], check=True, capture_output=True, text=True)
    return maximum(GLIBC.findall(result.stdout)), maximum(GLIBCXX.findall(result.stdout))


def exceeds(actual: str | None, limit: str) -> bool:
    return actual is not None and version_key(actual) > version_key(limit)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--max-glibc", required=True)
    parser.add_argument("--max-glibcxx", required=True)
    args = parser.parse_args(argv)

    files = sorted(path for path in args.package_dir.rglob("*.so*") if path.is_file())
    if not files:
        raise FileNotFoundError(f"no ELF shared libraries under {args.package_dir}")
    report = []
    glibc_versions = []
    glibcxx_versions = []
    for path in files:
        glibc, glibcxx = versions(path)
        if glibc:
            glibc_versions.append(glibc)
        if glibcxx:
            glibcxx_versions.append(glibcxx)
        report.append({"path": str(path), "GLIBC": glibc, "GLIBCXX": glibcxx})

    package_glibc = maximum(glibc_versions)
    package_glibcxx = maximum(glibcxx_versions)
    print(json.dumps({"files": report, "package_GLIBC": package_glibc, "package_GLIBCXX": package_glibcxx}, indent=2, sort_keys=True))
    if exceeds(package_glibc, args.max_glibc) or exceeds(package_glibcxx, args.max_glibcxx):
        raise RuntimeError(
            f"package ABI exceeds GLIBC_{args.max_glibc}/GLIBCXX_{args.max_glibcxx}: "
            f"GLIBC_{package_glibc}, GLIBCXX_{package_glibcxx}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
