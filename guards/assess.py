#!/usr/bin/env python3
"""Assessment: what does MY record of working with Claude Code show, and which guards fit ME?

  assess.py                  count my local sessions (costs no usage), write PROFILE.md,
                             profile_radar.svg and config.proposed.json. Changes nothing else.
  assess.py format k=v ...   store my answers about the reply shape in the proposal
  assess.py set k=v ...      change one proposed value (e.g. thread_threshold=4, P1_landing=off)
  assess.py accept           make the proposal my config.json (hooks are installed by install.py)
  assess.py sample [N]       list N sessions worth reading, with an estimate of what reading costs.
                             Reads nothing itself.

Nobody gets somebody else's settings: every value comes from my own counts and my own answers.
It looks at what happens on the screen (symptoms), not at diagnoses. It is not a diagnosis and not
medical advice. Reads ~/.claude/projects (read-only). Stores numbers and times, never message text.
Sends nothing anywhere.
"""
import collections
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guards as G  # noqa: E402
import reeval as R  # noqa: E402

PROPOSED = os.path.join(HERE, "config.proposed.json")
PROFILE = os.path.join(HERE, "PROFILE.md")
RADAR = os.path.join(HERE, "profile_radar.svg")
DAYS_BACK = 42

# Each dimension: what shows on the screen, how it is counted, and the guard that answers it.
# (metric, value that scores 0, value that scores 100). The anchors are PROVISIONAL: they come from the
# record of one heavy user, not from a population. They only decide what gets proposed; I decide what is used.
DIMENSIONS = [
    ("threads", "Many things at once", [("multi3_pct", 5, 45), ("sessions_per_day", 2, 10)],
     "session limit, focus mode"),
    ("stopping", "Going on after I said stop", [("after_stop_median", 3, 30)], "landing mode"),
    ("edges", "Long days, late nights, no days off", [("span_h", 8, 15), ("late23_pct", 2, 15),
                                                       ("short_nights_per_week", 0, 1.5),
                                                       ("days_on_share", 72, 100)], "time note, landing mode"),
    ("reply_load", "Much more text coming back than I send", [("ratio_median", 5, 15),
                                                               ("reply_kchars_per_day", 30, 150)], "reply shape"),
    ("decisions", "Many questions and choices put to me", [("ask_per100", 1, 8), ("q_end_pct", 5, 20)],
     "reply shape: one question, Claude decides small things"),
    ("track", "Losing track of where things stand", [("orient_per100", 0, 0.5), ("status_per100", 0.5, 3),
                                                     ("compactions_per_week", 1, 10)],
     "start brief, 'Open · Next' line, built-ledger"),
    ("steering", "Stopping and correcting Claude often", [("interrupts_per100", 0.5, 4)], "start brief with stop points"),
]

FORMAT_KEYS = {
    "bold_first": bool, "needs_you_line": bool, "open_line": ("top", "bottom", "off"), "max_questions": int,
    "short_sentences": bool, "numbered_sentences": bool, "decide_small_things": bool,
    "new_directions": ("block", "inline", "off"), "check_marks": bool, "language": str,
}


def measure():
    c = G.cfg()
    seen, ev = set(), []
    files = R.transcript_files()
    for f in files:
        try:
            R.scan(f, seen, ev)
        except Exception:
            pass
    rows = R.day_rows(ev, c)
    today = G.workday(G.now(), c)
    p = R.period(rows, today - dt.timedelta(days=DAYS_BACK), today - dt.timedelta(days=1))
    weeks = max(p["days"] / 7, 1e-9)
    p["short_nights_per_week"] = round(p["short_nights"] / weeks, 2)
    p["compactions_per_week"] = round(p["compactions"] / weeks, 1)
    p["days_on_share"] = round(100 * p["active_days"] / p["days"], 1)
    return p, ev, len(files)


def scores(p):
    out = {}
    for key, _, parts, _ in DIMENSIONS:
        vals = []
        for metric, lo, hi in parts:
            v = p.get(metric)
            if v is not None:
                vals.append(max(0.0, min(1.0, (v - lo) / (hi - lo))) * 100)
        out[key] = round(max(vals)) if vals else None
    if p["stop_days"] < 2:
        out["stopping"] = None  # not enough of my own stop signals to say anything
    return out


