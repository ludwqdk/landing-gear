#!/usr/bin/env python3
"""Guards for working with Claude Code: small hooks that change how Claude behaves towards one person.
Which guards are on, and with which values, comes from that person's own assessment (assess.py).
One file, standard library only.

Hooks (called by Claude Code, read JSON on stdin, print context on stdout):
  guards.py hook prompt     UserPromptSubmit
  guards.py hook start      SessionStart
  guards.py hook posttool   PostToolUse (Bash)

Commands for the human or for Claude:
  guards.py status                 what is active
  guards.py on|off [GUARD]         switch everything, or one guard (e.g. P1)
  guards.py threads                open threads behind the numbers
  guards.py built [DAYS] [PROJECT] ledger of what was built
  guards.py add KIND TEXT          KIND = review | parking | handoff | built
  guards.py review                 show tomorrow's review list
  guards.py settings               print the settings.json block for installing
  reeval.py                        (separate file) re-evaluation: did the guards help?
  guards.py selftest               run the built-in tests

A hook must never break a session: every error ends in exit code 0 and silence.
Nothing here sends data anywhere. The log keeps times and session ids, no message text.
"""
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("GUARDS_STATE") or os.path.join(HERE, "state")
CONFIG = os.environ.get("GUARDS_CONFIG") or os.path.join(HERE, "config.json")
LOG = os.path.join(STATE, "prompts.tsv")
LANDING = os.path.join(STATE, "landing.json")
MODES = os.path.join(STATE, "modes.json")
EVENTS = os.path.join(STATE, "events.log")
REVIEW = os.path.join(STATE, "review_queue.md")
PARKING = os.path.join(STATE, "parking.md")
BUILT = os.path.join(STATE, "built.md")
HANDOFF_DIR = os.path.join(STATE, "handoff")
MOOD = os.path.join(STATE, "day_digit.csv")
ACTIVE = os.path.join(HERE, "ACTIVE.md")
ME = "python3 " + os.path.join(HERE, "guards.py")
REEVAL = "python3 " + os.path.join(HERE, "reeval.py")
REEVAL_RUNS = os.path.join(STATE, "reeval_runs.log")
BRIEF_OFF = os.path.join(STATE, "brief_off.json")
WORKNOTE = os.path.join(STATE, "worknote.json")

NAMES = {
    "P1_landing": "Landing mode: my own stop words ('I am tired', 'done for today') stop new work and save the state",
    "P2_contract": "Reply shape: built from my answers in the setup (config 'format'); never cuts content",
    "P3_threads": "Thread limit: a new session beyond my own limit per hour gets a note, or is held until I type 'free'",
    "P4_ledger": "Built-ledger: three lines per commit in one central file",
    "P5_waiting": "Waiting: Claude says when a job ends and what it needs from you",
    "P6_brief": "Start brief: five fields at the start of every new session (skip with 'brief off')",
    "P7_focus": "Focus by default, free mode with the word 'free'",
    "P8_reviewer": "Second reader at milestones",
    "P11_digit": "One digit at the end of a day (1 to 5)",
}


# ---------- small helpers ----------

