#!/usr/bin/env python3
"""Re-evaluation (Phase 3): did the guards help? One file, standard library only.

  reeval.py                    run it: compare the time since the guards were installed
                               with the four weeks before, write reports/reeval_DATE.md
  reeval.py answer W U F [note]   store my own three ratings, each 1 (bad) to 5 (good):
                               W = was I able to work nicely, U = was AI still very useful,
                               F = did I feel good using it
  reeval.py --today            also count today (an unfinished day)

Reads (read-only): ~/.claude/projects (live transcripts), and this folder's state/. Writes only: guards/state/reeval_*.{json,csv,log} and
reports/reeval_DATE.md. Stores numbers and times only, never message text.
Sends nothing anywhere. This reports usage patterns. It is not a diagnosis.
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guards as G  # noqa: E402  (same folder: phrases, config, state paths)

PROJECT = HERE
STATE = G.STATE
LIVE = os.environ.get("REEVAL_LIVE") or os.path.expanduser("~/.claude/projects")
SNAP = os.environ.get("REEVAL_SNAPSHOT") or ""
DAYS = os.path.join(STATE, "reeval_days.json")
ANSWERS = os.path.join(STATE, "reeval_answers.csv")
RUNS = os.path.join(STATE, "reeval_runs.log")

SYSREM = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
IDE = re.compile(r"<ide_(opened_file|selection)>.*?</ide_\1>", re.S)
ARTV = re.compile(r"<artifact-view-context.*?</artifact-view-context>", re.S)
STATUS = re.compile(r"^(und|so|and|na|nun)\s*\?+$|^(status|fertig|done|ready|läuft es|laeuft es|does it run)\s*\?*$"
                    r"|how long|wie lange", re.I)
ORIENT = re.compile(r"where are we|wo sind wir|wo waren wir|was machen wir gerade|what are we doing|where were we", re.I)
COMMIT = re.compile(r"\bgit\b[^|;&]*\bcommit\b")


def ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def text_of(content):
    if isinstance(content, str):
        return content, 0
    t, img = [], 0
    for b in content or []:
        if isinstance(b, dict):
            if b.get("type") == "text":
                t.append(b.get("text", ""))
            elif b.get("type") == "image":
                img += 1
    return "\n".join(t), img


def first_ts(path):
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                m = re.search(r'"timestamp":"([^"]+)"', line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "9999"


def transcript_files():
    """Live transcripts first; the snapshot only for files that no longer exist live."""
    found = {}
    for root in (LIVE, SNAP):
        if not os.path.isdir(root):
            continue
        for d in os.listdir(root):
            p = os.path.join(root, d)
            if not os.path.isdir(p):
                continue
            for f in glob.glob(os.path.join(glob.escape(p), "*.jsonl")):
                key = (d, os.path.basename(f))
                if key not in found or os.path.getsize(f) > os.path.getsize(found[key]):
                    found[key] = f
    return sorted(found.values(), key=first_ts)


def scan(path, seen, ev):
    """Pull the few record kinds we count out of one transcript. Keeps numbers, not text."""
    sid = os.path.basename(path)[:-6]
    last_human_len, replies = None, 0
    with open(path, errors="replace") as fh:
        for line in fh:
            if '"origin":{"kind":"human"}' in line:
                kind = "h"
            elif '"stop_reason":"end_turn"' in line:
                kind = "a"
            elif "[Request interrupted by user" in line:
                kind = "i"
            elif '"compact_boundary"' in line:
                kind = "c"
            elif '"name":"AskUserQuestion"' in line:
                kind = "q"
            elif '"name":"Bash"' in line and "commit" in line and "git" in line:
                kind = "g"
            else:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("isSidechain"):
                continue
            t = ts(r.get("timestamp") or "")
            typ = r.get("type")
            msg = r.get("message") or {}
            content = msg.get("content")
            fresh = True
            u = r.get("uuid")
            if u:
                fresh = u not in seen  # forked sessions repeat records of their parent
            if kind == "h":
                if typ != "user" or (r.get("origin") or {}).get("kind") != "human" or r.get("isCompactSummary"):
                    continue
                if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                                     for b in content):
                    continue
                txt, img = text_of(content)
                if txt.startswith("[Request interrupted by user"):
                    if fresh and t:
                        seen.add(u)
                        ev.append((t, sid, "i", {}))
                    continue
                clean = ARTV.sub("", IDE.sub("", SYSREM.sub("", txt))).strip()
                if not clean and not img:
                    continue
                last_human_len = len(clean)
                if not (fresh and t):
                    continue
                seen.add(u)
                low = clean.lower()
                ev.append((t, sid, "h", {
                    "len": len(clean),
                    "status": bool(len(clean) < 40 and STATUS.search(low)),
                    "orient": bool(len(clean) < 200 and ORIENT.search(low)),
                    "phrase": bool(G.find_phrase(clean)),
                    "proj": re.sub(r"--claude-worktrees-.*$", "", os.path.basename(os.path.dirname(path))),
                    "entry": r.get("entrypoint") or "?",
                }))
            elif kind == "a":
                if typ != "assistant" or msg.get("stop_reason") != "end_turn" or r.get("isApiErrorMessage"):
                    continue
                txt, _ = text_of(content)
                txt = txt.strip()
                if not txt:
                    continue
                replies += 1
                if not (fresh and t):
                    continue
                seen.add(u)
                lines = [l.strip() for l in txt.splitlines() if l.strip()]
                head = "\n".join(lines[:12])
                ev.append((t, sid, "a", {
                    "len": len(txt),
                    "ratio": round(len(txt) / max(last_human_len, 1), 1) if last_human_len is not None else None,
                    "q_end": lines[-1].rstrip("*_ `").endswith("?"),
                    "bold": any(l.startswith("**") or re.match(r"^\d+\.\s+\*\*", l) for l in lines[:4]),
                    "needs": "needs you:" in head.lower(),
                    "open": bool(re.search(r"(?m)^\W*(\d+\.\s*)?Open:", "\n".join(lines[:8] + lines[-6:]))),
                    "marks": bool(re.search(r"checked:|not checked|needs your eyes", txt, re.I)),
                    "first": replies == 1,
                    "startline": "guards active" in "\n".join(lines[:3]).lower(),
                }))
            elif kind == "i":
                if typ == "user" and fresh and t and text_of(content)[0].startswith("[Request interrupted by user"):
                    seen.add(u)
                    ev.append((t, sid, "i", {}))
            elif kind == "c":
                if typ == "system" and r.get("subtype") == "compact_boundary" and fresh and t:
                    seen.add(u)
                    ev.append((t, sid, "c", {}))
            elif kind in ("q", "g"):
                if typ != "assistant" or not (fresh and t) or not isinstance(content, list):
                    continue
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    if b.get("name") == "AskUserQuestion":
                        ev.append((t, sid, "q", {}))
                    elif b.get("name") == "Bash" and COMMIT.search((b.get("input") or {}).get("command") or ""):
                        ev.append((t, sid, "g", {}))
                if u:
                    seen.add(u)


def wd(t, c):
    return G.workday(t, c)


def day_rows(ev, c):
    """One row of numbers per work day (a day runs 05:00 to 05:00)."""
    ev.sort(key=lambda e: e[0])
    humans = [e for e in ev if e[2] == "h"]
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for t, sid, k, p in ev:
        by[str(wd(t, c))][k].append((t, sid, p))
    # how many sessions did I write in during the hour before each message
    multi, j = {}, 0
    for i, (t, sid, _, _) in enumerate(humans):
        while humans[j][0] < t - dt.timedelta(minutes=60):
            j += 1
        multi[i] = len({h[1] for h in humans[j:i + 1]})
    idx = collections.defaultdict(list)
    for i, h in enumerate(humans):
        idx[str(wd(h[0], c))].append(i)
    rows = {}
    for day, kinds in by.items():
        hs = kinds.get("h", [])
        row = {"msgs": len(hs)}
        if hs:
            times = [h[0] for h in hs]
            row.update({
                "first": min(times).isoformat(timespec="minutes"),
                "last": max(times).isoformat(timespec="minutes"),
                "span_h": round((max(times) - min(times)).total_seconds() / 3600, 1),
                "sessions": len({h[1] for h in hs}),
                "projects": len({h[2]["proj"] for h in hs}),
                "multi3": sum(1 for i in idx[day] if multi[i] >= 3),
                "late23": sum(1 for x in times if x.hour >= 23 or x.hour < 5),
                "late01": sum(1 for x in times if 1 <= x.hour < 5),
                "status": sum(1 for h in hs if h[2]["status"]),
                "orient": sum(1 for h in hs if h[2]["orient"]),
                "msg_lens": [h[2]["len"] for h in hs],
                "eng_h": round(sum((b - a).total_seconds() for a, b in zip(times, times[1:])
                                   if (b - a).total_seconds() < 900) / 3600, 1),
                "switches": sum(1 for a, b in zip(hs, hs[1:]) if a[1] != b[1]),
            })
            hits = [h[0] for h in hs if h[2]["phrase"]]
            row["stop_hits"] = len(hits)
            if hits:
                t0 = min(hits)
                row["stop_at"] = t0.strftime("%H:%M")
                row["after_stop_3h"] = sum(1 for h in humans if t0 < h[0] <= t0 + dt.timedelta(hours=3))
        rep = kinds.get("a", [])
        row.update({
            "reply_lens": [r[2]["len"] for r in rep],
            "ratios": [r[2]["ratio"] for r in rep if r[2]["ratio"] is not None],
            "q_end": sum(1 for r in rep if r[2]["q_end"]),
            "c_bold": sum(1 for r in rep if r[2]["bold"]),
            "c_needs": sum(1 for r in rep if r[2]["needs"]),
            "c_open": sum(1 for r in rep if r[2]["open"]),
            "c_marks": sum(1 for r in rep if r[2]["marks"]),
            "first_replies": sum(1 for r in rep if r[2]["first"]),
            "startlines": sum(1 for r in rep if r[2]["first"] and r[2]["startline"]),
            "ask_dialogs": len(kinds.get("q", [])),
            "interrupts": len(kinds.get("i", [])),
            "compactions": len(kinds.get("c", [])),
            "commits": len(kinds.get("g", [])),
        })
        rows[day] = row
    return rows


def merge(stored, new):
    """Transcripts get deleted after some weeks. Keep the stored row when it saw more."""
    out = dict(stored)
    for day, row in new.items():
        old = stored.get(day)
        if not old or row.get("msgs", 0) >= old.get("msgs", 0):
            out[day] = row
    return out


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def dates(a, b):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


def period(rows, a, b):
    """All numbers for the work days a..b (both included). None if the period is empty."""
    if a > b:
        return None
    days = [str(d) for d in dates(a, b)]
    act = [rows[d] for d in days if rows.get(d, {}).get("msgs", 0) > 0]
    allr = [rows[d] for d in days if d in rows]
    n_msgs = sum(r["msgs"] for r in act)
    lens = [x for r in allr for x in r.get("reply_lens", [])]
    n_rep = len(lens)
    pauses = []
    for d in dates(a + dt.timedelta(days=1), b):
        p, q = rows.get(str(d - dt.timedelta(days=1)), {}), rows.get(str(d), {})
        if p.get("last") and q.get("first"):
            pauses.append((dt.datetime.fromisoformat(q["first"]) - dt.datetime.fromisoformat(p["last"]))
                          .total_seconds() / 3600)
    stops = [r["after_stop_3h"] for r in act if "after_stop_3h" in r]
    weeks = max(len(days) / 7, 1e-9)
    pct = lambda x, n: round(100 * x / n, 1) if n else None
    per100 = lambda x: round(100 * x / n_msgs, 1) if n_msgs else None
    return {
        "from": str(a), "to": str(b), "days": len(days), "active_days": len(act),
        "days_off": len(days) - len(act),
        "msgs": n_msgs, "msgs_per_week": round(n_msgs / weeks),
        "msgs_per_active_day": med([r["msgs"] for r in act]),
        "span_h": med([r["span_h"] for r in act]),
        "days_span_15h": sum(1 for r in act if r["span_h"] >= 15),
        "sessions_per_day": med([r["sessions"] for r in act]),
        "sessions_max": max([r["sessions"] for r in act], default=None),
        "projects_per_day": med([r["projects"] for r in act]),
        "multi3_pct": pct(sum(r["multi3"] for r in act), n_msgs),
        "late23_pct": pct(sum(r["late23"] for r in act), n_msgs),
        "days_after_01": sum(1 for r in act if r["late01"] > 0),
        "short_nights": sum(1 for p in pauses if p < 7), "night_pairs": len(pauses),
        "shortest_pause_h": round(min(pauses), 1) if pauses else None,
        "status_per100": per100(sum(r["status"] for r in act)),
        "orient_per100": per100(sum(r["orient"] for r in act)),
        "stop_days": len(stops), "after_stop_median": med(stops),
        "replies": n_rep, "reply_median": med(lens),
        "reply_over1500_pct": pct(sum(1 for x in lens if x > 1500), n_rep),
        "ratio_median": med([x for r in allr for x in r.get("ratios", [])]),
        "reply_kchars_per_day": med([round(sum(r.get("reply_lens", [])) / 1000) for r in act]),
        "q_end_pct": pct(sum(r.get("q_end", 0) for r in allr), n_rep),
        "ask_per100": per100(sum(r.get("ask_dialogs", 0) for r in allr)),
        "c_bold_pct": pct(sum(r.get("c_bold", 0) for r in allr), n_rep),
        "c_needs_pct": pct(sum(r.get("c_needs", 0) for r in allr), n_rep),
        "c_open_pct": pct(sum(r.get("c_open", 0) for r in allr), n_rep),
        "c_marks_pct": pct(sum(r.get("c_marks", 0) for r in allr), n_rep),
        "first_replies": sum(r.get("first_replies", 0) for r in allr),
        "startlines": sum(r.get("startlines", 0) for r in allr),
        "interrupts_per100": per100(sum(r.get("interrupts", 0) for r in allr)),
        "compactions": sum(r.get("compactions", 0) for r in allr),
        "commits": sum(r.get("commits", 0) for r in allr),
    }


# metric, label, which direction is good ("low", "high", or None = just information)
TABLE = [
    ("Q1 · Was I able to work nicely? (shape of the work)", None, None),
    ("days_off", "days without any AI use", "high"),
    ("msgs_per_active_day", "my messages per active day (median)", None),
    ("span_h", "hours from first to last message (median day)", "low"),
    ("days_span_15h", "days spanning 15 h or more", "low"),
    ("sessions_per_day", "sessions I wrote in per day (median)", "low"),
    ("projects_per_day", "project folders per day (median)", "low"),
    ("multi3_pct", "% of my messages with 3+ sessions in the hour before", "low"),
    ("late23_pct", "% of my messages between 23:00 and 05:00", None),
    ("days_after_01", "days with messages after 01:00", None),
    ("short_nights", "nights with under 7 h between last and first message", "low"),
    ("status_per100", "status checks ('und?', 'how long?') per 100 messages", "low"),
    ("orient_per100", "'where are we' questions per 100 messages", "low"),
    ("stop_days", "days on which I said I was tired / going to bed", None),
    ("after_stop_median", "my messages in the 3 h after saying so (median)", "low"),
    ("Claude's side", None, None),
    ("reply_median", "reply length, characters (median)", None),
    ("ratio_median", "reply length divided by my message length (median)", "low"),
    ("reply_kchars_per_day", "reply text per active day, thousand characters (median)", "low"),
    ("q_end_pct", "% of replies ending with a question", "low"),
    ("ask_per100", "multiple-choice dialogs per 100 of my messages", "low"),
    ("c_needs_pct", "% of replies with a 'Needs you:' line (reply contract)", "high"),
    ("c_open_pct", "% of replies with an 'Open: … · Next: …' line", "high"),
    ("c_marks_pct", "% of replies with a 'checked / not checked' mark", "high"),
    ("Q2 · Was AI still very useful? (counts cannot decide this; my own rating does)", None, None),
    ("msgs_per_week", "my messages per week", None),
    ("commits", "git commits made by Claude", None),
    ("interrupts_per100", "times I stopped Claude (Esc) per 100 messages", "low"),
    ("compactions", "context compactions (very long sessions)", None),
]


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return str(v)


def verdict(key, good, base, now, scale):
    if good is None or base is None or now is None or (base.get(key) is None) or (now.get(key) is None):
        return ""
    b, n = base[key], now[key]
    if key in ("days_off", "days_span_15h", "short_nights"):
        b = b * scale  # counts: bring the baseline to the length of the new period
    if key.endswith("_pct"):
        diff, tol = n - b, 5
    else:
        diff, tol = n - b, max(abs(b) * 0.2, 0.5)
    if abs(diff) < tol:
        return "about the same"
    return "better" if (diff < 0) == (good == "low") else "worse"


def guard_state(after_from, c):
    """What the guards themselves recorded since the install."""
    out = {"events": collections.Counter(), "digits": [], "off_now": []}
    try:
        for line in open(G.EVENTS):
            day, msg = line[:10], line[18:].strip()
            if day < str(after_from):
                continue
            for key, pat in (("landing_on", "landing ON"), ("landing_weiter", "landing overridden"),
                             ("threshold", "threshold crossed"), ("all_off", "all guards OFF"),
                             ("free", "free mode on"), ("errors", "ERROR in hook"), ("blocked", "BLOCKED session"),
                             ("block_lifted", "block lifted"), ("auto_passed", "automated session"),
                             ("brief_off", "start brief OFF"), ("time_notes", "time note:"), ("one_off", "_")):
                if pat == "_":
                    if re.match(r"P\d+_\w+ OFF", msg):
                        out["events"][key] += 1
                elif pat in msg:
                    out["events"][key] += 1
    except Exception:
        pass
    try:
        for line in open(G.MOOD):
            p = line.strip().split(",")
            if len(p) >= 2 and p[0] >= str(after_from) and p[1].isdigit():
                out["digits"].append((p[0], int(p[1])))
    except Exception:
        pass
    count = lambda path, start: sum(1 for l in open(path) if l.startswith(start)) if os.path.exists(path) else 0
    out["review_open"] = count(G.REVIEW, "- [ ]")
    out["review_done"] = count(G.REVIEW, "- [x]")
    out["parking"] = count(G.PARKING, "- ")
    out["built"] = sum(1 for l in open(G.BUILT) if l.startswith("- ") and l[2:12] >= str(after_from)) \
        if os.path.exists(G.BUILT) else 0
    if not c.get("all", True):
        out["off_now"].append("EVERYTHING")
    out["off_now"] += [k.split("_")[0] for k in G.NAMES if not c.get("guards", {}).get(k, False)]
    return out


def hook_coverage(ev, c):
    """Do the guards reach every session? Compare transcripts with the guards' own log."""
    logged, first = set(), None
    try:
        for line in open(G.LOG):
            p = line.split("\t")
            if len(p) >= 2:
                logged.add(p[1])
                first = first or dt.datetime.fromisoformat(p[0])
    except Exception:
        pass
    if not first:
        return None
    sess = collections.defaultdict(list)
    for t, sid, k, p in ev:
        if k == "h" and t >= first:
            sess[sid].append(p["entry"])
    missed = {s: v for s, v in sess.items() if s not in logged}
    return {"since": first.isoformat(timespec="minutes"), "sessions": len(sess), "missed": len(missed),
            "missed_msgs": sum(len(v) for v in missed.values()),
            "missed_entry": dict(collections.Counter(e for v in missed.values() for e in v)),
            "ok_entry": dict(collections.Counter(e for s, v in sess.items() if s in logged for e in v))}


