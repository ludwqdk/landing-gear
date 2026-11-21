#!/usr/bin/env python3
"""Daily overview: my usage numbers, plotted, as one local HTML page. Standard library only.

  daily.py                 count (costs no usage) and write reports/daily/overview.html
  daily.py --open          the same, then open the page in the browser
  daily.py schedule HH:MM  macOS: run `daily.py --open` every day at that time (a LaunchAgent)
  daily.py unschedule      remove that again

The page needs no internet and loads nothing from outside. Numbers and times only, no message text.
The counting is the same as in reeval.py. This reports usage patterns; it is not a diagnosis.
"""
import collections
import datetime as dt
import html
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guards as G  # noqa: E402
import reeval as R  # noqa: E402

OUT = os.path.join(R.PROJECT, "reports", "daily", "overview.html")
LABEL = "com.guards.daily-overview"
PLIST = os.path.expanduser("~/Library/LaunchAgents/{}.plist".format(LABEL))
DAYS = 42
W, PADL, PADR = 960, 46, 14
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def refresh(c):
    seen, ev = set(), []
    for f in R.transcript_files():
        try:
            R.scan(f, seen, ev)
        except Exception:
            pass
    rows = R.merge(G.load(R.DAYS, {}), R.day_rows(ev, c))
    G.save(R.DAYS, rows)
    return rows


