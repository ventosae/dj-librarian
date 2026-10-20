"""PreToolUse write gate for Claude Code (R-1105, C-10). Standard library only.

Claude Code runs this before every dj-librarian write tool (hooks.json: tool names ending in
_apply, _write or _undo). It reads the hook's JSON from stdin. A write tool whose
`tool_input.preview_id` is missing, empty or not 12 lower-case hex digits is denied: one JSON
object on stdout with `hookSpecificOutput.permissionDecision: "deny"` and the reason, which
Claude sees. Anything else is allowed silently: exit 0, no output.

Input that cannot be read is denied, unless a tool name in it is plainly not a write tool (the
hook only fires for write tools, so unreadable input is treated as one). The engine checks the
id itself as well; this hook stops the call before it reaches the engine.

Run through uv (no system Python needed): see hooks.json and docs/prompts/plans/W-21.md.
"""

import json
import re
import sys

SERVERS = ("plugin_dj-librarian_dj-librarian", "dj-librarian")
WRITE_TOOL = re.compile(
    r"^mcp__(?:" + "|".join(re.escape(s) for s in SERVERS) + r")__[A-Za-z0-9_]+_(?:apply|write|undo)$"
)
PREVIEW_ID = re.compile(r"^[0-9a-f]{12}$")
TOOL_NAME_IN_TEXT = re.compile(r'"tool_name"\s*:\s*"([^"\\]*)"')

NO_ID = (
    "dj-librarian write gate: {tool} needs the preview_id from its preview tool. Call the preview "
    "tool, show the DJ the result, ask, and call {tool} only after their explicit yes, with that "
    "preview_id."
)
BAD_ID = (
    "dj-librarian write gate: {value!r} is not a preview id (12 lower-case hex digits from the "
    "preview tool). Call the preview tool again and pass the id it returns, after the DJ's yes."
)
UNREADABLE = (
    "dj-librarian write gate: the tool call could not be read, so it is not let through. Call the "
    "preview tool, show the DJ the result, and pass its preview_id after their yes."
)


def is_write_tool(name):
    return isinstance(name, str) and bool(WRITE_TOOL.match(name))


def decide(raw):
    """The reason to deny this tool call, or None to allow it."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        found = TOOL_NAME_IN_TEXT.search(raw or "")
        if found and not is_write_tool(found.group(1)):
            return None
        return UNREADABLE
    name = data.get("tool_name")
    if not isinstance(name, str):
        return UNREADABLE
    if not is_write_tool(name):
        return None
    tool = name.rsplit("__", 1)[-1]
    tool_input = data.get("tool_input")
    value = tool_input.get("preview_id") if isinstance(tool_input, dict) else None
    if value is None or (isinstance(value, str) and not value.strip()):
        return NO_ID.format(tool=tool)
    if not isinstance(value, str) or not PREVIEW_ID.fullmatch(value):  # "$" alone allows a trailing newline
        return BAD_ID.format(value=value)
    return None


def deny_output(reason):
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        reason = decide(raw)
    except Exception:  # never let a crash decide: an unreadable call is denied
        reason = UNREADABLE
    if reason is not None:
        sys.stdout.write(deny_output(reason) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