def now():
    t = os.environ.get("GUARDS_NOW")
    return dt.datetime.fromisoformat(t) if t else dt.datetime.now()


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def append(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(line.rstrip("\n") + "\n")


def cfg():
    return load(CONFIG, {"all": True, "guards": {k: True for k in NAMES}})


def on(c, key):
    return bool(c.get("all", True)) and bool(c.get("guards", {}).get(key, False))


def text(name):
    try:
        with open(os.path.join(HERE, "text", name)) as f:
            return f.read().strip()
    except Exception:
        return ""


def contract_text(c):
    """The reply shape, built from the person's own answers (config 'format'). Shape only: the head line
    forbids cutting content, and no setting here can switch that off."""
    f = c.get("format") or {}
    r = ["First line: the answer or result{}, one sentence.".format(", in bold" if f.get("bold_first", True) else "")]
    if f.get("needs_you_line", True):
        r.append('Second line: "Needs you: nothing" or "Needs you: 1 decision (below)" or "Needs you: your eyes on X".')
    if f.get("open_line", "top") in ("top", "bottom"):
        r.append('{}: "Open: … · Next: …" (write "none" if empty).'.format(
            "Next line" if f.get("open_line", "top") == "top" else "Last line"))
    q = int(f.get("max_questions", 1))
    if q > 0:
        r.append("At most {} question{} per reply. No option menus for small things.".format(q, "" if q == 1 else "s"))
    if f.get("short_sentences"):
        r.append("Short sentences. One piece of information per sentence.")
    if f.get("numbered_sentences"):
        r.append("Number the sentences, continuing the numbering through the whole session.")
    if f.get("decide_small_things", True):
        r.append('Small reversible choices: decide yourself, list them under "Defaults I chose (change any)".')
    r.append("Costly or irreversible actions (delete, overwrite, cancel or start a long job, copy large data, push, "
             "install, change settings): ask first, wait for the answer, give no \"recommended\" label. Do only "
             "what was asked; anything beyond it is a proposal, not an action.")
    nd = f.get("new_directions", "block")
    if nd == "block":
        r.append('Your own new ideas and offers: one "Parking:" block at the end, in full, as statements, not '
                 'questions. Do not hold ideas back: the user wants them, in one place.')
    elif nd == "inline":
        r.append("Propose new directions freely wherever they help. The user asked for this explicitly.")
    if f.get("check_marks", True):
        r.append('Every "done"/"works"/"fixed" claim carries a mark: "checked: <how>" or "not checked" or '
                 '"needs your eyes" (anything you cannot see).')
    r.append("Then the full details, complete, in short blocks with one idea each.")
    if f.get("language"):
        r.append("Write in {}.".format(f["language"]))
    head = ("[guard · reply shape · re-sent with every message so it cannot wear off]\n"
            "Shape of every reply to this user. They chose it themselves. This changes order and shape only. "
            "NEVER shorten or drop content to comply: the user must get the same information as anyone else.\n")
    return head + "\n".join("{}. {}".format(i + 1, x) for i, x in enumerate(r))


def workday(t, c):
    """The day a moment belongs to. 02:00 at night still belongs to the day before."""
    return (t - dt.timedelta(hours=int(c.get("day_starts_at_hour", 5)))).date()


def event(msg):
    append(EVENTS, now().strftime("%Y-%m-%d %H:%M") + "  " + msg)


# ---------- P1: phrases ----------

def phrases():
    """My stop phrases: phrases/<language>.txt for every language in config 'languages' (default: all files),
    plus phrases/mine.txt, which the setup fills with the words I actually use."""
    out = []
    langs = cfg().get("languages")
    d = os.path.join(HERE, "phrases")
    try:
        for name in sorted(os.listdir(d)):
            if not name.endswith(".txt") or (langs and name[:-4] not in list(langs) + ["mine"]):
                continue
            with open(os.path.join(d, name)) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        out.append(line.lower())
    except Exception:
        pass
    return out


def own_words(prompt):
    """The user's own typing: no quoted lines, no code blocks, no pasted blocks, no tags."""
    p = re.sub(r"<pasted_content.*?</pasted_content[^>]*>", " ", prompt, flags=re.S)
    p = re.sub(r"```.*?```", " ", p, flags=re.S)
    p = re.sub(r"<!--.*?-->", " ", p, flags=re.S)
    p = re.sub(r"<[^>\n]{1,80}>", " ", p)
    lines = [l for l in p.splitlines() if not l.lstrip().startswith(">")]
    return "\n".join(lines)


def find_phrase(prompt):
    p = own_words(prompt).lower().replace("’", "'")
    if len(p) > 4000:  # a long brief is not a sigh
        return None
    for ph in phrases():
        pat = r"(?<!\w)" + r"\s+".join(re.escape(w).replace(r"\*", r"\w*") for w in ph.split()) + r"(?!\w)"
        m = re.search(pat, p)
        if m:
            return re.sub(r"\s+", " ", m.group(0))
    return None


def landing_state(c):
    st = load(LANDING, {})
    if st and st.get("workday") == str(workday(now(), c)):
        return st
    return {}


# ---------- P3: threads ----------

def read_log(hours):
    rows = []
    cut = now() - dt.timedelta(hours=hours)
    try:
        with open(LOG) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 4:
                    continue
                try:
                    t = dt.datetime.fromisoformat(parts[0])
                except Exception:
                    continue
                if t >= cut:
                    rows.append((t, parts[1], parts[2], parts[3]))
    except Exception:
        pass
    return rows


def tail_state(path):
    """Look at the end of a transcript: 'runs', 'waits', or 'idle'. A guess, by design."""
    try:
        age = time.time() - os.path.getmtime(path)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 120_000))
            chunk = f.read().decode("utf-8", "ignore")
    except Exception:
        return "idle", ""
    last_text, asks = "", False
    for line in chunk.splitlines()[-60:]:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("isSidechain"):
            continue
        if r.get("type") == "assistant":
            content = (r.get("message") or {}).get("content") or []
            if isinstance(content, list):
                for b in content:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        last_text = b["text"].strip()
                        asks = False
                    if b.get("type") == "tool_use" and b.get("name") in ("AskUserQuestion", "ExitPlanMode"):
                        asks = True
        elif r.get("type") == "user":
            content = (r.get("message") or {}).get("content")
            if isinstance(content, str):
                last_text, asks = "", False
    if not os.environ.get("GUARDS_NOW") and age < 120:
        return "runs", last_text
    if asks or last_text.rstrip("*_ \n").endswith("?"):
        return "waits", last_text
    return "idle", last_text