def answers():
    out = []
    try:
        for line in open(ANSWERS):
            p = line.rstrip("\n").split(",", 4)
            if len(p) >= 4 and p[1].isdigit():
                out.append(p)
    except Exception:
        pass
    return out


def flags(base, now, gs, cov, ans, c):
    """Fixed rules, written down before any result existed. Each one names what to do."""
    f = []
    if cov and cov["sessions"] and cov["missed"] / cov["sessions"] > 0.1:
        f.append("R1 · The guards did not reach {} of {} sessions ({} messages; opened via: {}). Find out which way "
                 "of starting a session skips the hooks, before judging anything else."
                 .format(cov["missed"], cov["sessions"], cov["missed_msgs"], cov["missed_entry"]))
    if gs["off_now"]:
        f.append("R2 · Switched off right now: {}. That is information, not a failure. Say what bothered me, then "
                 "change or delete that guard.".format(", ".join(gs["off_now"])))
    if gs["events"]["errors"]:
        f.append("R3 · The hook script crashed {} times (see guards/state/events.log). Fix it."
                 .format(gs["events"]["errors"]))
    if not now or now["days"] < 7:
        return f
    if now["first_replies"] >= 5 and now["startlines"] / now["first_replies"] < 0.8:
        f.append("R4 · The line 'Guards active' opened only {} of {} new sessions. Either the start hook does not "
                 "arrive or Claude drops the line. Then I can forget the guards exist: repair this first."
                 .format(now["startlines"], now["first_replies"]))
    if now["c_needs_pct"] is not None and now["c_needs_pct"] < 70:
        f.append("R5 · Only {}% of replies follow the reply contract (P2). It is wearing off or not arriving. "
                 "Shorten the contract text or move it to an output style.".format(fmt(now["c_needs_pct"])))
    if now["stop_days"] >= 2 and base and base["after_stop_median"] and now["after_stop_median"] is not None \
            and now["after_stop_median"] >= 0.7 * base["after_stop_median"]:
        f.append("R6 · After I said I was tired I still wrote {} messages in the next 3 h (before: {}). Landing "
                 "mode (P1) does not change what happens. It needs a different design, not more reminders."
                 .format(fmt(now["after_stop_median"]), fmt(base["after_stop_median"])))
    ev = gs["events"]
    if ev["landing_on"] >= 3 and ev["landing_weiter"] > ev["landing_on"] / 2:
        f.append("R7 · I typed 'weiter' after {} of {} landings. Either my phrases fire too easily (edit "
                 "guards/phrases.txt) or landing costs me more than it gives.".format(ev["landing_weiter"],
                                                                                    ev["landing_on"]))
    if now["stop_days"] == 0 and (now["days_after_01"] >= 2 or now["short_nights"] >= 1):
        f.append("R8 · Late nights happened but no stop phrase was ever seen. Landing mode depends on my words; "
                 "check whether I say it differently now (guards/phrases.txt).")
    if now["commits"] >= 5 and gs["built"] < 0.5 * now["commits"]:
        f.append("R9 · {} commits but only {} ledger entries (P4). The ledger is not kept; make the hook write "
                 "the entry itself or drop P4.".format(now["commits"], gs["built"]))
    if ev["landing_on"] >= 3 and len(gs["digits"]) < ev["landing_on"] / 3:
        f.append("R10 · The day digit (P11) was answered {} times in {} landings. Drop it or ask differently."
                 .format(len(gs["digits"]), ev["landing_on"]))
    if now["days"] >= 14 and now["days_off"] == 0:
        f.append("R11 · Still no day without AI use in {} days. No guard addresses this; it needs a decision of "
                 "mine, not a tool.".format(now["days"]))
    if now["msgs_per_week"] < 0.3 * (base["msgs_per_week"] if base else 0):
        f.append("R12 · I use Claude far less than before ({} vs {} messages a week). Check whether that has an outside "
                 "reason, or whether the guards make Claude unpleasant to use."
                 .format(now["msgs_per_week"], base["msgs_per_week"]))
    if ev["blocked"] >= 5 and ev["block_lifted"] >= 0.8 * ev["blocked"]:
        f.append("R14 · I typed 'frei' in {} of {} blocked sessions. The block is only a speed bump. Decide: keep "
                 "it as a pause to think, make it stricter, or remove it.".format(ev["block_lifted"], ev["blocked"]))
    if ev["blocked"] >= 3 and now["sessions_per_day"] is not None and base and base["sessions_per_day"] \
            and now["sessions_per_day"] >= 0.8 * base["sessions_per_day"]:
        f.append("R15 · Sessions per day did not go down ({} vs {} before) although the block fired {} times."
                 .format(fmt(now["sessions_per_day"]), fmt(base["sessions_per_day"]), ev["blocked"]))
    if ans and any(int(x) <= 2 for x in ans[-1][1:4]):
        f.append("R13 · My own last rating has a 1 or 2 in it. That outweighs every count above.")
    return f


