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


@pytest.fixture
def fail_nth(monkeypatch):
    """Make the store refuse the n-th file a commit writes (1-based).

    The failure is injected where bagof-paths moves a staged file onto its
    target, so the transaction sees the `CommitError` a real refusal gives.
    """
    from bagof.paths import _staged

    def arm(n):
        calls = []

        def wrap(real):
            def commit(*args, **kwargs):
                calls.append(args)
                if len(calls) == n:
                    raise PermissionError(13, "refused by the test")
                return real(*args, **kwargs)
            return commit

        def awrap(real):
            async def commit(*args, **kwargs):
                calls.append(args)
                if len(calls) == n:
                    raise PermissionError(13, "refused by the test")
                return await real(*args, **kwargs)
            return commit

        monkeypatch.setattr(_staged, "_commit_local", wrap(_staged._commit_local))
        monkeypatch.setattr(_staged, "_commit_remote", wrap(_staged._commit_remote))
        monkeypatch.setattr(
            _staged, "_acommit_remote", awrap(_staged._acommit_remote)
        )
        return calls

    return arm


@pytest.fixture
def listed_dirs(monkeypatch):
    """Record each directory the in-process memory store lists, in order."""
    pytest.importorskip("fsspec")
    from fsspec.implementations.memory import MemoryFileSystem

    listed = []
    real = MemoryFileSystem.ls

    def ls(self, path, *args, **kwargs):
        listed.append(MemoryFileSystem._strip_protocol(path).rstrip("/"))
        return real(self, path, *args, **kwargs)

    monkeypatch.setattr(MemoryFileSystem, "ls", ls)
    return listed