def streak(c):
    days = set()
    try:
        with open(LOG) as f:
            for line in f:
                try:
                    days.add(workday(dt.datetime.fromisoformat(line.split("\t", 1)[0]), c))
                except Exception:
                    pass
    except Exception:
        pass
    today = workday(now(), c)
    if today not in days:
        return 0
    n, d = 0, today
    while d in days:
        n += 1
        d -= dt.timedelta(days=1)
    # Days before the log began: known from Phase 1 (no day without use since the seed date).
    seed, inst = c.get("streak_seed_start"), c.get("installed_on")
    if seed and inst:
        try:
            first_logged = min(days)
            inst_d = dt.date.fromisoformat(inst)
            if d < first_logged and first_logged <= inst_d + dt.timedelta(days=1):
                n += max(0, (first_logged - dt.date.fromisoformat(seed)).days)
        except Exception:
            pass
    return n


def thread_numbers(c):
    rows = read_log(24)
    t = now()
    hour = {sid for (ts, sid, _, _) in rows if ts >= t - dt.timedelta(hours=1)}
    latest = {}
    for ts, sid, path, cwd in rows:
        latest[sid] = (ts, path, cwd)
    states = {sid: tail_state(p)[0] for sid, (_, p, _) in latest.items()}
    today = [ts for (ts, _, _, _) in read_log(30) if workday(ts, c) == workday(t, c)]
    hrs = (t - min(today)).total_seconds() / 3600 if today else 0
    return {
        "active": len(hour),
        "waits": sum(1 for s in states.values() if s == "waits"),
        "runs": sum(1 for s in states.values() if s == "runs"),
        "hours": hrs,
        "streak": streak(c),
        "latest": latest,
        "states": states,
    }


def thread_line(n):
    return "{} active in the last hour · {} wait for you · {} run · {:.0f} h today · day {} in a row · {}".format(
        n["active"], n["waits"], n["runs"], n["hours"], n["streak"], now().strftime("%H:%M"))


# ---------- P3: the block ----------

FREE_WORDS = ("frei", "frei an", "free", "free on", "free mode", "explore")
CARRY_WORDS = ("carry", "carry me", "trag mich", "take over", "übernimm")
LAND_WORDS = ("landung", "landen", "landing", "land", "schluss", "schluss für heute", "feierabend",
              "stop für heute", "genug für heute", "done for today")


def stale_blocks(modes):
    """A session that was held back and never released for 15 minutes goes on the review list, once.
    This is how a blocked automatic session becomes visible."""
    for sid, m in modes.items():
        try:
            if m.get("held") and m.get("held_at") and not m.get("reported") and \
                    (now() - dt.datetime.fromisoformat(m["held_at"])).total_seconds() > 900:
                m["reported"] = True
                append(REVIEW, "- [ ] {} · guards · Session {} in '{}' was held back by the session block at {} "
                               "and never released. If nobody was typing there, it was an automatic session: "
                               "open it and type frei.".format(now().strftime("%Y-%m-%d %H:%M"), sid[:8],
                                                               m.get("held_cwd", "?"), m["held_at"][11:16]))
                event("held session {} put on the review list".format(sid[:8]))
        except Exception:
            pass
DESKTOP_META = os.environ.get("GUARDS_DESKTOP_META") or os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code-sessions")


def automated(sid, prompt):
    """Sessions that no human can unblock (scheduled tasks, sessions started by another session) pass.
    Live test 2026-11-21: the desktop app writes a started session's file only AFTER its first message
    reaches this hook. So: known openings of such messages first, then look for the file for a few seconds."""
    p = prompt.lstrip()
    if p.startswith(("<scheduled-task", "<task-notification", "Background (from the session that started this one)")):
        return True
    import glob
    for attempt in range(7):
        try:
            files = sorted(glob.glob(os.path.join(DESKTOP_META, "*", "*", "local_*.json")),
                           key=os.path.getmtime, reverse=True)[:60]
            for f in files:
                d = load(f, {})
                mine = d.get("cliSessionId") == sid or sid in (d.get("priorCliSessionIds") or [])
                # a file a few seconds old, started by another session or a schedule, not yet tied to a session id
                newborn = not d.get("cliSessionId") and time.time() - os.path.getmtime(f) < 20
                if mine or newborn:
                    if d.get("spawnedFrom") or d.get("scheduledTaskId"):
                        return True
                    if mine:
                        return False
        except Exception:
            pass
        if os.environ.get("GUARDS_NOW") or attempt == 6:
            break
        time.sleep(0.5)
    return False


def block_text(c, n, thr):
    lines = ["Guard P3: this would be session {} within one hour. Your own limit is {}.".format(n["active"] + 1, thr),
             "Your message was NOT sent to Claude. It is kept and goes through as soon as you type:  free", "",
             thread_line(n)]
    for sid, (ts, path, cwd) in sorted(n["latest"].items(), key=lambda kv: kv[1][0], reverse=True)[:8]:
        lines.append("  {:5}  {}  {}".format(n["states"].get(sid, ""), ts.strftime("%H:%M"), os.path.basename(cwd)[:40]))
    lines += ["", "Or close this session and continue in one of those. Off switch: guards off."]
    return "\n".join(lines)


