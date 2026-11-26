import sys

import pytest


@pytest.fixture
def anyio_backend():
    """Run the async tests on asyncio (bagof-paths' bridge needs it)."""
    return "asyncio"


@pytest.fixture
def async_memory(monkeypatch):
    """Make memory:// natively async for `AsyncPath`, for one test.

    `AsyncPath("memory://...")` then gets bagof-paths' native async driver,
    over fsspec's `AsyncFileSystemWrapper` around the in-process
    `MemoryFileSystem` (whose store is shared with the sync backend), as in
    bagof-paths' own tests. No network and no credentials are involved.
    """
    pytest.importorskip("fsspec")
    wrapper = pytest.importorskip("fsspec.implementations.asyn_wrapper")
    from fsspec.implementations.memory import MemoryFileSystem

    class AsyncMemoryFileSystem(wrapper.AsyncFileSystemWrapper):
        protocol = "memory"
        async_impl = True

        def __init__(self, *args, **kwargs):
            # bagof-paths passes asynchronous= and skip_instance_cache=
            super().__init__(MemoryFileSystem(), asynchronous=True)

        @classmethod
        def _strip_protocol(cls, path):
            return MemoryFileSystem._strip_protocol(path)

    registry = sys.modules["fsspec.registry"]._registry
    monkeypatch.setitem(registry, "memory", AsyncMemoryFileSystem)
    return AsyncMemoryFileSystem
