# vs-dfttest2-api4
DFTTest re-implementation for VapourSynth API4.

This fork packages the CPU backend and, for CUDA-tagged builds, the NVRTC and
cuFFT/CUDA backends. The HIP, HIPRTC, and GCC backend sources are kept in the
repository, but they are not part of the default Windows package.

## Installation

The Windows VCS install path is release-backed. Pick the package variant by
installing from one of the repository tags:

```powershell
pip install "vapoursynth-dfttest2 @ git+https://github.com/RyougiKukoc/vs-dfttest2-api4.git@cpu"
pip install "vapoursynth-dfttest2 @ git+https://github.com/RyougiKukoc/vs-dfttest2-api4.git@cu121"
pip install "vapoursynth-dfttest2 @ git+https://github.com/RyougiKukoc/vs-dfttest2-api4.git@cu129"
```

`cpu` installs only `dfttest2_cpu.dll`. `cu121` installs `dfttest2_cpu.dll`
plus CUDA 12.1 builds of `dfttest2_nvrtc.dll` and `dfttest2_cuda.dll`. `cu129`
does the same with CUDA 12.9. If you switch between tags, use
`--force-reinstall` so pip replaces the already-installed wheel with the other
variant.

## Usage

```python
from dfttest2 import DFTTest
output = DFTTest(input)
```

See also [VapourSynth-DFTTest](https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest).

## Compilation

The default local CMake configuration builds CPU and NVRTC. Enable
`ENABLE_CUDA` as well when building the cuFFT backend:

```powershell
cmake -S . -B build -G Ninja `
  -D ENABLE_CPU=ON `
  -D ENABLE_NVRTC=ON `
  -D ENABLE_CUDA=OFF `
  -D ENABLE_GCC=OFF `
  -D ENABLE_HIP=OFF `
  -D USE_NVRTC_STATIC=ON `
  -D VS_INCLUDE_DIR=C:\path\to\vapoursynth\include

cmake --build build
```

For reproducible release packages, use the GitHub Actions workflow. It builds
and smoke-tests the CPU-only, CUDA 12.1, and CUDA 12.9 variants separately,
then uploads `dfttest2-cpu-win64.zip`, `dfttest2-cu121-win64.zip`, or
`dfttest2-cu129-win64.zip` to the matching release tag.

## Behavior fixes and regression checks

For `ftype=0`, non-default `f0beta` values now reach the native power calculation
as an unscaled exponent. The CPU helper also forwards `zmean=False`, allowing
the mean to be filtered. These corrections intentionally change affected
outputs. Native CPU calls reject missing or incorrectly sized window/sigma
arrays with a VapourSynth error, and GPU entrypoints reject variable formats
and unsupported sample types before initializing CUDA. GPU kernels use 16-bit
storage for 9–15-bit input.

Clang 20.1.8 with `-ffast-math` can miscompile VCL's AVX2 power calculation even
with finite input. The CMake CPU frame targets add `-fno-finite-math-only` while
retaining SIMD, FMA and the other optimizations. Windows packages continue to
use the separate CPU, CUDA 12.1 and CUDA 12.9 builds with static NVRTC.

CI runs native argument checks, mathematical CPU output checks, and explicit
tests of autoload isolation before packaging. Run the same suite against a
built package with an R77 Python environment:

```console
python tools/test_regressions.py --artifact-dir dist/windows-cu121 --vapoursynth-root _deps/vapoursynth-wheel-R77
```

On a compatible NVIDIA machine, add `--gpu` to exercise NVRTC and cuFFT with
8-bit, 10-bit, 16-bit and float input. Smoke helpers also verify the actual
loaded DLL paths, so another installed copy cannot silently satisfy a check.