# ---------- time note: how long have I been at it today ----------

def active_hours(c):
    """Hours of work with Claude today: time between my messages, pauses over 30 minutes not counted."""
    today = workday(now(), c)
    ts = sorted(t for (t, _, _, _) in read_log(30) if workday(t, c) == today)
    secs = sum(min((b - a).total_seconds(), 1800) for a, b in zip(ts, ts[1:]) if (b - a).total_seconds() <= 1800)
    return secs / 3600, (ts[0] if ts else None), len({s for (t, s, _, _) in read_log(30) if workday(t, c) == today})


def work_note(c):
    """One line, once each time another `work_note_hours` of active work is reached. No advice, no question."""
    every = float(c.get("work_note_hours") or 0)
    if every <= 0:
        return None
    hrs, first, nsess = active_hours(c)
    if now().hour >= 23 or now().hour < 5:  # at night the note comes more often
        every = float(c.get("work_note_hours_night") or every) - 0.01  # 20 min steps must not miss by rounding
    st = load(WORKNOTE, {})
    day = str(workday(now(), c))
    if st.get("workday") != day:
        st = {"workday": day, "last_at": 0.0}
    if hrs - float(st.get("last_at", 0.0)) < every:
        return None
    st["last_at"] = round(hrs, 2)
    save(WORKNOTE, st)
    event("time note: {:.1f} h active today".format(hrs))
    return ("[guards · time note] Show this line once, as it is, as the first line of your reply, then answer "
            "normally. No advice, no question, no comment about it: \"Time note: {:.1f} h of work with Claude "
            "today (first message {}, {} sessions, pauses over 30 min not counted). Now {}.\""
            .format(hrs, first.strftime("%H:%M"), nsess, now().strftime("%H:%M")))


# ---------- Phase 3: re-evaluation ----------

def reeval_due(c):
    """Days since the last re-evaluation (or since the install), if that is at least `reeval_every_days`.
    Off unless that key is set in config.json."""
    every = c.get("reeval_every_days")
    if not every:
        return None
    last = c.get("installed_on")
    try:
        with open(REEVAL_RUNS) as f:
            for line in f:
                if line[:10] > (last or ""):
                    last = line[:10]
    except Exception:
        pass
    try:
        days = (now().date() - dt.date.fromisoformat(last)).days
    except Exception:
        return None
    return (days, last) if days >= int(every) else None


# ---------- hooks ----------

