# Dimensions: what the assessment counts

The assessment (`guards/assess.py`) reads your local Claude Code transcripts and counts. It keeps numbers and times, never message text. Seven dimensions come out of it. Each is something visible on the screen, not a trait of a person.

A score runs from 0 to 100. It is a linear scale between two anchor values, and the highest part of a dimension counts. **The anchors are provisional:** they were set from the record of a single heavy user. They decide only what gets *proposed*. A guard is proposed at 50 or more.

A "day" runs from 05:00 to 05:00, so work after midnight belongs to the evening before.

| Dimension | Counted as | 0 at | 100 at |
|---|---|---|---|
| Many things at once | % of your messages written when you had written in 3 or more sessions during the hour before | 5% | 45% |
| | sessions you wrote in per day (median) | 2 | 10 |
| Going on after I said stop | your messages in the 3 hours after a stop phrase of yours (median); needs 2 such days | 3 | 30 |
| Long days, late nights, no days off | hours from first to last message (median day) | 8 | 15 |
| | % of your messages between 23:00 and 05:00 | 2% | 15% |
| | nights per week with under 7 h between last and first message | 0 | 1.5 |
| | % of days with any use | 72% | 100% |
| Much more text coming back | reply length divided by the length of your message (median) | 5 | 15 |
| | reply text per active day, thousand characters (median) | 30 | 150 |
| Many questions and choices | multiple-choice dialogs per 100 of your messages | 1 | 8 |
| | % of replies ending with a question | 5% | 20% |
| Losing track | "where are we" questions per 100 messages | 0 | 0.5 |
| | status checks ("and?", "how long?") per 100 messages | 0.5 | 3 |
| | context compactions per week (very long sessions) | 1 | 10 |
| Stopping and correcting Claude | interruptions (Esc) per 100 messages | 0.5 | 4 |

## What is not counted, on purpose

- How you felt. The re-evaluation asks you.
- Whether you need *more* from Claude: more new directions, more questions, more explanation. Counts cannot see a lack. The setup asks, and `format new_directions=inline` or a higher `max_questions` are as valid as their opposites.
- Anything about a diagnosis.

## Known weaknesses

- Phrase matching is literal. If you say "I'm done" and that is not in your phrase files, the stopping dimension stays empty.
- A message at night proves you were awake. A long pause does not prove sleep.
- A crunch for a deadline looks the same as a habit.
- Forked sessions repeat records of their parent; duplicates are removed by record id.
