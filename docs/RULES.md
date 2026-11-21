# Re-evaluation rules

`guards/reeval.py` compares the four weeks before the install with the time since. The rules below are fixed in the code (function `flags`) so that a result cannot be bent afterwards. Before 7 finished days it only says "too early". Claude proposes changes after a run; nothing changes without your yes.

| Rule | Fires when | Then |
|---|---|---|
| R1 | hooks missed more than 10% of sessions | find which way of opening a session skips them, before judging anything else |
| R2 | a guard is switched off | say what bothered you; change or delete that guard |
| R3 | the hook script crashed | fix it |
| R4 | "Guards active" opened fewer than 80% of new sessions | repair first; otherwise you forget the guards exist |
| R5 | fewer than 70% of replies keep the reply shape | shorten it or move it to an output style |
| R6 | after a stop phrase you still write about as much as before | landing mode needs a different design, not more reminders |
| R7 | you end landing mode after more than half of the landings | phrases too sensitive, or landing costs more than it gives |
| R8 | late nights but no stop phrase seen | you say it differently now; update your phrase file |
| R9 | the ledger has fewer than half as many entries as commits | drop the ledger or make it automatic |
| R10 | the day digit is answered in under a third of landings | drop it or ask differently |
| R11 | no day without AI in 14 days or more | no guard covers this; it needs a decision of yours |
| R12 | use fell below 30% of before | check whether the guards make Claude unpleasant to use |
| R13 | your own rating has a 1 or 2 | that outweighs every count |
| R14 | you lift the session hold in 80% or more of cases | it is only a speed bump: keep it as a pause, make it stricter, or remove it |
| R15 | sessions per day did not go down although the hold fired | it does not change the shape of your day |