def hook_prompt(data):
    c = cfg()
    prompt = data.get("prompt") or ""
    sid = data.get("session_id") or "?"
    word = re.sub(r"[.!\s]+$", "", prompt.strip().lower())
    out = []

    # P0: the switch also works as a chat message.
    if word in ("guards off", "guards aus"):
        c["all"] = False
        save(CONFIG, c)
        write_active(c)
        event("all guards OFF (typed in chat)")
        print("[guards] The user switched ALL guards off by typing 'guards off'. Confirm in one line: "
              "'All guards are off. Type guards on to switch them back on.' Then stop.")
        return
    if word in ("guards on", "guards an"):
        c["all"] = True
        save(CONFIG, c)
        write_active(c)
        event("all guards ON (typed in chat)")
        out.append("[guards] The user switched the guards back on. Confirm in one line and name them: "
                   + ", ".join(k.split("_")[0] for k in NAMES if on(c, k)) + ".")
    if not c.get("all", True):
        return

    t = now()
    before = {s for (ts, s, _, _) in read_log(1)}

    # P3: a new session beyond the limit does not take the message until the user types 'frei'.
    modes = load(MODES, {})
    mine = modes.get(sid, {})
    released = None
    thr = int(c.get("thread_threshold", 3))
    if on(c, "P3_threads") and c.get("thread_block") and sid not in before and len(before) >= thr \
            and not mine.get("admitted"):
        if word in FREE_WORDS:
            mine["admitted"] = True
            released = mine.pop("held", None)
            event("block lifted with '{}' in {}".format(word, sid[:8]))
        elif not automated(sid, prompt):
            n = thread_numbers(c)
            if not mine.get("held"):
                event("BLOCKED session {} ({} active)".format(sid[:8], n["active"]))
            mine["held"] = prompt[:20000]
            mine.setdefault("held_at", t.isoformat(timespec="seconds"))
            mine["held_cwd"] = os.path.basename(data.get("cwd") or "")
            modes[sid] = mine
            save(MODES, modes)
            print(json.dumps({"decision": "block", "reason": block_text(c, n, thr)}))
            return
        else:
            mine["admitted"] = True
            event("automated session {} passed the block".format(sid[:8]))
    stale_blocks(modes)
    append(LOG, "\t".join([t.isoformat(timespec="seconds"), sid,
                           data.get("transcript_path") or "", data.get("cwd") or ""]))

    if released:
        out.append("[guard P3 · block lifted] This session was over the user's limit of sessions per hour. The "
                   "user typed 'frei' to work here anyway; accept that without comment. Their first message was "
                   "held back by the guard and was never shown to you. Here it is, word for word. Answer it now "
                   "as if it had just been sent:\n\n<held_message>\n" + released + "\n</held_message>")

    # P0: for the first days, show the guide with the first message of every session.
    until = c.get("guide_until")
    if until and str(t.date()) <= until and not mine.get("guide_shown"):
        g = text("guide.md").replace("{until}", until)
        if g:
            out.append("[guards · guide] This is the user's first message in this session. The user asked to see "
                       "the following guide at the start of every session until " + until + ". Print it once, word "
                       "for word, as the first thing in your reply (after the 'Guards active' line if there is one), "
                       "then answer the message normally. Do not print it again in this session.\n\n" + g)
        mine["guide_shown"] = True

    # Phase 3: the re-evaluation as one word.
    if word in ("reeval", "re-eval", "auswertung"):
        out.append("[guards · re-evaluation] The user typed '{w}'. Run `{r}` now and show its printed summary "
                   "completely, in the reply shape below. If it says there is no rating yet, ask as the single "
                   "question of this reply for three digits from 1 (bad) to 5 (good): was I able to work nicely, "
                   "was AI still very useful, did I feel good using it; then store them with `{r} answer W U F`. "
                   "Change no guard on your own; changes are proposals.".format(w=word, r=REEVAL))

    # P6: every new session starts with the brief. 'brief off' switches that off for the rest of the day,
    # in all sessions; the next day it is on again by itself. 'brief on' switches it back on at once.
    if on(c, "P6_brief") and c.get("brief_at_start"):
        today = str(workday(t, c))
        own = [l.strip().lower().rstrip(".!") for l in own_words(prompt).splitlines() if l.strip()]
        off_today = load(BRIEF_OFF, {}).get("workday") == today
        if "brief off" in own or "brief aus" in own:
            save(BRIEF_OFF, {"workday": today})
            off_today = True
            event("start brief OFF for today (typed in " + sid[:8] + ")")
            out.append("[guard P6] The user wrote 'brief off'. The start brief is off for the rest of today in all "
                       "sessions and comes back by itself tomorrow. Say exactly that in one line, add 'Back on "
                       "earlier: brief on', and if the message contains more than that, answer the rest normally.")
        elif word in ("brief on", "brief an"):
            save(BRIEF_OFF, {})
            off_today = False
            mine["brief_done"] = True
            event("start brief ON again (typed in " + sid[:8] + ")")
            out.append("[guard P6] The user wrote 'brief on'. The start brief is on again for new sessions. "
                       "Confirm in one line.")
        if not mine.get("brief_done"):
            control = word in FREE_WORDS + ("fokus", "focus", "frei aus", "free off", "back", "weiter",
                                            "weitermachen", "continue anyway", "reeval", "re-eval", "auswertung",
                                            "guards on", "guards an") + LAND_WORDS + CARRY_WORDS or re.fullmatch(r"[1-5]", word or "")
            old = False
            try:
                st = os.stat(data.get("transcript_path") or "")
                old = time.time() - getattr(st, "st_birthtime", st.st_mtime) > 900 \
                    and not os.environ.get("GUARDS_NOW")
            except Exception:
                pass
            if off_today or old or word in ("brief", "start brief") or automated(sid, prompt):
                mine["brief_done"] = True
            elif not control or released:
                mine["brief_done"] = True
                out.append("[guard P6 · start brief] The user wants every new session to start with the brief. "
                           "This is the first working message of this session{}. Before doing any work on it, use "
                           "the `brief` skill: ask its five fields in ONE numbered list (Goal, Done when, Stop "
                           "points, Not in scope, Landing for today). Fill in what the message already says, so "
                           "the user only confirms or corrects; every field may be skipped with '-'. This is the "
                           "single question of this reply. Start the work only after the user answered; any "
                           "answer counts, also 'ok' or '-'. Tell the user in one line: 'Off for today: brief off'."
                           .format(" (the held message below)" if released else ""))

    # P11: a single digit answers the day question.
    land = landing_state(c) if on(c, "P1_landing") else {}
    if on(c, "P11_digit") and land.get("digit_pending") and re.fullmatch(r"[1-5]", word or ""):
        append(MOOD, "{},{},{}".format(land["workday"], word, t.strftime("%H:%M")))
        land["digit_pending"] = False
        save(LANDING, land)
        out.append("[guard P11] The digit {} was saved as today's rating. Confirm with one short line. "
                   "Do not comment on the number.".format(word))

    # P7: mode words.
    if on(c, "P7_focus"):
        if word in FREE_WORDS:
            mine["mode"] = "free"
            event("free mode on in " + sid[:8])
        elif word in CARRY_WORDS:
            mine["mode"] = "carry"
            event("carry mode on in " + sid[:8])
        elif word in ("fokus", "focus", "frei aus", "free off", "back"):
            mine["mode"] = "focus"
            event("focus mode on in " + sid[:8])

    # P1: landing.
    if on(c, "P1_landing"):
        if word in ("weiter", "continue anyway", "weitermachen") and land:
            mine["landing_override"] = land["workday"]
            event("landing overridden with 'weiter' in " + sid[:8])
            out.append("[guard P1] The user typed 'weiter'. Landing mode is off for this session. "
                       "Confirm in one line and continue normally. No comment, no warning.")
        else:
            hit = find_phrase(prompt)
            if word in LAND_WORDS:  # landing as a command, not only as a sigh
                hit = word
            if hit and not land:
                land = {"workday": str(workday(t, c)), "since": t.strftime("%H:%M"), "phrase": hit,
                        "sid": sid, "digit_pending": on(c, "P11_digit"), "ask_digit_in": sid}
                save(LANDING, land)
                event("landing ON, phrase '{}' in {}".format(hit, sid[:8]))
        if land and mine.get("landing_override") != land["workday"]:
            where = "" if land.get("sid") == sid else " in another session"
            out.append(text("landing.md").replace("{since}", land["since"])
                       .replace("{phrase}", land["phrase"]).replace("{where}", where))
            if on(c, "P11_digit") and land.get("digit_pending") and land.get("ask_digit_in") == sid \
                    and not land.get("digit_asked"):
                out.append("[guard P11] As the single allowed question of this reply, ask at the very end: "
                           "'{}' (1 = bad day with AI, 5 = good day). Ask it once only."
                           .format(c.get("digit_question", "Today, 1 to 5?")))
                land["digit_asked"] = True
                save(LANDING, land)

    modes[sid] = mine
    if len(modes) > 400:
        modes = dict(list(modes.items())[-200:])
    save(MODES, modes)

    note = work_note(c)
    if note:
        out.insert(0, note)

    # P2, P5, P8: the standing rules.
    if on(c, "P2_contract"):
        out.append(contract_text(c))
    if on(c, "P5_waiting"):
        out.append(text("waiting.md"))
    if on(c, "P8_reviewer"):
        out.append(text("reviewer.md"))
    if on(c, "P7_focus"):
        out.append(text({"free": "free.md", "carry": "carry.md"}.get(mine.get("mode"), "focus.md")))

    # P3: say the number once when this session pushes the count over the threshold.
    if on(c, "P3_threads"):
        if sid not in before and len(before) >= thr and not c.get("thread_block"):
            n = thread_numbers(c)
            event("threshold crossed: {} active".format(n["active"]))
            out.append("[guard P3 · threads] This is session number {} the user has written in during the last "
                       "hour (their own limit is {}). Show this line once, as it is, before your answer: \"{}\". "
                       "Then ask, as the single question of this reply: 'Which one pauses?'. 'None' is a valid "
                       "answer; accept it without comment. Then answer the message normally."
                       .format(n["active"], thr, thread_line(n)))

    if any(on(c, k) for k in ("P1_landing", "P4_ledger", "P7_focus", "P5_waiting")):
        out.append("[guards · commands] To store things use: `{me} add review \"…\"` (tomorrow's review list), "
                   "`{me} add parking \"…\"` (parked ideas), `{me} add handoff \"…\"` (state of this session), "
                   "`{me} add built \"…\"` (ledger). When a guard makes you act differently, say so in one line."
                   .format(me=ME))
    print("\n\n".join(x for x in out if x))


