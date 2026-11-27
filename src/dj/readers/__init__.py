"""Readers that turn a rekordbox source into a `dj.model.Library`.

`dj.readers.db` (pyrekordbox, a snapshot copy of master.db) is the one reader every command uses;
it is never imported from here, so importing this package stays light. `dj.readers.xml` is test
support only (see its docstring).
"""