def propose(p, s):
    """Values come from my own numbers. A guard is proposed when its dimension scores 50 or more."""
    hi = lambda k, t=50: s.get(k) is not None and s[k] >= t
    g = {
        "P1_landing": hi("stopping") or hi("edges"),
        "P2_contract": hi("reply_load") or hi("decisions") or hi("track"),
        "P3_threads": hi("threads"),
        "P4_ledger": hi("track") and p["commits"] > 0,
        "P5_waiting": hi("threads"),
        "P6_brief": hi("track") or hi("steering"),
        "P7_focus": hi("threads"),
        "P8_reviewer": False,  # a second model costs usage: only if I switch it on myself
        "P11_digit": hi("stopping") or hi("edges"),
    }
    why = {}
    cfg = {"all": True, "guards": g, "day_starts_at_hour": 5, "installed_on": None,
           "languages": None, "reeval_every_days": 14,
           "budget": {"max_read_tokens": 150000, "reader_model": "the cheapest model available",
                      "ask_before_more": True}}
    if g["P3_threads"]:
        cfg["thread_threshold"] = int(max(2, min(5, round((p["sessions_per_day"] or 4) / 2))))
        cfg["thread_block"] = hi("threads", 75)
        why["thread_threshold"] = "half of my median of {} sessions a day, kept between 2 and 5".format(
            R.fmt(p["sessions_per_day"]))
        why["thread_block"] = "a hard stop only when 'many things at once' scores 75 or more; otherwise a note"
    if hi("edges"):
        cfg["work_note_hours"] = int(max(1, min(3, round((p["span_h"] or 8) / 4))))
        why["work_note_hours"] = "a quarter of my median day of {} h, kept between 1 and 3".format(R.fmt(p["span_h"]))
        if (p["late23_pct"] or 0) >= 8:
            cfg["work_note_hours_night"] = 0.5
            why["work_note_hours_night"] = "{}% of my messages come between 23:00 and 05:00".format(R.fmt(p["late23_pct"]))
    if g["P6_brief"]:
        cfg["brief_at_start"] = hi("track", 75) or hi("steering", 75)
        why["brief_at_start"] = "at every session start only when the score is 75 or more; otherwise on request"
    cfg["format"] = {"bold_first": True, "needs_you_line": hi("decisions") or hi("track"),
                     "open_line": "top" if hi("track") else "off", "max_questions": 1 if hi("decisions") else 2,
                     "short_sentences": False, "numbered_sentences": False, "decide_small_things": hi("decisions"),
                     "new_directions": "block", "check_marks": True}
    why["format"] = "a starting point from the counts; my answers in the setup replace it"
    return cfg, why


def standing_words(cfg):
    """Words added to EVERY message by the proposed guards. That is a usage cost, so it is shown."""
    g, n = cfg["guards"], 0
    count = lambda name: len(G.text(name).split())
    if g.get("P2_contract"):
        n += len(G.contract_text(cfg).split())
    n += count("waiting.md") if g.get("P5_waiting") else 0
    n += count("reviewer.md") if g.get("P8_reviewer") else 0
    n += count("focus.md") if g.get("P7_focus") else 0
    return n + 60


def radar(s):
    keys = [(k, label) for k, label, _, _ in DIMENSIONS]
    cx, cy, rad, n = 260, 215, 140, len(keys)
    pt = lambda i, r: (cx + r * math.sin(2 * math.pi * i / n), cy - r * math.cos(2 * math.pi * i / n))
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 430" font-family="sans-serif" font-size="12">',
         '<rect width="520" height="430" fill="white"/>']
    for ring in (0.25, 0.5, 0.75, 1):
        o.append('<polygon fill="none" stroke="#ccc" points="{}"/>'.format(
            " ".join("%.1f,%.1f" % pt(i, rad * ring) for i in range(n))))
    for i, (k, label) in enumerate(keys):
        x, y = pt(i, rad)
        o.append('<line x1="{}" y1="{}" x2="{:.1f}" y2="{:.1f}" stroke="#ccc"/>'.format(cx, cy, x, y))
        lx, ly = pt(i, rad + 22)
        anchor = "middle" if abs(lx - cx) < 20 else ("start" if lx > cx else "end")
        val = "no data" if s[k] is None else str(s[k])
        o.append('<text x="{:.1f}" y="{:.1f}" text-anchor="{}">{} ({})</text>'.format(lx, ly, anchor, label, val))
    o.append('<polygon fill="#3b6fb6" fill-opacity="0.3" stroke="#3b6fb6" stroke-width="2" points="{}"/>'.format(
        " ".join("%.1f,%.1f" % pt(i, rad * (s[k] or 0) / 100) for i, (k, _) in enumerate(keys))))
    o.append('<text x="260" y="420" text-anchor="middle" fill="#666">0 = not seen in my record · 100 = strong · '
             'anchors are provisional</text></svg>')
    return "\n".join(o)


