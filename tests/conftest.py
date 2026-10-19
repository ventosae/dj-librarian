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
    """A test that forgets to mock must fail loudly, never touch master.db or the internet."""
    import socket

    from dj import safety

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to reach the real master.db or the network")

    monkeypatch.setattr(safety, "_connect", refuse)
    monkeypatch.setattr(safety, "find_master_db", refuse)
    real_connect = socket.socket.connect

    def loopback_only(sock, address):
        # asyncio on Windows wires its event loop through a 127.0.0.1 socket pair.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return real_connect(sock, address)
        refuse()

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
