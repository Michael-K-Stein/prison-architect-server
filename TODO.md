# TODO

Open work for the bot and the protocol notes. Remove an item when it is done and put the
finding in `journal/journal2.md`.

## Bot

- **Prisoner status and data.** Prisoners have names, ages, needs and reputations. Needs are
  only visible with a **Psychologist on the premises** (hire one: `ctl hire Psychologist`,
  seat him in an Office). The bot should also know when a prisoner has **no free cell**: the
  game shows "There are no free cells for this prisoner" when hovering over the character.
  Find where it lives (live `ObjectData` Person keys such as `ci` / `la`, the save's
  `Bio` / `Needs` children, or a room assignment such as `AssignedRoom`) and add `ctl
  prisoners` plus a `problems` line / hint when prisoners outnumber free cells (deaths and
  escapes cut reputation and income; pause intake meanwhile).
- **Intake categories.** The intake screen controls which prisoner categories are taken (MinSec /
  Normal / MaxSec / transfers; `Save Intake/Categories`: `Pool`, `Ratio`, `NextIntake`,
  `Queue`). Only the mode (`IntakeTypeChange`: Closed / Fill Capacity / Total Prisoners / Num
  Per Day / All Available) is wired.
- **Dismantling objects.** The host creates `DismantleObject` work jobs from its own UI; no
  client request is known (journal2 "Pause point"). Capture a real client dismantling.
- **Unnamed keys.** `Finance.v.<n>` / `tr.*`, `Intake.i`, `NeedsDistribution`, `Visitation.w`,
  `WorkQueue.ri`, `EffectsSystem`, `EventLog` event codes (guesses), `VictorySystem` leftovers.