def write_profile(p, s, cfg, why, nfiles):
    low = p["active_days"] < 14 or p["msgs"] < 200
    L = ["# PROFILE — what my own record shows, and what was proposed for me", "",
         "Made by `assess.py` on {}. Counts from {} transcript files, {} to {} ({} active days, {} messages of mine)."
         .format(G.now().date(), nfiles, p["from"], p["to"], p["active_days"], p["msgs"]),
         "Everything is **data** (counts) unless marked as inference. This is not a diagnosis.", ""]
    if low:
        L += ["**Thin record: fewer than 14 active days or 200 messages. Treat every score as a hint. My own answers "
              "in the setup count more than these numbers.**", ""]
    L += ["![radar](profile_radar.svg)", "", "| What shows on the screen | Score | My numbers | Guard that answers it |",
          "|---|---|---|---|"]
    for key, label, parts, guard in DIMENSIONS:
        nums = "; ".join("{} = {}".format(m, R.fmt(p.get(m))) for m, _, _ in parts)
        L.append("| {} | {} | {} | {} |".format(label, "no data" if s[key] is None else s[key], nums, guard))
    L += ["", "Scores are relative to provisional anchors (see `docs/DIMENSIONS.md`). A low score does not mean "
          "'no problem'; it means the counts do not show it (inference).", "",
          "## Proposed for me (nothing is active until I say yes)", ""]
    for k, v in cfg["guards"].items():
        L.append("- {} **{}** — {}".format(k.split("_")[0], "on" if v else "off", G.NAMES[k]))
    L += [""] + ["- `{}` = {} — because: {}".format(k, json.dumps(cfg.get(k)) if k != "format" else "see below", w)
                 for k, w in why.items()]
    L += ["", "Reply shape (`format`): " + ", ".join("{}={}".format(k, v) for k, v in cfg["format"].items()), "",
          "## What this costs", "",
          "- This assessment cost no usage: it is a script that counts.",
          "- The proposed guards add about **{} words to every message** I send. That is a usage cost. Fewer guards, "
          "fewer words.".format(standing_words(cfg)),
          "- Reading sessions with a model is optional, off by default, capped at {} tokens, and needs my explicit yes "
          "each time (`assess.py sample`).".format(cfg["budget"]["max_read_tokens"]), "",
          "## What the counts cannot see", "",
          "- How I felt. Whether I want more or fewer new ideas from Claude. Whether I read long replies easily.",
          "- That is what the questions in the setup are for. My answers win over the counts.",
          "- Web and phone chats are not counted.", "",
          "## Change it", "",
          "- One value: `python3 assess.py set thread_threshold=4` · one guard: `python3 assess.py set P1_landing=off`",
          "- Reply shape: `python3 assess.py format numbered_sentences=yes max_questions=1`",
          "- Accept: `python3 assess.py accept`, then `python3 install.py`. Off again: type `guards off`.", ""]
    with open(PROFILE, "w") as f:
        f.write("\n".join(L))
    with open(RADAR, "w") as f:
        f.write(radar(s))


def parse(v, kind):
    if kind is bool:
        return v.lower() in ("yes", "y", "true", "on", "1", "ja")
    if kind is int:
        return int(v)
    if isinstance(kind, tuple):
        if v not in kind:
            raise ValueError("must be one of " + ", ".join(kind))
        return v
    return v


def cmd_edit(args, fmt):
    cfg = G.load(PROPOSED, None)
    if cfg is None:
        print("Run `python3 assess.py` first.")
        return
    for a in args:
        k, _, v = a.partition("=")
        try:
            if fmt:
                if k not in FORMAT_KEYS:
                    print("Unknown:", k, "· known:", ", ".join(FORMAT_KEYS))
                    continue
                cfg.setdefault("format", {})[k] = parse(v, FORMAT_KEYS[k])
            elif k in G.NAMES or any(n.split("_")[0].lower() == k.lower() for n in G.NAMES):
                name = k if k in G.NAMES else [n for n in G.NAMES if n.split("_")[0].lower() == k.lower()][0]
                cfg["guards"][name] = parse(v, bool)
            elif k == "budget.max_read_tokens":
                cfg["budget"]["max_read_tokens"] = int(v)
            elif k == "languages":
                cfg[k] = [x for x in v.split(",") if x]
            else:
                cfg[k] = json.loads(v) if v.lower() not in ("yes", "no", "on", "off") else parse(v, bool)
        except Exception as e:
            print("Not set:", a, "·", e)
    G.save(PROPOSED, cfg)
    print("Proposal updated:", PROPOSED)
    print("Words added to every message now: about", standing_words(cfg))


