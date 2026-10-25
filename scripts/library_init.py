"""Make the DJ's dj-library folder (W-36): `/dj-librarian:install` step 6 runs this. The logic and its
tests live in src/dj/library_setup.py.

    python library_init.py --folder <whole path> --device <mac|windows> [--today YYYY-MM-DD]

In the plugin zip it sits in engine/scripts/ next to engine/src; in a clone in scripts/ next to
src/. Prints one JSON line; exit 2 on a refusal (synced, not empty, a drive or the home folder),
1 on any other error. Nothing is touched on either.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dj.library_setup import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
