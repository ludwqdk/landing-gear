# landing-gear — personal safeguards for working with Claude Code

Working with an AI agent all day can wear a person down: too many threads at once, replies far longer than the question, a stream of small decisions, no natural stopping point. Which of these hits you, and how hard, differs from person to person.

This package does not ship one set of rules. It **looks at your own record first**, proposes guards with values taken from your numbers and your answers, and installs only what you agree to. Later it checks, with the same counts, whether they helped.

**Status: early draft (v0.1).** Built from one person's experience and tested on one machine (macOS, Claude Code desktop app and CLI). Expect rough edges. Read "Limits" before you rely on it.

## Principles

1. **Individual.** Nobody gets somebody else's settings. Every value comes from your own sessions and your own answers.
2. **Symptoms, not diagnoses.** It was started by someone with ADHD, but it never asks for a diagnosis. It looks at what shows on the screen.
3. **Same information.** A guard may change the order and shape of Claude's replies. It never tells Claude to say less. Reducing content is a separate decision that only you can take.
4. **Transparent.** Every session starts with one line saying which guards are active. `ACTIVE.md` lists them. `PROFILE.md` says why. You should never wonder why Claude behaves differently.
5. **Reversible.** Type `guards off` in any session. `python3 install.py --remove` takes the hooks out again.
6. **Private.** Standard-library Python, no network calls, nothing leaves your machine. Logs hold times and session ids, never message text (one exception, see Limits).
7. **Careful with your usage.** The assessment is a script and costs nothing. Anything that would spend tokens says how many first and asks. It never raises its own budget.
8. **Not finished after one try.** A built-in re-evaluation compares before and after, and deleting a guard that does not help counts as a good result.

## Start

```bash
git clone https://github.com/ludwqdk/landing-gear.git ~/landing-gear
```

```bash
cd ~/landing-gear/guards && python3 assess.py
```

Read `PROFILE.md`. Change what does not fit (`python3 assess.py set …`, `python3 assess.py format …`). Then:

```bash
python3 assess.py accept
```

```bash
python3 install.py
```

Or let Claude walk you through it, including the questions about reply shape with side-by-side examples: copy `skills/guards-setup` and `skills/brief` to `~/.claude/skills/` and say "guards setup" in a session opened in this folder.

## What a guard can be

| Guard | What it does | Proposed when your record shows |
|---|---|---|
| Landing mode | Your own words ("I am tired", "done for today") stop new work, save the state, move reviews to tomorrow | you kept going after saying stop; long days and nights |
| Reply shape | Result first, what needs you, what is open, at most N questions, ideas in one block; built from your answers | much more text back than you send; many questions put to you |
| Session limit | A note, or a hold until you type `free`, when you open more sessions per hour than your own limit | many things at once |
| Focus / free / carry | Stay on the first topic by default; `free` to wander; `carry` when you are tired and want Claude to take the small decisions | many things at once |
| Start brief | Five fields before work starts: goal, done when, stop points, not in scope, landing for today | losing track; stopping Claude often |
| Built-ledger | One plain entry per commit in one central file | losing track |
| Time note | One line in the chat after every N hours of work in a day, more often at night | long days, late nights |
| Waiting | Claude says when a long job ends and what it needs from you | many things at once |
| Second reader | A second model reviews milestones. Off unless you switch it on: it costs usage | never proposed |
| Day digit | One digit, 1 to 5, when landing starts. Feeds the re-evaluation | whenever landing mode is on |

How the scores are counted: `docs/DIMENSIONS.md`. The rules of the re-evaluation: `docs/RULES.md`.

## Words you can type as a whole message

`guards off` · `guards on` · `free` · `focus` · `carry` · `landing` · `continue anyway` · `brief off` · `brief on` · `reeval` (German words such as `frei`, `fokus`, `weiter`, `schluss` work too.)

## Did it help?

Type `reeval` in a session, or run `python3 reeval.py`. It compares the four weeks before the install with the time since, using the same code for both, and asks you three questions: could I work well, was AI still useful, did I feel good using it. Your own rating outweighs every count. A reminder line appears at session start when a check is due; there are no calendar entries.

## A daily overview

```bash
python3 daily.py --open
```

One local HTML page with your numbers as charts: messages and engaged hours per day, the window from first to last message, day and night, switches between sessions, weekdays, and what the guards did. No internet, nothing loaded from outside, no usage. On macOS `python3 daily.py schedule 09:00` builds and opens it every morning; `python3 daily.py unschedule` stops that.

## Limits

- **Not a diagnosis, not treatment, not medical advice.** It reports patterns in usage data.
- The anchors that turn counts into scores are provisional. They come from one heavy user's record, not from a population.
- Counts show what happened on the screen, not how you felt. That is why your answers win.
- Only local Claude Code sessions are counted. Web and phone chats are not.
- Most guards are instructions that are re-sent to Claude with every message. Claude usually follows them; nothing enforces it. The session limit and the hooks themselves are real mechanisms.
- The standing instructions add words to every message (the profile tells you how many). That costs usage.
- When the session limit holds a message back, that one message is stored locally in `state/` until you release it.
- The session limit recognises sessions started by Claude itself and scheduled tasks and lets them pass. This was tested on the macOS desktop app only.
- Only English and German phrase lists are included. Add your own in `guards/phrases/`.

## Layout

- `guards/guards.py` — the hooks and small commands. `guards/assess.py` — the assessment. `guards/reeval.py` — the re-evaluation. `guards/install.py` — install and remove. `guards/daily.py` — the daily overview. `guards/selftest.py` — tests.
- `guards/text/` — the exact words sent to Claude. `guards/phrases/` — stop phrases.
- `skills/` — the setup conversation and the start brief.
- Your own files (`config.json`, `PROFILE.md`, `ACTIVE.md`, `state/`, `reports/`) are in `.gitignore` and stay on your machine.

## Contributing

Different people need different things, and some need the opposite of what is here (for example more prompting to explore, not less). Reports of what did **not** fit you are the most useful contribution. Please do not post transcript content.