def cmd_accept():
    cfg = G.load(PROPOSED, None)
    if cfg is None:
        print("Run `python3 assess.py` first.")
        return
    old = G.load(G.CONFIG, None)
    if old is not None:
        G.save(G.CONFIG + ".before_" + G.now().strftime("%Y-%m-%d_%H%M"), old)
        cfg["installed_on"] = old.get("installed_on")
    cfg["installed_on"] = cfg.get("installed_on") or str(G.now().date())
    G.save(G.CONFIG, cfg)
    G.write_active(cfg)
    G.event("config accepted from the assessment")
    print("This is my config now:", G.CONFIG)
    print("What is active:", G.ACTIVE)
    print("Hooks are installed by: python3 install.py   (asks nothing, makes a backup, undo with --remove)")


def cmd_sample(n):
    """Which sessions would be worth reading, and what would that cost? Reads nothing."""
    c = G.load(PROPOSED, None) or G.cfg()
    cap = int((c.get("budget") or {}).get("max_read_tokens", 150000))
    seen, ev = set(), []
    for f in R.transcript_files():
        try:
            R.scan(f, seen, ev)
        except Exception:
            pass
    per = collections.defaultdict(lambda: {"chars": 0, "stop": 0, "late": 0, "msgs": 0, "last": None})
    for t, sid, k, d in ev:
        s = per[sid]
        if k in ("h", "a"):
            s["chars"] += d["len"]
            s["last"] = t
        if k == "h":
            s["msgs"] += 1
            s["stop"] += d["phrase"]
            s["late"] += t.hour >= 23 or t.hour < 5
    cand = [(sid, s) for sid, s in per.items() if s["msgs"] >= 5]
    cand.sort(key=lambda x: x[1]["chars"])
    pick, add = [], lambda xs: [pick.append(x) for x in xs if x not in pick]
    add(sorted(cand, key=lambda x: -x[1]["stop"])[:max(1, n // 3)])
    add(sorted(cand, key=lambda x: -x[1]["late"])[:max(1, n // 3)])
    mid = len(cand) // 2
    add(cand[max(0, mid - n):mid + n])
    pick = pick[:n]
    total = 0
    print("Sessions worth reading (a suggestion; nothing was read):\n")
    for sid, s in pick:
        tok = int(s["chars"] / 3.5)
        total += tok
        print("  {}  {}  {:4} msgs  about {:>7,} tokens  {}{}".format(
            sid[:8], s["last"].strftime("%Y-%m-%d") if s["last"] else "?", s["msgs"], tok,
            "stop words " if s["stop"] else "", "late night" if s["late"] else ""))
    print("\nReading all {} once: at least {:,} tokens of input (tool output inside the sessions comes on top), plus the "
          "reader's own output.".format(len(pick), total))
    print("My cap (budget.max_read_tokens): {:,}.".format(cap))
    if total > cap:
        print("OVER THE CAP. Read fewer sessions, or raise the cap yourself: "
              "`python3 assess.py set budget.max_read_tokens=N`. Nothing raises it for you.")
    print("Rules for whoever reads (the setup skill follows them): cheapest model, one reader at a time, "
          "stop at the cap, and ask me explicitly before every run, with this estimate.")


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print(__doc__)
    elif a and a[0] == "format":
        cmd_edit(a[1:], True)
    elif a and a[0] == "set":
        cmd_edit(a[1:], False)
    elif a and a[0] == "accept":
        cmd_accept()
    elif a and a[0] == "sample":
        cmd_sample(int(a[1]) if len(a) > 1 else 6)
    else:
        p, ev, nfiles = measure()
        s = scores(p)
        cfg, why = propose(p, s)
        old = G.load(PROPOSED, None)
        if old and old.get("format"):
            cfg["format"] = old["format"]  # my answers survive a new count
        G.save(PROPOSED, cfg)
        write_profile(p, s, cfg, why, nfiles)
        G.save(os.path.join(G.STATE, "profile.json"), {"date": str(G.now().date()), "scores": s,
                                                        "period": {k: v for k, v in p.items()}})
        print(open(PROFILE).read().split("## What this costs")[0].rstrip())
        print("\nFull profile:", PROFILE, "· radar:", RADAR)
        print("Nothing was installed or changed. Proposal:", PROPOSED)


if __name__ == "__main__":
    main()