def hook_start(data):
    c = cfg()
    if not c.get("all", True):
        return
    if (data.get("source") or "startup") not in ("startup", "clear"):
        return
    active = [k.split("_")[0] for k in NAMES if on(c, k)]
    out = ["[guards · session start] Begin your FIRST reply in this session with exactly this one line, then answer "
           "normally: \"Guards active: {} ({}). Off: type guards off. Why they exist → {}/PROFILE.md · list → {}\""
           .format(len(active), " ".join(active), HERE, ACTIVE)]
    if on(c, "P3_threads"):
        out.append("[guard P3] Add this as a second line: \"{}\"".format(thread_line(thread_numbers(c))))
    due = reeval_due(c)
    if due:
        out.append("[guards · re-evaluation] Add as a further line: \"Re-evaluation is due: last check {} "
                   "({} days ago). Type reeval to run it (about ten seconds).\"".format(due[1], due[0]))
    land = landing_state(c) if on(c, "P1_landing") else {}
    if land:
        out.append("[guard P1] Add as a further line: \"At {} you wrote '{}'. Landing mode is on; type continue anyway to "
                   "work normally here.\"".format(land["since"], land["phrase"]))
    elif os.path.exists(REVIEW) and os.path.getsize(REVIEW) > 0:
        try:
            with open(REVIEW) as f:
                items = [l for l in f if l.startswith("- [ ]")]
        except Exception:
            items = []
        if items:
            out.append("[guard P1] Add as a further line: \"Review list from earlier: {} open items → {}\". "
                       "Do not read them out unless asked.".format(len(items), REVIEW))
    print("\n\n".join(out))


