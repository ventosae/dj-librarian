"""dj tidy: library hygiene for the audio files behind the rekordbox collection.

Reads master.db only through `safety.open_db(write=False)` (never a write session, never a
commit). Writes go to audio-file tags, same-directory renames, and repo files under
plans/, reports/tidy/ and state/tidy/. Never deletes, never moves across folders.
"""

from __future__ import annotations


class TidyError(RuntimeError):
    pass
