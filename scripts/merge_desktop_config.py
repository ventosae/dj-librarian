"""Add or remove the dj-librarian engine in Claude Desktop's config (W-35): `/dj-librarian:install`
and `/dj-librarian:uninstall` run this. Standard library only; the logic and its tests live in
src/dj/installer.py.

    python merge_desktop_config.py merge --uv <abs uv> --folder <abs engine folder> --library <dj-library>
    python merge_desktop_config.py remove

In the plugin zip it sits in plugin/engine/scripts/ next to engine/src; in a clone in scripts/
next to src/. Prints one JSON line; exit 1 on a refusal (nothing written).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dj.installer import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