def guard_events(c):
    """What the guards did, per work day."""
    per = collections.defaultdict(collections.Counter)
    kinds = (("landing", "landing ON"), ("held", "BLOCKED session"), ("released", "block lifted"),
             ("brief off", "start brief OFF"), ("time note", "time note:"), ("guards off", "all guards OFF"))
    try:
        for line in open(G.EVENTS):
            try:
                t = dt.datetime.strptime(line[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            for name, pat in kinds:
                if pat in line[18:]:
                    per[str(G.workday(t, c))][name] += 1
    except Exception:
        pass
    digits = {}
    try:
        for line in open(G.MOOD):
            p = line.strip().split(",")
            if len(p) >= 2 and p[1].isdigit():
                digits[p[0]] = int(p[1])
    except Exception:
        pass
    return per, digits, [k for k, _ in kinds]


def esc(s):
    return html.escape(str(s), quote=True)


def nice_max(v):
    """The smallest round axis maximum (four equal steps) that holds v."""
    if v <= 0:
        return 1
    k = 1.0
    while True:
        for m in (1, 2, 2.5, 3, 4, 5, 6, 8):
            if v <= m * k * 4:
                top = m * k * 4
                return int(top) if top == int(top) else top
        k *= 10


class Chart:
    """One small panel. All panels share the same x positions, one day per slot."""

    def __init__(self, days, h=150, ymax=1, unit="", install=None):
        self.days, self.h, self.ymax, self.unit, self.install = days, h, nice_max(ymax), unit, install
        self.top, self.bot = 12, 22
        self.slot = (W - PADL - PADR) / len(days)
        self.bw = min(24, max(3, self.slot - 2))
        self.o = []

    def x(self, i):
        return PADL + self.slot * (i + 0.5)

    def y(self, v):
        return self.top + (self.h - self.top - self.bot) * (1 - v / self.ymax)

    def frame(self, fmt=lambda v: "%g" % v, ticks=4):
        o = ['<svg viewBox="0 0 {} {}" role="img">'.format(W, self.h)]
        for k in range(ticks + 1):
            v = self.ymax * k / ticks
            yy = self.y(v)
            o.append('<line class="{}" x1="{}" x2="{}" y1="{:.1f}" y2="{:.1f}"/>'.format(
                "axis" if k == 0 else "grid", PADL, W - PADR, yy, yy))
            o.append('<text class="tick" x="{}" y="{:.1f}" text-anchor="end">{}</text>'.format(PADL - 6, yy + 4, fmt(v)))
        for i, d in enumerate(self.days):
            day = dt.date.fromisoformat(d)
            if day.weekday() == 0:
                o.append('<text class="tick" x="{:.1f}" y="{}" text-anchor="middle">{}</text>'.format(
                    self.x(i), self.h - 6, day.strftime("%d.%m.")))
        if self.install in self.days:
            xi = self.x(self.days.index(self.install)) - self.slot / 2
            o.append('<line class="mark" x1="{0:.1f}" x2="{0:.1f}" y1="{1}" y2="{2:.1f}"/>'.format(xi, 2, self.y(0)))
            o.append('<text class="tick" x="{:.1f}" y="10">guards on</text>'.format(xi + 4))
        self.o = o + self.o
        return "\n".join(self.o + ["</svg>"])

    def bar(self, i, lo, hi, cls, tip):
        y1, y0 = self.y(hi), self.y(lo)
        if y0 - y1 < 0.5:
            return
        hgt, x0, r = y0 - y1, self.x(i) - self.bw / 2, min(4, self.bw / 2, (y0 - y1))
        # rounded at the data end, square at the baseline
        d = "M{:.1f},{:.1f} v{:.1f} q0,-{r} {r},-{r} h{:.1f} q{r},0 {r},{r} v{:.1f} z".format(
            x0, y0, -(hgt - r), self.bw - 2 * r, hgt - r, r=r)
        self.o.append('<path class="{}" d="{}" data-tip="{}"/>'.format(cls, d, esc(tip)))

    def seg(self, i, lo, hi, cls, tip):  # stacked segment with a 2px surface gap
        y1, y0 = self.y(hi), self.y(lo)
        if y0 - y1 < 2.5:
            return
        self.o.append('<rect class="{}" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" data-tip="{}"/>'.format(
            cls, self.x(i) - self.bw / 2, y1 + 1, self.bw, y0 - y1 - 2, esc(tip)))

    def line(self, vals, cls, tips=None, label=None):
        pts = [(self.x(i), self.y(v)) for i, v in enumerate(vals) if v is not None]
        if len(pts) > 1:
            self.o.append('<polyline class="ln {}" points="{}"/>'.format(
                cls, " ".join("%.1f,%.1f" % p for p in pts)))
        if tips:
            for i, v in enumerate(vals):
                if v is not None:
                    self.o.append('<circle class="hit" cx="{:.1f}" cy="{:.1f}" r="7" data-tip="{}"/>'.format(
                        self.x(i), self.y(v), esc(tips[i])))
        if label and pts:
            self.o.append('<circle class="dot {}" cx="{:.1f}" cy="{:.1f}" r="4"/>'.format(cls, *pts[-1]))
            self.o.append('<text class="lab" x="{:.1f}" y="{:.1f}" text-anchor="end">{}</text>'.format(
                pts[-1][0] - 8, pts[-1][1] - 8, esc(label)))


def hm(s):
    return s[11:16] if s else "–"


def clock(s, c):
    """Hours since the start of the work day (05:00 = 0)."""
    t = dt.datetime.fromisoformat(s)
    return ((t.hour + t.minute / 60) - int(c.get("day_starts_at_hour", 5))) % 24


def build(rows, c):
    today = G.workday(G.now(), c)
    days = [str(today - dt.timedelta(days=k)) for k in range(DAYS, 0, -1)]
    g = lambda d, k, default=0: rows.get(d, {}).get(k, default) or default
    inst = c.get("installed_on")
    label = lambda d: "{} {}".format(WD[dt.date.fromisoformat(d).weekday()], dt.date.fromisoformat(d).strftime("%d.%m."))
    per, digits, kinds = guard_events(c)
    yday = days[-1]

    # ---- tiles: yesterday against the median of the 28 days before
    prev = days[-29:-1]
    med = lambda k: statistics.median([g(d, k) for d in prev if g(d, "msgs")] or [0])
    fmt = lambda v: ("%.1f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    y = rows.get(yday, {})
    tiles = [("My messages", fmt(g(yday, "msgs")), "28-day median " + fmt(med("msgs"))),
             ("Engaged hours", fmt(float(g(yday, "eng_h", 0.0))), "28-day median " + fmt(float(med("eng_h")))),
             ("First – last message", "{} – {}".format(hm(y.get("first")), hm(y.get("last"))) if y.get("msgs") else "no use",
              "{} h from first to last".format(fmt(float(g(yday, "span_h", 0.0))))),
             ("Sessions / folders", "{} / {}".format(g(yday, "sessions"), g(yday, "projects")),
              "28-day median {} / {}".format(fmt(med("sessions")), fmt(med("projects")))),
             ("Messages after 23:00", fmt(g(yday, "late23")), "of these after 01:00: " + fmt(g(yday, "late01")))]
    T = "".join('<div class="tile"><div class="k">{}</div><div class="v">{}</div><div class="s">{}</div></div>'.format(
        esc(a), esc(b), esc(s)) for a, b, s in tiles)

    # ---- 1 messages per day + 7-day average
    msgs = [g(d, "msgs") for d in days]
    c1 = Chart(days, 170, max(msgs + [1]), install=inst)
    for i, d in enumerate(days):
        c1.bar(i, 0, msgs[i], "s1", "{}: {} messages".format(label(d), msgs[i]))
    avg = [round(sum(msgs[max(0, i - 6):i + 1]) / len(msgs[max(0, i - 6):i + 1]), 1) for i in range(len(days))]
    c1.line(avg, "ink", label="7-day average")

    # ---- 2 engaged hours
    eng = [float(g(d, "eng_h", 0.0)) for d in days]
    c2 = Chart(days, 130, max(eng + [1]), install=inst)
    for i, d in enumerate(days):
        c2.bar(i, 0, eng[i], "s1", "{}: {} h engaged".format(label(d), fmt(eng[i])))

    # ---- 3 active window, 05:00 to 05:00
    c3 = Chart(days, 190, 24, install=inst)
    c3.ymax = 24
    for i, d in enumerate(days):
        r = rows.get(d, {})
        if r.get("msgs"):
            a, b = clock(r["first"], c), clock(r["last"], c)
            a, b = (a, max(b, a + 0.25))
            yy1, yy0 = c3.y(24 - a), c3.y(24 - b)  # time runs downwards
            c3.o.append('<rect class="s1" rx="3" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" '
                        'data-tip="{}"/>'.format(c3.x(i) - c3.bw / 2, yy1, c3.bw, max(2, yy0 - yy1),
                                                 esc("{}: {} – {}".format(label(d), hm(r["first"]), hm(r["last"])))))
    start = int(c.get("day_starts_at_hour", 5))
    s3 = c3.frame(fmt=lambda v: "%02d:00" % ((start + 24 - int(v)) % 24), ticks=4)

    # ---- 4 late night, stacked: one hue, darker = later
    c4 = Chart(days, 150, max(msgs + [1]), install=inst)
    for i, d in enumerate(days):
        l23, l01 = g(d, "late23"), g(d, "late01")
        day = msgs[i] - l23
        c4.seg(i, 0, day, "q1", "{}: {} before 23:00".format(label(d), day))
        c4.seg(i, day, day + l23 - l01, "q2", "{}: {} between 23:00 and 01:00".format(label(d), l23 - l01))
        c4.seg(i, day + l23 - l01, msgs[i], "q3", "{}: {} after 01:00".format(label(d), l01))

    # ---- 5 switches between sessions
    sw = [g(d, "switches") for d in days]
    c5 = Chart(days, 130, max(sw + [1]), install=inst)
    for i, d in enumerate(days):
        c5.bar(i, 0, sw[i], "s1", "{}: {} switches between sessions".format(label(d), sw[i]))

    # ---- 6 sessions and folders
    ses = [g(d, "sessions") if g(d, "msgs") else None for d in days]
    prj = [g(d, "projects") if g(d, "msgs") else None for d in days]
    c6 = Chart(days, 140, max([v or 0 for v in ses] + [1]), install=inst)
    c6.line(ses, "s1", tips=["{}: {} sessions, {} folders".format(label(d), ses[i], prj[i]) for i, d in enumerate(days)],
            label="sessions")
    c6.line(prj, "s2", label="folders")

    # ---- 7 weekday
    by = collections.defaultdict(list)
    for d in days:
        if g(d, "msgs"):
            by[dt.date.fromisoformat(d).weekday()].append(g(d, "msgs"))
    wk = [round(statistics.mean(by[k]), 1) if by[k] else 0 for k in range(7)]
    mx, bars = max(wk + [1]), []
    for k in range(7):
        bars.append('<div class="wrow"><span class="wl">{}</span><span class="wb" style="width:{:.1f}%" '
                    'data-tip="{}: {} messages on an average active day ({} days)"></span><span class="wv">{}</span></div>'
                    .format(WD[k], 78 * wk[k] / mx, WD[k], fmt(wk[k]), len(by[k]), fmt(wk[k])))

    # ---- guard marks since the install
    gd = [d for d in days if inst and d >= inst] + [str(today)]
    marks = ""
    if inst and any(per.get(d) or d in digits for d in gd):
        head = "".join("<th>{}</th>".format(esc(label(d))) for d in gd)
        body = "".join("<tr><th>{}</th>{}</tr>".format(esc(k), "".join(
            "<td>{}</td>".format(per[d][k] or "") for d in gd)) for k in kinds)
        body += "<tr><th>day digit (1–5)</th>{}</tr>".format("".join("<td>{}</td>".format(digits.get(d, "")) for d in gd))
        marks = ('<section><h2>What the guards did</h2><p class="sub">Counts per day since the install on {}. '
                 'Last column: today so far.</p><div class="scroll"><table class="log"><tr><th></th>{}</tr>{}</table>'
                 '</div></section>').format(esc(inst), head, body)

    # ---- table
    cols = [("msgs", "msgs"), ("first", "first"), ("last", "last"), ("span_h", "span h"), ("eng_h", "eng h"),
            ("sessions", "sess"), ("projects", "folders"), ("switches", "switches"), ("late23", ">23:00"),
            ("late01", ">01:00")]
    trs = []
    for d in reversed(days):
        r = rows.get(d, {})
        if not r.get("msgs"):
            trs.append('<tr><td>{}</td><td colspan="{}" class="muted">no use</td></tr>'.format(esc(label(d)), len(cols)))
            continue
        trs.append("<tr><td>{}</td>{}</tr>".format(esc(label(d)), "".join(
            "<td>{}</td>".format(esc(hm(r.get(k)) if k in ("first", "last") else fmt(r.get(k, "–")))) for k, _ in cols)))
    table = '<table class="log"><tr><th>day</th>{}</tr>{}</table>'.format(
        "".join("<th>{}</th>".format(h) for _, h in cols), "".join(trs))

    sec = lambda title, sub, body: '<section><h2>{}</h2><p class="sub">{}</p>{}</section>'.format(title, sub, body)
    legend4 = ('<p class="legend"><span><i class="sw q1"></i>before 23:00</span><span><i class="sw q2"></i>23:00–01:00'
               '</span><span><i class="sw q3"></i>after 01:00</span></p>')
    legend6 = '<p class="legend"><span><i class="sw s1"></i>sessions</span><span><i class="sw s2"></i>folders</span></p>'
    page = PAGE.replace("{{DATE}}", esc(G.now().strftime("%A %d.%m.%Y, %H:%M"))) \
        .replace("{{YDAY}}", esc(label(yday))).replace("{{RANGE}}", esc("{} to {}".format(label(days[0]), label(yday)))) \
        .replace("{{TILES}}", T).replace("{{BODY}}", "".join([
            sec("My messages per day", "Bars: messages I typed. Line: average of the last 7 days.", c1.frame()),
            sec("Engaged hours per day", "Time between my messages when the gap was under 15 minutes. A lower bound: "
                "reading and waiting are not in it.", c2.frame()),
            sec("Active window", "From my first to my last message of the day. The axis runs from {0:02d}:00 at the top "
                "to {0:02d}:00 the next morning.".format(start), s3),
            sec("Day and night", "My messages by time of day.", legend4 + c4.frame()),
            sec("Switches between sessions", "How often two messages in a row went to different sessions.", c5.frame()),
            sec("Sessions and folders", "How many sessions and project folders I wrote in.", legend6 + c6.frame()),
            sec("Average by weekday", "Messages on an average active day, in this period.",
                '<div class="wk">{}</div>'.format("".join(bars))),
            marks,
            '<section><h2>Daily log</h2><p class="sub">The numbers behind the charts. A day runs from {0:02d}:00 to '
            '{0:02d}:00, so work after midnight counts to the evening before.</p><div class="scroll">{1}</div></section>'
            .format(start, table)]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(page)
    return OUT


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily overview</title>
<style>
:root{--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--s1:#2a78d6;--s2:#eb6834;--q1:#86b6ef;--q2:#2a78d6;--q3:#104281}
@media (prefers-color-scheme: dark){:root{--plane:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--s1:#3987e5;--s2:#d95926;--q1:#1c5cab;--q2:#5598e7;--q3:#cde2fb}}
*{box-sizing:border-box}body{margin:0;background:var(--plane);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 60px}h1{font-size:22px;margin:0 0 2px}
h2{font-size:16px;margin:0}.sub{color:var(--ink2);margin:2px 0 10px;font-size:13px}.muted{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}
.tile,section{background:var(--surface);border:1px solid var(--grid);border-radius:10px;padding:14px 16px}
section{margin:14px 0}.k{color:var(--ink2);font-size:12px}.v{font-size:26px;font-weight:650;margin:2px 0}
.s{color:var(--muted);font-size:12px}svg{width:100%;height:auto;display:block}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}.mark{stroke:var(--muted);stroke-width:1}
.tick{fill:var(--muted);font-size:11px}.lab{fill:var(--ink2);font-size:11px}
.s1{fill:var(--s1)}.s2{fill:var(--s2)}.q1{fill:var(--q1)}.q2{fill:var(--q2)}.q3{fill:var(--q3)}
.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.ln.s1{stroke:var(--s1)}.ln.s2{stroke:var(--s2)}
.ln.ink{stroke:var(--ink)}.dot{stroke:var(--surface);stroke-width:2}.dot.ink{fill:var(--ink)}.hit{fill:transparent}
[data-tip]:hover{opacity:.75}.legend{margin:0 0 6px;font-size:12px;color:var(--ink2)}.legend span{margin-right:14px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;background:var(--s1)}
.sw.s2{background:var(--s2)}.sw.q1{background:var(--q1)}.sw.q2{background:var(--q2)}.sw.q3{background:var(--q3)}
.wk{max-width:560px}.wrow{display:flex;align-items:center;gap:8px;margin:5px 0}.wl{width:34px;color:var(--ink2);font-size:12px}
.wb{height:16px;background:var(--s1);border-radius:0 4px 4px 0;min-width:1px}.wv{font-size:12px;color:var(--ink2)}
.scroll{overflow-x:auto}table.log{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;width:100%}
.log th,.log td{padding:4px 9px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
.log th:first-child,.log td:first-child{text-align:left}.log th{color:var(--ink2);font-weight:600}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);padding:5px 9px;border-radius:6px;
font-size:12px;display:none;z-index:9;max-width:280px}
footer{color:var(--muted);font-size:12px;margin-top:18px}
</style></head><body><main>
<h1>Daily overview</h1>
<p class="sub">Built {{DATE}} · tiles: {{YDAY}} · charts: {{RANGE}} · counts of my local Claude Code sessions</p>
<div class="tiles">{{TILES}}</div>
{{BODY}}
<footer>Counts show what happened on the screen, not how I felt. A message at night proves I was awake; a long pause
does not prove sleep. Web and phone chats are not counted. This is not a diagnosis.</footer>
</main><div id="tip"></div>
<script>
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
if(!t){tip.style.display='none';return}
tip.textContent=t.getAttribute('data-tip');tip.style.display='block';
const x=Math.min(e.clientX+14,window.innerWidth-tip.offsetWidth-8);
tip.style.left=x+'px';tip.style.top=(e.clientY+16)+'px'});
</script></body></html>
"""


def schedule(hhmm):
    try:
        hh, mm = [int(x) for x in hhmm.split(":")]
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        print("Use: daily.py schedule HH:MM")
        return
    if sys.platform != "darwin":
        print("Scheduling is built for macOS only. Elsewhere: let cron run `python3 {} --open`."
              .format(os.path.abspath(__file__)))
        return
    log = os.path.join(G.STATE, "daily.log")
    os.makedirs(G.STATE, exist_ok=True)
    plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>{py}</string><string>{me}</string><string>--open</string></array>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer></dict>
<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""".format(label=LABEL, py=sys.executable, me=html.escape(os.path.abspath(__file__)), hh=hh, mm=mm, log=html.escape(log))
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    uid = "gui/{}".format(os.getuid())
    subprocess.run(["launchctl", "bootout", uid, PLIST], capture_output=True)
    with open(PLIST, "w") as f:
        f.write(plist)
    r = subprocess.run(["launchctl", "bootstrap", uid, PLIST], capture_output=True, text=True)
    print("Scheduled: every day at {:02d}:{:02d} the overview is built and opened in the browser.".format(hh, mm))
    print("File:", PLIST, "· remove with: python3 daily.py unschedule")
    if r.returncode:
        print("launchctl said:", r.stderr.strip())
    G.event("daily overview scheduled at {:02d}:{:02d}".format(hh, mm))


def unschedule():
    subprocess.run(["launchctl", "bootout", "gui/{}".format(os.getuid()), PLIST], capture_output=True)
    if os.path.exists(PLIST):
        os.remove(PLIST)
    print("Removed. The overview no longer opens by itself.")
    G.event("daily overview unscheduled")


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print(__doc__)
    elif a and a[0] == "schedule":
        schedule(a[1] if len(a) > 1 else "")
    elif a and a[0] == "unschedule":
        unschedule()
    else:
        c = G.cfg()
        out = build(refresh(c), c)
        print("Daily overview:", out)
        if "--open" in a:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", out])


if __name__ == "__main__":
    main()