def report(rows, ev, c, today_too):
    inst = dt.date.fromisoformat(c.get("installed_on") or str(G.now().date()))
    seed = inst - dt.timedelta(days=28)
    today = wd(G.now(), c)
    end = today if today_too else today - dt.timedelta(days=1)
    base = period(rows, seed, inst - dt.timedelta(days=1))
    now = period(rows, inst + dt.timedelta(days=1), end)
    gs = guard_state(inst, c)
    cov = hook_coverage(ev, c)
    ans = answers()
    fl = flags(base, now, gs, cov, ans, c)
    scale = (now["days"] / base["days"]) if (now and base) else 1
    L = ["# Re-evaluation, " + str(G.now().date()), "",
         "Made by `guards/reeval.py`. Everything is **data** (counts) unless a line says inference.",
         "This reports usage patterns. It is not a diagnosis.", "",
         "- Before: {} to {} ({} days), the four weeks before the guards.".format(base["from"], base["to"],
                                                                                    base["days"]),
         "- Since: {} to {} ({} days). The install day itself ({}) counts for neither side.".format(
             now["from"], now["to"], now["days"], inst) if now else
         "- Since: no finished day yet after the install on {}.".format(inst), ""]
    if not now or now["days"] < 7:
        L += ["**Too early to judge: {} finished days since the install. Wait for at least 7, better 14.** "
              "The table shows the 'before' column so that I can see what will be compared."
              .format(now["days"] if now else 0), ""]
    elif now["days"] < 14:
        L += ["**Early look: {} days. Treat every 'better/worse' as a hint.**".format(now["days"]), ""]
    L += ["## My three questions", ""]
    if ans:
        a = ans[-1]
        L += ["My own rating of {} (1 bad … 5 good): work nicely **{}**, AI useful **{}**, felt good **{}**{}".format(
            a[0], a[1], a[2], a[3], " · note: " + a[4] if len(a) > 4 and a[4] else "")]
        if len(ans) > 1:
            L += ["Earlier: " + " · ".join("{} {}/{}/{}".format(x[0], x[1], x[2], x[3]) for x in ans[:-1])]
    else:
        L += ["No rating from me yet. Counts cannot say how it felt. Record it with three digits (1 bad … 5 good):",
              "`python3 {} answer W U F` — W: was I able to work nicely, U: was AI still very useful, "
              "F: did I feel good using it.".format(os.path.join(HERE, "reeval.py"))]
    if gs["digits"]:
        L += ["Day digits (P11) since the install: {} answers, mean {:.1f}: {}".format(
            len(gs["digits"]), statistics.mean(d for _, d in gs["digits"]),
            " ".join("{}:{}".format(d[5:], v) for d, v in gs["digits"][-14:]))]
    L += ["", "## What the rules say", ""]
    L += ["- " + x for x in fl] or ["- No rule fired."]
    L += ["", "The rules are fixed in `guards/reeval.py` (function `flags`) and explained in `docs/RULES.md`.", "",
          "## Before and since", "", "| | before | since | |", "|---|---|---|---|"]
    for key, label, good in TABLE:
        if label is None:
            L.append("| **{}** | | | |".format(key))
            continue
        L.append("| {} | {} | {} | {} |".format(label, fmt(base.get(key)), fmt(now.get(key)) if now else "–",
                                                 verdict(key, good, base, now, scale)))
    L += ["", "Counts for days are not scaled in the columns; the verdict scales 'before' to the length of 'since'.",
          "", "## Are the guards alive?", ""]
    if cov:
        L += ["- Hooks reached {} of {} sessions I wrote in since {} (missed: {} sessions, {} messages; opened via "
              "{}). While everything is switched off, nothing is logged, so 'missed' can include those times."
              .format(cov["sessions"] - cov["missed"], cov["sessions"], cov["since"], cov["missed"],
                      cov["missed_msgs"], cov["missed_entry"] or "–")]
    if now:
        L += ["- Start line 'Guards active' in the first reply: {} of {} new sessions.".format(
            now["startlines"], now["first_replies"])]
    e = gs["events"]
    L += ["- Landing mode started {} times; I typed 'weiter' {} times.".format(e["landing_on"], e["landing_weiter"]),
          "- Thread note ('which one pauses?') shown {} times. Free mode switched on {} times.".format(
              e["threshold"], e["free"]),
          "- Session block: {} new sessions were held back; I typed 'frei' in {} of them; {} automated "
          "sessions passed.".format(e["blocked"], e["block_lifted"], e["auto_passed"]),
          "- Start brief switched off for the day {} times. Time notes shown: {}.".format(e["brief_off"],
                                                                                         e["time_notes"]),
          "- 'guards off' typed {} times; single guards switched off {} times; off right now: {}.".format(
              e["all_off"], e["one_off"], ", ".join(gs["off_now"]) or "none"),
          "- Review list: {} open, {} done. Parked ideas: {}. Ledger entries: {} (commits seen: {}).".format(
              gs["review_open"], gs["review_done"], gs["parking"], gs["built"], now["commits"] if now else "–"),
          "", "## Week by week", "",
          "| week from | active days | my messages | after 23:00 | reply text (k chars) | sessions/day (median) |",
          "|---|---|---|---|---|---|"]
    monday = today - dt.timedelta(days=today.weekday())
    for w in range(9, -1, -1):
        a = monday - dt.timedelta(weeks=w)
        p = period(rows, a, min(a + dt.timedelta(days=6), today))
        if not p or (p["msgs"] == 0 and a < seed):
            continue
        late = sum(rows.get(str(d), {}).get("late23", 0) for d in dates(a, a + dt.timedelta(days=6)))
        kch = sum(sum(rows.get(str(d), {}).get("reply_lens", [])) for d in dates(a, a + dt.timedelta(days=6)))
        L.append("| {}{} | {} | {} | {} | {} | {} |".format(
            a, " (running)" if w == 0 else "", p["active_days"], p["msgs"], late, round(kch / 1000),
            fmt(p["sessions_per_day"])))
    L += ["", "## Limits", "",
          "- Counts show what happened on the screen, not how I felt. Only my own rating answers that.",
          "- Less or more use since the install can have reasons outside the guards (a deadline, a holiday). The "
          "week table helps to see that.",
          "- The same script counted both periods, so the columns are comparable with each other.",
          "- A message at night proves I was awake. A long pause does not prove sleep.",
          "- Chats in the claude.ai web app and on the phone are not counted.", ""]
    return "\n".join(L), now


