#!/usr/bin/env python3
"""Tests for the guards. Run in a temporary folder with a temporary config; touch nothing real."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="guards_test_")
CFG = os.path.join(tmp, "config.json")
fails = []
BASE = {"all": True, "guards": {k: True for k in (
    "P1_landing", "P2_contract", "P3_threads", "P4_ledger", "P5_waiting", "P6_brief", "P7_focus", "P8_reviewer",
    "P11_digit")}, "thread_threshold": 3, "day_starts_at_hour": 5, "installed_on": "2026-01-01"}


def setup(**extra):
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    json.dump(dict(BASE, **extra), open(CFG, "w"))


def run(script, args, data=None, when="2026-01-10T14:00:00", env=None):
    e = dict(os.environ, GUARDS_STATE=os.path.join(tmp, "state"), GUARDS_CONFIG=CFG, GUARDS_NOW=when,
             GUARDS_DESKTOP_META=os.path.join(tmp, "nometa"), **(env or {}))
    p = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                       input=json.dumps(data) if data is not None else None, capture_output=True, text=True, env=e)
    return p.stdout + p.stderr


def prompt(text, sid="s1", when="2026-01-10T14:00:00"):
    return run("guards.py", ["hook", "prompt"], {"prompt": text, "session_id": sid, "transcript_path": "",
                                                 "cwd": "/tmp/proj_" + sid}, when)


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


BLOCK = '"decision": "block"'

setup()
o = prompt("Fix the plot labels please")
check("reply shape comes with a normal message", "reply shape" in o and "NEVER shorten" in o)
check("no landing on a normal message", "LANDING MODE" not in o)

setup(format={"numbered_sentences": True, "max_questions": 2, "open_line": "off", "new_directions": "inline"})
o = prompt("hello")
check("the reply shape follows my own format answers", "Number the sentences" in o and "At most 2 questions" in o
      and "Open:" not in o and "Propose new directions freely" in o)
check("no format setting removes the same-information rule", "NEVER shorten" in o)

for words in ("I am tired, just do it", "ich bin müde", "landing", "done for today"):
    setup()
    check("landing starts on: " + words, "LANDING MODE" in prompt(words))
setup()
check("a quoted stop phrase does not start landing", "LANDING MODE" not in prompt("> I am tired\nwhat did he mean?"))
prompt("I am tired")
check("landing is visible in another session", "LANDING MODE" in prompt("next", sid="s2"))
check("'continue anyway' ends it for the session", "LANDING MODE" not in prompt("continue anyway", sid="s2") + prompt("go", sid="s2"))

setup()
check("'free' switches to free mode", "mode: FREE" in prompt("free"))
check("'carry' switches to carry mode", "mode: CARRY" in prompt("carry"))
check("'focus' switches back", "FOCUS" in prompt("focus"))

setup(thread_block=True)
for i in range(3):
    prompt("work", sid="b%d" % i)
o = prompt("please build the thing", sid="b3")
check("session 4 is held back", BLOCK in o and "free" in o)
o = prompt("free", sid="b3")
check("'free' lifts the block and hands over the held message", "please build the thing" in o and BLOCK not in o)
check("a scheduled task passes", BLOCK not in prompt("<scheduled-task name='x'>run</scheduled-task>", sid="b9"))
check("a session started by another session passes",
      BLOCK not in prompt("Background (from the session that started this one):\nx", sid="b10"))

setup()
for i in range(3):
    prompt("work", sid="n%d" % i)
o = prompt("hello", sid="n3")
check("without thread_block there is only a note", BLOCK not in o and "Which one pauses" in o)

setup(brief_at_start=True)
M = "start brief]"
check("first message asks for the brief", M in prompt("build me a parser", sid="q1"))
check("second message does not", M not in prompt("ok", sid="q1"))
prompt("brief off", sid="q2")
check("'brief off' holds for the day", M not in prompt("build", sid="q3"))
check("and ends the next day", M in prompt("build", sid="q4", when="2026-01-11T10:00:00"))

setup(work_note_hours=1)
seen = [m for m in range(0, 100, 20) if "Time note:" in prompt("x", when="2026-01-10T09:%02d:00" % m if m < 60
                                                                  else "2026-01-10T10:%02d:00" % (m - 60))]
check("time note appears once after the set time", seen == [60])

setup()
o = prompt("guards off")
check("'guards off' confirms", "All guards are off" in o)
check("and nothing is sent afterwards", prompt("hello").strip() == "")
check("'guards on' brings them back", "reply shape" in prompt("guards on"))

setup(guards=dict(BASE["guards"], P2_contract=False, P7_focus=False, P5_waiting=False, P8_reviewer=False))
o = prompt("hello")
check("a guard that is off for me sends nothing", "reply shape" not in o and "FOCUS" not in o)

setup()
o = run("guards.py", ["hook", "posttool"], {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
                                            "tool_response": {"stdout": "[main abc] x"}})
check("a commit asks for a ledger entry", "built-ledger" in o)
p = subprocess.run([sys.executable, os.path.join(HERE, "guards.py"), "hook", "prompt"], input="not json",
                   capture_output=True, text=True, env=dict(os.environ, GUARDS_STATE=tmp, GUARDS_CONFIG=CFG))
check("broken input never breaks a session", p.returncode == 0 and p.stdout.strip() == "")

# install.py on a temporary settings file that already has someone else's hook
st = os.path.join(tmp, "settings.json")
json.dump({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo other"}]}]}, "theme": "x"},
          open(st, "w"))
json.dump(BASE, open(os.path.join(HERE, "config.json.selftest"), "w"))
run("install.py", ["--show"])
env = {"GUARDS_SETTINGS": st}
had_cfg = os.path.exists(os.path.join(HERE, "config.json"))
if not had_cfg:
    check("install refuses before my own assessment", "No config.json yet" in run("install.py", [], env=env))
    shutil.copy(os.path.join(HERE, "config.json.selftest"), os.path.join(HERE, "config.json"))
run("install.py", [], env=env)
s = json.load(open(st))
check("install adds three hooks and keeps the other one", len(s["hooks"]["SessionStart"]) == 2
      and "UserPromptSubmit" in s["hooks"] and s["theme"] == "x")
run("install.py", ["--remove"], env=env)
s = json.load(open(st))
check("remove takes only ours out", s["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "echo other"
      and "UserPromptSubmit" not in s["hooks"] and not s["permissions"]["allow"])
if not had_cfg:
    os.remove(os.path.join(HERE, "config.json"))
os.remove(os.path.join(HERE, "config.json.selftest"))

shutil.rmtree(tmp, ignore_errors=True)
print("\n{} failed".format(len(fails)) if fails else "\nall passed")
sys.exit(1 if fails else 0)
