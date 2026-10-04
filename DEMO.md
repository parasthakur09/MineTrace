# Demo script (3 minutes)

Before you go on stage:
- Run `python ingest_comtrade.py` and `python ingest_opensanctions.py` days before, not on the day.
- Run `npm run textures` so the globe works without internet.
- Start Ollama and open one route once, so its explanation is already cached.
- Pick your demo route in advance: a red route with two or more flags. Note its name.
- Record a backup video of this whole script.

## 1. The problem (20 seconds)

"A 30-person battery maker in Europe now has to show where its cobalt comes from. The tools that
answer that cost tens of thousands a year. Small manufacturers, journalists and researchers have
nothing."

## 2. The globe (25 seconds)

Point at the globe. "Every arc is an official trade flow from UN Comtrade. Red and amber routes are
ones our rules flagged. Here's the network: the biggest supplier, and how concentrated supply is."
Point at the HHI line in the bottom row.

## 3. Open the flagged route (60 seconds)

Click it in "Routes to look at first". The globe turns to it.
- "Each flag shows its evidence. Here the exporter and the importer report different values for the
  same trade." Point at both numbers. "A normal gap is 5 to 10 percent. This one is far bigger."
- Scroll to "Checks run". "Where we don't have enough data, we say so instead of guessing."

## 4. The explanation (25 seconds)

"A local LLM writes this summary, but it can only use numbers from the evidence. If it invents a
number or cites a rule that didn't fire, we reject it and fall back to a template. The label tells
you which one you're reading."

## 5. The report (15 seconds)

Click "Evidence report". "One click gives a printable evidence file a compliance team can attach to
its due-diligence records."

## 6. Offline (15 seconds)

Turn Wi-Fi off. Click another route. "No login, no paid API, no data leaving this laptop."

## 7. Close (20 seconds)

"We work at country level because that's what public data supports, and we say so. Next: more
minerals, shipment-level data where it exists, and reports aligned with the EU Battery Regulation and
OECD guidance."

## Questions judges are likely to ask

- **Why not just use the Comtrade website?** Comtrade gives raw tables. MineTrace compares both sides
  of every flow, measures concentration on a network graph, checks prices, cross-references sanctions
  and explains the result, in one view.
- **Isn't country level too coarse?** Yes, for proving anything. It is a first-pass screen that tells
  you where to look harder.
- **How do you avoid false positives?** Every threshold is visible and adjustable in one file, every
  flag shows its numbers, and tiny flows are excluded from comparisons.
- **How do sanctions become a flag on a country route?** R5 counts sanctioned companies whose names
  match mining or metals terms, linked to either country. It is labelled as exposure, not as proof
  that this trade involves them.
- **Can the LLM hallucinate?** Its output is checked against the evidence before it is shown, and
  there's a deterministic fallback. Show the "rejected" path if asked.
