#!/usr/bin/env python3
"""Install or remove the hooks in ~/.claude/settings.json. Standard library only.

  install.py            add the three hooks and the permissions (backup first). Needs config.json,
                        which only `assess.py accept` creates: nothing is installed before my own assessment.
  install.py --remove   take them out again (backup first). My config and state stay in this folder.
  install.py --show     print what would be added, change nothing.

It touches nothing else: no CLAUDE.md, no other hooks, no other settings.
"""
import datetime as dt
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.environ.get("GUARDS_SETTINGS") or os.path.expanduser("~/.claude/settings.json")
ME = "python3 " + os.path.join(HERE, "guards.py")
EVENTS = {"UserPromptSubmit": ("prompt", None), "SessionStart": ("start", None), "PostToolUse": ("posttool", "Bash")}
PERMS = ["Bash({} add:*)".format(ME), "Bash({} threads)".format(ME), "Bash({} built:*)".format(ME),
         "Bash({} review)".format(ME), "Bash({} status)".format(ME),
         "Bash(python3 {})".format(os.path.join(HERE, "reeval.py"))]


def ours(entry):
    return any(os.path.join(HERE, "guards.py") in (h.get("command") or "") for h in entry.get("hooks", []))


def load():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(s):
    if os.path.exists(SETTINGS):
        bak = SETTINGS + ".before_guards_" + dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        shutil.copy2(SETTINGS, bak)
        print("Backup:", bak)
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS + ".tmp", "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(SETTINGS + ".tmp", SETTINGS)


def strip(s):
    for ev in list(s.get("hooks", {})):
        s["hooks"][ev] = [e for e in s["hooks"][ev] if not ours(e)]
        if not s["hooks"][ev]:
            del s["hooks"][ev]
    allow = s.get("permissions", {}).get("allow")
    if allow is not None:
        s["permissions"]["allow"] = [p for p in allow if p not in PERMS]
    return s


def add(s):
    strip(s)
    for ev, (name, matcher) in EVENTS.items():
        e = {"hooks": [{"type": "command", "command": ME + " hook " + name, "timeout": 10}]}
        if matcher:
            e["matcher"] = matcher
        s.setdefault("hooks", {}).setdefault(ev, []).append(e)
    s.setdefault("permissions", {}).setdefault("allow", []).extend(PERMS)
    return s


def main():
    a = sys.argv[1:]
    if "--show" in a:
        print(json.dumps(add({}), indent=2))
    elif "--remove" in a:
        save(strip(load()))
        print("Hooks removed. New sessions run without guards. My config and state are still in", HERE)
    else:
        if not os.path.exists(os.path.join(HERE, "config.json")):
            print("No config.json yet. Run `python3 assess.py`, look at PROFILE.md, then `python3 assess.py accept`.")
            sys.exit(1)
        save(add(load()))
        print("Hooks installed. They apply to sessions started from now on.")
        print("Off at any time: type `guards off` in a session. Remove: python3 install.py --remove")
        print("What is active:", os.path.join(HERE, "ACTIVE.md"))


if __name__ == "__main__":
    main()
