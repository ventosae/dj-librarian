"""What the host tells the engine (W-34, D-28), and where the engine keeps its files.

Door 1 core: stdlib only, and nothing from `dj` (dj.safety and dj.libfolder import this module).

The engine runs two ways:

- From a clone (DJ_ENGINE unset): the repo is the code and the home of `state/`, `backups/`,
  `.cache/` and `reports/`, exactly as in every earlier version.
- As the desktop extension (DJ_ENGINE=mcpb): the code sits in the extension's install folder,
  which an update replaces, and no file there is ever read as the DJ's (no `.env`, no config).
  What must outlive an update (preview records, build and push state, caches, master.db backups,
  tidy undo records) goes to `<dj-library>/.cache/engine/`, in the clone's layout (`state/`,
  `backups/`, `.cache/`); reports and log.md go to the dj-library folder itself. Without a usable
  library folder all of it goes to `~/.dj-librarian/`. The Spotify token always stays in
  `~/.dj-librarian/.cache/`: it belongs to this computer, and the dj-library folder may be
  cloud-synced or mounted for Claude (Cowork).

Host-given values come as environment variables from the extension's settings form:

    DJ_LIBRARY             the dj-library folder
    SPOTIFY_CLIENT_ID      the DJ's own Spotify app (secret: never printed or logged)
    SPOTIFY_CLIENT_SECRET
    DJ_POWER_MODE          "true" / "false": false refuses every master.db write; in the
                           extension an unset value refuses too (fails closed)
    DJ_ENGINE              "mcpb" in the extension

An empty value, or one with an unsubstituted `${...}` in it, counts as unset: a host may pass
either for an optional field the DJ left empty.

Config files (`tidy.yaml`, `bases.yaml`, `tree.yaml`): in a clone the library folder's first, the
repo's as the fallback; in the extension the library folder's only (`config_file`).
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]  # the clone, or the extension's install folder

ENGINE = "DJ_ENGINE"
BUNDLE = "mcpb"  # DJ_ENGINE's value in the desktop extension
LIBRARY = "DJ_LIBRARY"
POWER_MODE = "DJ_POWER_MODE"
SPOTIFY_CLIENT_ID = "SPOTIFY_CLIENT_ID"
SPOTIFY_CLIENT_SECRET = "SPOTIFY_CLIENT_SECRET"

FALLBACK_DIR = ".dj-librarian"  # under the home folder: the bundle's state without a library folder
ENGINE_STATE = (".cache", "engine")  # under the library folder: the bundle's state
LIBRARY_PATH_FILE = ("state", "library-path.txt")  # `dj library use`, under the state root

_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")
_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")

POWER_MODE_OFF = (
    "power mode is off in the engine settings, so master.db writes are refused. Write an XML to "
    "import instead, or turn on Power mode (Windows) in the engine settings. Nothing written."
)
# The extension started without a Power mode value (a host that did not fill it in): off.
POWER_MODE_UNSET = (
    "power mode is off: the engine settings passed no Power mode (Windows) value, so master.db "
    "writes are refused. Write an XML to import instead, or turn on Power mode (Windows) in the "
    "engine settings. Nothing written."
)
NO_LIBRARY = (
    "No dj-library folder is set: choose it in the engine settings (dj-library folder), then try again."
)


class HostSettingError(ValueError):
    """A setting the host gave cannot be used. One line; it names the setting, never a secret."""


# -- values ----------------------------------------------------------------------------------


def env_value(name: str) -> str | None:
    """The environment variable `name`, stripped; None when unset, empty, or still holding an
    unsubstituted `${...}` placeholder."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value or _PLACEHOLDER.search(value):
        return None
    return value


def bundle_mode() -> bool:
    """True in the desktop extension (DJ_ENGINE=mcpb), False in a clone."""
    return (env_value(ENGINE) or "").lower() == BUNDLE


def power_mode_setting() -> bool | None:
    """DJ_POWER_MODE: True (true/1/yes/on), False (false/0/no/off), None when unset.
    Anything else -> HostSettingError, one line."""
    value = env_value(POWER_MODE)
    if value is None:
        return None
    word = value.lower()
    if word in _TRUE:
        return True
    if word in _FALSE:
        return False
    raise HostSettingError(f"{POWER_MODE} must be true or false, got {value!r}. Nothing written.")


def power_mode_refusal() -> str | None:
    """Why the host's settings refuse a master.db write (one line), or None when they leave it to
    the call. DJ_POWER_MODE false (or not true/false) refuses. In the extension an unset value
    (empty, or an unsubstituted `${...}`) refuses too: its settings form defaults to off, so a
    value that did not arrive fails closed. True, or unset in a clone, leaves today's rule (the
    explicit flag, Windows only, a preview id). The setting never turns power mode on."""
    try:
        setting = power_mode_setting()
    except HostSettingError as exc:
        return str(exc)
    if setting is False:
        return POWER_MODE_OFF
    if setting is None and bundle_mode():
        return POWER_MODE_UNSET
    return None


# -- the library folder ------------------------------------------------------------------------


def fallback_root() -> Path:
    """`~/.dj-librarian`: the bundle's state and reports while no library folder can be used."""
    try:
        return Path.home() / FALLBACK_DIR
    except (OSError, RuntimeError):  # RuntimeError: no home folder known
        return Path(tempfile.gettempdir()) / "dj-librarian"