def hook_posttool(data):
    c = cfg()
    if not on(c, "P4_ledger"):
        return
    cmd = ((data.get("tool_input") or {}).get("command") or "")
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd) or "--dry-run" in cmd:
        return
    resp = json.dumps(data.get("tool_response") or "")[:4000].lower()
    if "nothing to commit" in resp or "nothing added to commit" in resp:
        return
    msg = ("[guard P4 · built-ledger] You just committed. Before your reply, record it with ONE command: "
           "`{me} add built \"<project> | what changed (one line) | why (one line) | checked: <how> or not checked"
           " | decided on the user's behalf: <list or none>\"`. Plain words, as you would explain it to the "
           "user's colleague. For several commits in a row, one entry per commit.").format(me=ME)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))


# ---------- commands ----------

def write_active(c):
    lines = ["# ACTIVE — which guards change how Claude behaves", "",
             "Written by `guards.py`. Last change: " + now().strftime("%Y-%m-%d %H:%M") + ".", "",
             "**Everything: " + ("ON" if c.get("all", True) else "OFF") + "**", "",
             "| Guard | State | What it does |", "|---|---|---|"]
    for k, v in NAMES.items():
        st = "on" if on(c, k) else "off"
        lines.append("| {} | {} | {} |".format(k.split("_")[0], st, v))
    lines += ["",
              "## Switch off", "",
              "- Everything: type `guards off` as a message in any Claude Code session. Back on: `guards on`.",
              "- One guard: `{} off P1` in a terminal (or ask Claude to run it).".format(ME),
              "- Remove completely: run `python3 install.py --remove` in this folder.",
              "",
              "## Words you can type as a whole message", "",
              "- `landing` (also `done for today`, `schluss`, `feierabend`) — landing mode on, as a command.",
              "- `continue anyway` (or `weiter`) — landing mode off for this session.",
              "- `free` / `focus` (or `frei` / `fokus`) — free mode on / off for this session. `free` also lifts the "
              "session block.",
              "- `carry` — I am tired: Claude takes the small decisions and carries the task. `focus` ends it.",
              "- `guards off` / `guards on` — everything.",
              "- `brief off` — no start brief for the rest of today, in all sessions; on again tomorrow by itself. "
              "`brief on` — back on at once.",
              "- `reeval` — run the re-evaluation: did the guards help? ({}).".format(
                  "a reminder line appears every {} days".format(c["reeval_every_days"])
                  if c.get("reeval_every_days") else "no reminder is set"),
              "",
              "## Also running", "",
              "- Session block: {}.".format("on" if c.get("thread_block") else "off (only a note)"),
              "- Start brief in every new session: {}.".format("on" if c.get("brief_at_start") else "off"),
              "- Time note in the chat: {}.".format("every {} h of work with Claude in a day, every {:.0f} minutes "
                  "between 23:00 and 05:00".format(c["work_note_hours"], 60 * float(c.get(
                      "work_note_hours_night", c["work_note_hours"])))
                  if c.get("work_note_hours") else "off"),
              "- Change these in `{}/config.json` (`thread_block`, `brief_at_start`, `work_note_hours`, `work_note_hours_night`).".format(HERE),
              "",
              "## Where things are (all in one folder)", "",
              "- Why this exists, and what my assessment found: `{}/PROFILE.md`".format(HERE),
              "- Re-evaluation reports: `{}/reports/reeval_DATE.md`".format(HERE),
              "- Review list for the next day: `{}`".format(REVIEW),
              "- Parked ideas: `{}`".format(PARKING),
              "- What was built: `{}`".format(BUILT),
              "- Session states saved at landing: `{}/`".format(HANDOFF_DIR),
              "- What the guards did and when: `{}`".format(EVENTS),
              "- My stop phrases (edit freely): `{}/phrases/`".format(HERE),
              "- The rules sent to Claude, word for word: `{}/text/`".format(HERE), ""]
    with open(ACTIVE, "w") as f:
        f.write("\n".join(lines))


def cmd_switch(state, which):
    c = cfg()
    if which:
        keys = [k for k in NAMES if k.split("_")[0].lower() == which.lower()]
        if not keys:
            print("Unknown guard:", which, "· known:", " ".join(k.split("_")[0] for k in NAMES))
            return
        c.setdefault("guards", {})[keys[0]] = state
        event("{} {}".format(keys[0], "ON" if state else "OFF"))
    else:
        c["all"] = state
        event("all guards {}".format("ON" if state else "OFF"))
    save(CONFIG, c)
    write_active(c)
    cmd_status()


