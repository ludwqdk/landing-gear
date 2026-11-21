---
name: guards-setup
description: Set up personal guards for working with Claude Code from the user's own record. Use when the user says "guards setup", "set up my guards", "assess my sessions", or has just cloned this repository and asks how to start. Runs a free count of their local sessions, shows what it found, asks about the reply shape with examples, and installs only what the user agrees to.
---
You are setting up guards for ONE person. Nobody gets anybody else's settings. Work in the `guards/` folder of this repository. Every step below is small; do them in order and stop where it says STOP.

## Rules that hold for the whole setup

1. **Symptoms, not diagnoses.** Never ask about or guess a diagnosis. Talk about what shows on the screen and what the person tells you.
2. **Same information.** A reply shape may change order and form. It must never reduce what the person is told. If they ask for less content, say that this is a content choice, separate from shape, and note it as their decision.
3. **Usage budget.** The count in step 1 is a script and costs nothing. Do not read transcripts yourself. Do not start subagents. Reading sessions with a model is step 5, optional, and needs an explicit yes with the estimate in front of the person. Never exceed `budget.max_read_tokens`. Never raise it yourself; if more would help, ask explicitly: "This would use about N tokens, more than your cap of M. May I use more?" and accept a no without comment.
4. **Transparency.** Everything that will change Claude's behaviour is shown before it is switched on, and the off switch is said out loud: `guards off`.
5. **Privacy.** Nothing leaves the machine. Do not paste transcript content into searches or other services.
6. One question per message. Short messages.

## Step 1: count (free)

Run `python3 assess.py`. Show the printed profile completely. Say in one line that this cost no usage and changed nothing. Point to `PROFILE.md` and `profile_radar.svg`.

## Step 2: does it match?

Ask one question: "Does this match how working with Claude feels to you? What is missing or wrong?" Their answer wins over the counts. Change the proposal accordingly with `python3 assess.py set ...` (for example a guard they do not want: `set P7_focus=off`; a need the counts cannot see, such as wanting more new ideas: `format new_directions=inline`).

## Step 3: reply shape, by example

Do not ask abstract questions. Take ONE short answer (about 120 words, any neutral topic) and show it twice, same content, different shape. Ask which is easier to take in. One pair per message:

- A: plain paragraphs. B: result first in bold, then short blocks.
- A: flowing sentences. B: one piece of information per sentence, numbered.
- A: ideas and offers woven into the text. B: the same ideas collected in one "Parking" block at the end. C: no extra ideas unless asked (say plainly that C removes content).
- A: Claude asks whenever something is open. B: Claude decides small things and lists them; at most one question.
- Where should "what is still open" stand: top, bottom, nowhere.

Check after each pair that both versions really carried the same information. Store the answers: `python3 assess.py format bold_first=yes numbered_sentences=no new_directions=block max_questions=1 open_line=top`. Also ask which language they want replies in if it is not obvious (`format language=...`).

## Step 4: their own stop words

Ask: "When you have had enough, what do you actually type?" Write their words, one per line, into `phrases/mine.txt`. Set `languages` to the phrase files that fit them (`python3 assess.py set languages=en,de`).

## Step 5 (optional, costs usage): a closer look

Only if the person wants more than counts. Run `python3 assess.py sample`. Show the list and the token estimate. Ask explicitly whether to read them, naming the estimate. On yes: read with the cheapest model available, one session at a time, stop at the cap, and report patterns as data vs. inference, with at most one short quote each. On no: go on.

## Step 6: show, then install

Show the final proposal: each guard on/off with its one-line description, each value with its reason, and the number of words added to every message. STOP and ask for a yes.
On yes: `python3 assess.py accept`, then `python3 install.py`. Tell them: it applies to new sessions; `guards off` switches everything off; `ACTIVE.md` lists what is on; `PROFILE.md` says why.

## Step 7: it will not be right the first time

Say so. The re-evaluation (`reeval`, as a word in any session, or `python3 reeval.py`) compares the weeks before and after with the same counts and asks them three questions: could I work well, was AI still useful, did I feel good using it. A reminder line appears after `reeval_every_days` days. Guards that do not help get changed or deleted; that counts as a good result.
