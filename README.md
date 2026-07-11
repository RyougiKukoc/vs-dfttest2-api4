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
