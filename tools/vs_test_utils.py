"""VapourSynth test environments: require creation flags and verify DLL identity."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys


class TestEnvironmentPolicy:
    def __init__(self, flags: int) -> None:
        self.flags = flags
        self.api = None
        self.environment = None

    def on_policy_registered(self, api) -> None:
        self.api = api
        self.environment = api.create_environment(self.flags)

    def on_policy_cleared(self) -> None:
        self.close()
        self.api = None

    def get_current_environment(self):
        return self.environment

    def set_environment(self, environment):
        previous = self.environment
        if environment is not None:
            self.environment = environment
        return previous

    def is_alive(self, environment) -> bool:
        return environment is self.environment

    def close(self) -> None:
        if self.api is not None and self.environment is not None:
            self.api.destroy_environment(self.environment)
            self.environment = None


@contextmanager
def test_core(vs, *, autoload: bool = False):
    # A prior policy/core makes a claim about creation flags unverifiable.
    if vs.has_policy():
        raise RuntimeError("VapourSynth already has an environment policy; run the test in a fresh process")
    flags = 0 if autoload else int(vs.DISABLE_AUTO_LOADING)
    policy = TestEnvironmentPolicy(flags)
    vs.register_policy(policy)
    try:
        yield vs.core
    finally:
        policy.close()


def assert_plugin_paths(core, package: Path, *, expected_backends: tuple[str, ...] | None = None) -> None:
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
    for backend in ("cpu", "nvrtc", "cuda"):
        namespace = "dfttest2_" + backend
        expected = package / (namespace + suffix)
        loaded = hasattr(core, namespace)
        should_be_loaded = expected.is_file() if expected_backends is None else backend in expected_backends
        if should_be_loaded != loaded:
            raise RuntimeError(f"unexpected presence of {namespace}: expected loaded={should_be_loaded}, loaded={loaded}")
        if loaded:
            actual = Path(getattr(core, namespace).plugin_path)
            if not actual.is_file() or not actual.samefile(expected):
                raise RuntimeError(f"{namespace} loaded {actual}, expected {expected}")
            print(f"Verified {namespace}: {actual}")
