# vs-dfttest2
DFTTest re-implementation for VapourSynth API4.

This fork packages the CPU backend and the static-NVRTC backend. The old cuFFT,
HIP, HIPRTC, and GCC backend sources are kept in the repository, but they are
not part of the default Windows package.

## Installation

The Windows VCS install path is release-backed. Pick the CUDA runtime family by
installing from one of the repository tags:

```powershell
pip install "vapoursynth-dfttest2 @ git+https://github.com/RyougiKukoc/vs-dfttest2.git@cu121"
pip install "vapoursynth-dfttest2 @ git+https://github.com/RyougiKukoc/vs-dfttest2.git@cu129"
```

`cu121` is built with CUDA 12.1 static NVRTC libraries. `cu129` is built with
CUDA 12.9 static NVRTC libraries. If you switch between the two tags, use
`--force-reinstall` so pip replaces the already-installed wheel with the other
variant.

## Usage

```python
from dfttest2 import DFTTest
output = DFTTest(input)
```

See also [VapourSynth-DFTTest](https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest).

## Compilation

The default local CMake configuration builds only CPU and NVRTC:

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
and smoke-tests CUDA 12.1 and CUDA 12.9 variants separately, then uploads
`dfttest2-cu121-win64.zip` or `dfttest2-cu129-win64.zip` to the matching
release tag.