def cmd_status():
    c = cfg()
    print("Everything:", "ON" if c.get("all", True) else "OFF")
    for k, v in NAMES.items():
        print("  {:4} {:3}  {}".format(k.split("_")[0], "on" if on(c, k) else "off", v))
    land = landing_state(c)
    if land:
        print("Landing mode: on since {} ('{}')".format(land["since"], land["phrase"]))
    print("List:", ACTIVE)


def cmd_threads():
    c = cfg()
    n = thread_numbers(c)
    print(thread_line(n))
    for sid, (ts, path, cwd) in sorted(n["latest"].items(), key=lambda kv: kv[1][0], reverse=True):
        st, last = tail_state(path)
        last = re.sub(r"\s+", " ", last)[-90:]
        print("  {:5}  {}  {:28}  …{}".format(st, ts.strftime("%a %H:%M"), os.path.basename(cwd)[:28], last))
    if not n["latest"]:
        print("  (no messages logged in the last 24 hours; the log starts when the guards are installed)")


def cmd_add(kind, body):
    t = now().strftime("%Y-%m-%d %H:%M")
    cwd = os.path.basename(os.getcwd())
    body = body.strip()
    if kind == "review":
        append(REVIEW, "- [ ] {} · {} · {}".format(t, cwd, body))
        print("Added to the review list:", REVIEW)
    elif kind == "parking":
        append(PARKING, "- {} · {} · {}".format(t, cwd, body))
        print("Parked in:", PARKING)
    elif kind == "built":
        append(BUILT, "- {} · {}".format(t, body))
        print("Added to the ledger:", BUILT)
    elif kind == "handoff":
        path = os.path.join(HANDOFF_DIR, "{}_{}.md".format(now().strftime("%Y-%m-%d_%H%M"), cwd))
        append(path, "# Handoff {} · {}\n\n{}".format(t, os.getcwd(), body))
        print("State saved in:", path)
    else:
        print("KIND must be one of: review, parking, handoff, built")


def cmd_built(args):
    days, proj = 7, None
    for a in args:
        if a.isdigit():
            days = int(a)
        else:
            proj = a.lower()
    cut = (now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with open(BUILT) as f:
            rows = [l.rstrip() for l in f if l.startswith("- ") and l[2:12] >= cut]
    except Exception:
        rows = []
    if proj:
        rows = [r for r in rows if proj in r.lower()]
    print("Built in the last {} days{}: {} entries".format(days, " (" + proj + ")" if proj else "", len(rows)))
    for r in rows:
        parts = [p.strip() for p in r[2:].split("|")]
        head = parts[0].split(" · ")
        print("\n{}  {}".format(head[0], " · ".join(head[1:])))
        for p in parts[1:]:
            print("    " + p)


def cmd_settings():
    hook = lambda name, extra=None: dict({"hooks": [{"type": "command", "command": ME + " hook " + name,
                                                    "timeout": 10}]}, **(extra or {}))
    block = {
        "hooks": {
            "UserPromptSubmit": [hook("prompt")],
            "SessionStart": [hook("start")],
            "PostToolUse": [hook("posttool", {"matcher": "Bash"})],
        },
        "permissions": {"allow": ["Bash({} add:*)".format(ME), "Bash({} threads)".format(ME),
                                  "Bash({} built:*)".format(ME), "Bash({} review)".format(ME),
                                  "Bash({} status)".format(ME)]},
    }
    print("# guards — merge into ~/.claude/settings.json (existing hooks stay). install.py does this for you.")
    print(json.dumps(block, indent=2))


def cmd_review():
    try:
        with open(REVIEW) as f:
            print(f.read().strip() or "(empty)")
    except Exception:
        print("(empty)")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "hook":
        try:
            raw = sys.stdin.read()
            data = json.loads(raw) if raw.strip() else {}
            {"prompt": hook_prompt, "start": hook_start, "posttool": hook_posttool}[a[1]](data)
        except Exception as e:  # never break a session
            try:
                event("ERROR in hook {}: {!r}".format(a[1:], e))
            except Exception:
                pass
        sys.exit(0)
    if a[0] in ("on", "off"):
        cmd_switch(a[0] == "on", a[1] if len(a) > 1 else None)
    elif a[0] == "status":
        cmd_status()
    elif a[0] == "threads":
        cmd_threads()
    elif a[0] == "built":
        cmd_built(a[1:])
    elif a[0] == "add" and len(a) >= 3:
        cmd_add(a[1], " ".join(a[2:]))
    elif a[0] == "review":
        cmd_review()
    elif a[0] == "settings":
        cmd_settings()
    elif a[0] == "selftest":
        import subprocess
        sys.exit(subprocess.call([sys.executable, os.path.join(HERE, "selftest.py")]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
