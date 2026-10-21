"""A fake pyrekordbox database. No test may open the real master.db."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

import pytest

ATTRIBUTE = {"playlist": 0, "folder": 1, "smart": 4}


@dataclass
class Row:
    ID: str
    Name: str
    Attribute: int
    ParentID: str
    Seq: int
    SmartList: str | None = None
    Songs: list = field(default_factory=list)


class Query:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def count(self):
        return len(self._rows)


class FakeDB:
    def __init__(self):
        self.rows: list[Row] = []
        self.calls: list[tuple] = []
        self.commits = self.rollbacks = self.closes = 0
        self._ids = count(1000)

    # -- test setup
    def seed(self, kind, name, parent="root"):
        parent_id = parent.ID if isinstance(parent, Row) else parent
        seq = sum(r.ParentID == parent_id for r in self.rows) + 1
        row = Row(str(next(self._ids)), name, ATTRIBUTE[kind], parent_id, seq)
        self.rows.append(row)
        return row

    # -- the pyrekordbox surface the tool is allowed to use
    def get_playlist(self, **kwargs):
        assert set(kwargs) == {"ParentID"}
        return Query([r for r in self.rows if r.ParentID == kwargs["ParentID"]])

    def _create(self, kind, name, parent, kwargs):
        assert not kwargs, f"only name/parent may be passed, never {sorted(kwargs)}"
        self.calls.append((kind, name, parent.ID if isinstance(parent, Row) else parent))
        return self.seed(kind, name, "root" if parent is None else parent)

    def create_playlist(self, name, parent=None, **kwargs):
        return self._create("playlist", name, parent, kwargs)

    def create_playlist_folder(self, name, parent=None, **kwargs):
        return self._create("folder", name, parent, kwargs)

    def create_smart_playlist(self, name, smart_list, parent=None, **kwargs):
        row = self._create("smart", name, parent, kwargs)
        row.SmartList = smart_list
        return row

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"the tool called db.{name}, which it must never use")


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture(autouse=True)
def no_real_db_no_network(monkeypatch):
    """A test that forgets to mock must fail loudly, never touch master.db or the internet.

    Network: connect, connect_ex and sendto reach loopback only, and only the machine's own names
    resolve. asyncio's Proactor connects to a numeric address without socket.connect; a host name
    still has to resolve first, which is blocked."""
    import socket

    from dj import safety

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to reach the real master.db or the network")

    monkeypatch.setattr(safety, "_connect", refuse)
    monkeypatch.setattr(safety, "find_master_db", refuse)
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_getaddrinfo = socket.getaddrinfo
    loopback = ("127.0.0.1", "::1")

    def is_loopback(address):
        return isinstance(address, tuple) and address[0] in loopback

    def loopback_only(sock, address):
        # asyncio on Windows wires its event loop through a 127.0.0.1 socket pair.
        if is_loopback(address):
            return real_connect(sock, address)
        refuse()

    def loopback_only_ex(sock, address):
        if is_loopback(address):
            return real_connect_ex(sock, address)
        refuse()

    def loopback_sendto(sock, data, *args):
        if args and is_loopback(args[-1]):  # sendto(data, address) or sendto(data, flags, address)
            return real_sendto(sock, data, *args)
        refuse()

    def local_names_only(host, *args, **kwargs):
        # DNS is the network too: only the machine itself resolves (asyncio and httpx resolve
        # before they connect, so this also covers connections that bypass socket.connect).
        if host in (None, "", "localhost", b"localhost", *loopback):
            return real_getaddrinfo(host, *args, **kwargs)
        refuse()

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(socket.socket, "connect_ex", loopback_only_ex)
    monkeypatch.setattr(socket.socket, "sendto", loopback_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", local_names_only)


@pytest.fixture
def live_master_db(monkeypatch, tmp_path_factory):
    """For a test whose fake `safety.open_db` serves the CLI's reads: a small file standing in for
    the live master.db, returned by `safety.find_master_db`. Every read-only pass copies it to a
    snapshot (`dj.readers.db.open_snapshot`, R-202) and opens only the copy, so a fake open_db sees
    `db_path` = the copy. Its bytes are only copied, never read. Returns its path."""
    from dj import safety

    path = tmp_path_factory.mktemp("live-rekordbox") / "master.db"
    path.write_bytes(b"stands in for the live master.db: copied, never opened")
    monkeypatch.setattr(safety, "find_master_db", lambda: path)
    return path


@pytest.fixture(autouse=True)
def no_real_library_folder(monkeypatch, tmp_path_factory):
    """The DJ's own dj-library folder is real data too. Since W-25 (R-802) the inbox loop follows
    the library's links.yaml, so a set DJ_LIBRARY or a remembered folder on the test machine would
    send `dj pull`/`plan`/`apply` there. Every test starts with a library folder that does not
    exist; a test that needs one builds it under tmp_path and sets DJ_LIBRARY itself."""
    monkeypatch.setenv("DJ_LIBRARY", str(tmp_path_factory.getbasetemp() / "no-dj-library"))


@pytest.fixture(autouse=True)
def gate_records_in_a_temp_folder(monkeypatch, tmp_path_factory, request):
    """The CLI's preview records (dj.write_gate, R-1102) go to a folder of this test's own, never
    to REPO_ROOT/state. Created only when a test records a preview."""
    import hashlib

    from dj import write_gate

    key = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:16]
    monkeypatch.setattr(write_gate, "STATE_DIR", tmp_path_factory.getbasetemp() / "gate-state" / key)


@pytest.fixture(autouse=True)
def activity_log_in_a_temp_folder(monkeypatch, tmp_path_factory, request):
    """The CLI's log.md lines (dj.activity_log, R-904) go to a folder of this test's own, never to
    REPO_ROOT/log.md or to a library folder configured on this machine. A test that checks the
    library-folder case patches `activity_log.library_root` itself."""
    import hashlib

    from dj import activity_log

    key = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:16]
    folder = tmp_path_factory.getbasetemp() / "activity-log" / key
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(activity_log, "REPO_DIR", folder)
    monkeypatch.setattr(activity_log, "library_root", lambda: None)


@pytest.fixture(autouse=True)
def mcp_runs_forgotten():
    """The MCP server keeps a read tool's run for its later pages (mcp_server.RUNS): each test
    starts and ends with none, so one test's run never answers another's page 2."""
    import sys

    def forget():
        server = sys.modules.get("dj.mcp_server")
        if server is not None:
            server.RUNS.clear()

    forget()
    yield
    forget()