def main():
    a = sys.argv[1:]
    if a and a[0] == "answer":
        if len(a) < 4 or not all(re.fullmatch(r"[1-5]", x) for x in a[1:4]):
            print("Use: reeval.py answer W U F [note]   each 1 (bad) to 5 (good)")
            return
        note = " ".join(a[4:]).replace("\n", " ")
        G.append(ANSWERS, "{},{},{},{},{}".format(G.now().date(), a[1], a[2], a[3], note))
        print("Saved in", ANSWERS)
        return
    if a and a[0] in ("-h", "--help"):
        print(__doc__)
        return
    c = G.cfg()
    seen, ev = set(), []
    files = transcript_files()
    for f in files:
        try:
            scan(f, seen, ev)
        except Exception as e:
            print("skipped", f, repr(e), file=sys.stderr)
    rows = merge(G.load(DAYS, {}), day_rows(ev, c))
    G.save(DAYS, rows)
    text, now = report(rows, ev, c, "--today" in a)
    out = os.path.join(PROJECT, "reports", "reeval_{}.md".format(G.now().date()))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(text)
    G.append(RUNS, "{}  {} files, {} finished days since install".format(
        G.now().strftime("%Y-%m-%d %H:%M"), len(files), now["days"] if now else 0))
    print(text.split("## Before and since")[0].rstrip())
    print("\nFull report with all tables:", out)


if __name__ == "__main__":
    main()