def library_path_file() -> Path:
    """Where `dj library use` stores the library folder's path: `state/library-path.txt` in the
    clone; in the bundle under `~/.dj-librarian/` (the install folder is replaced on update)."""
    base = fallback_root() if bundle_mode() else REPO_ROOT
    return base.joinpath(*LIBRARY_PATH_FILE)


# Where macOS and Linux desktops mount a whole drive, and how deep the drive's own folder sits:
# /Volumes/<drive>, /media/<drive> or /media/<user>/<drive>, /run/media/<user>/<drive>. Not /mnt:
# a sandbox may mount the connected folder itself there (and WSL is not supported anyway).
_VOLUME_MOUNTS = ((("/", "Volumes"), 3), (("/", "media"), 4), (("/", "run", "media"), 5))


def volume_root(path: str | Path) -> bool:
    """True for a mounted drive's own folder, or a folder above it (a DJ's external music drive
    on a Mac is /Volumes/<drive>). By path, not os.path.ismount: Cowork mounts the folder the DJ
    connected, the dj-library folder itself, and that one must stay usable."""
    parts = PurePosixPath(Path(path).as_posix()).parts
    return any(parts[: len(base)] == base and len(parts) <= depth for base, depth in _VOLUME_MOUNTS)


def check_library_root(path: str | Path, where: str) -> Path:
    """`path` expanded and resolved; HostSettingError if it is too wide to be one library folder
    (a drive or volume root, the home folder, or a folder above it)."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: `~` with no home folder known
        raise HostSettingError(f"{where}: cannot use {path}: {exc}") from exc
    too_wide = resolved.parent == resolved or volume_root(resolved)  # a filesystem, drive or volume root
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and home.is_relative_to(resolved):
        too_wide = True  # the home folder, or a folder that holds it
    if too_wide:
        raise HostSettingError(
            f"{where}: {resolved} is a whole drive or home folder, not a library folder. "
            "Point it at the dj-library folder itself."
        )
    return resolved


def library_setting(state_file: Path, default: Path | None, stored_where: str = "state/library-path.txt") -> Path:
    """The library folder, absolute: DJ_LIBRARY, else the path in `state_file` (`dj library use`),
    else `default` (the clone's `<repo>/dj-library`; None in the bundle -> HostSettingError, as
    the install folder holds no library). A folder too wide to be a library is refused.
    A state file that cannot be read raises its OSError / UnicodeDecodeError."""
    env = env_value(LIBRARY)
    if env:
        where = f"the dj-library folder in the engine settings ({LIBRARY})" if bundle_mode() else LIBRARY
        return check_library_root(env, where)
    if state_file.is_file():
        text = state_file.read_text(encoding="utf-8").strip()
        if text:
            return check_library_root(text, stored_where)
    if default is None:
        raise HostSettingError(NO_LIBRARY)
    return check_library_root(default, "the default library folder")


def configured_library() -> Path | None:
    """The configured library folder (it may not exist yet), or None when none can be used."""
    default = None if bundle_mode() else REPO_ROOT / "dj-library"
    try:
        return library_setting(library_path_file(), default, str(library_path_file()))
    except (HostSettingError, OSError, ValueError):  # ValueError: a state file that is not UTF-8
        return None


def usable_library() -> Path | None:
    """The configured library folder when it exists as a folder, else None."""
    root = configured_library()
    try:
        return root if root is not None and root.is_dir() else None
    except OSError:
        return None


# -- where files go ----------------------------------------------------------------------------


def state_root() -> Path:
    """The folder that holds `state/`, `backups/` and `.cache/`: the repo in a clone; in the
    bundle `<dj-library>/.cache/engine`, or `~/.dj-librarian` without a usable library folder."""
    if not bundle_mode():
        return REPO_ROOT
    library = usable_library()
    return library.joinpath(*ENGINE_STATE) if library is not None else fallback_root()


def home_root() -> Path:
    """The folder of the files the DJ reads (`reports/`, and log.md before the library is set
    up): the repo in a clone; in the bundle the dj-library folder, or `~/.dj-librarian` without a
    usable library folder."""
    if not bundle_mode():
        return REPO_ROOT
    library = usable_library()
    return library if library is not None else fallback_root()


def report_root() -> Path:
    """The folder reports go to: `<repo>/reports` in a clone; in the bundle `<dj-library>/reports`,
    or `~/.dj-librarian/reports` without a usable library folder."""
    return home_root() / "reports"


def machine_root() -> Path:
    """The folder of what belongs to this computer and must not follow the dj-library folder
    (which may be cloud-synced, and which Cowork mounts for Claude): the Spotify token, in its
    `.cache/`. The repo in a clone (as before); `~/.dj-librarian` in the bundle, which an update of
    the extension leaves alone."""
    return fallback_root() if bundle_mode() else REPO_ROOT


def config_file(name: str | Path, fallback: Path | None = None) -> Path:
    """A config file by name (`tidy.yaml`, `bases.yaml`, `tree.yaml`).

    Clone: the configured library folder's when it is there, else `fallback` (default
    `<repo>/<name>`, the clone's place). Bundle: the library folder's path, there or not (a "not
    found" then names the place the DJ should put it); never a file in the install folder, and
    without a library folder HostSettingError (NO_LIBRARY: it names the engine settings)."""
    library = configured_library()
    if bundle_mode():
        if library is None:
            raise HostSettingError(NO_LIBRARY)
        return library / name
    in_library = library / name if library is not None else None
    if in_library is not None and in_library.is_file():
        return in_library
    return fallback if fallback is not None else REPO_ROOT / name
