---
name: email-scoring
description: Score a single email on a 6-dimension priority formula (urgency, importance, sender authority, deadline proximity, financial impact, context richness) and apply post-composite special rules (YMYL floors, sender ceilings, decay, deadline boost). Use whenever Dave OS Phase 4 needs to rank tasks derived from emails.
---

# Email Scoring (Dave OS Phase 4)

Compute a `priority_score` between 0.000 and 1.000 for each email-derived task. The score drives ranking in `/inbox-start`, the morning brief, and any "what should I do next" question.

Source design: Clearpath PRD §8 — ported intact. The formula is calibrated to Dave's life and tested against the four PRD §14 success scenarios. **Don't redesign it; tune it.**

## The composite formula

```
priority_score = (urgency           * 0.25)
               + (importance        * 0.25)
               + (sender_authority  * 0.20)
               + (deadline_proximity* 0.15)
               + (financial_impact  * 0.10)
               + (context_richness  * 0.05)
```

All inputs ∈ [0.0, 1.0]. Result ∈ [0.0, 1.0]. Store the dimensions individually in `efc.tasks.score_dimensions` (jsonb) so Dave can ask *"why did this score so high?"* and we can answer.

## Dimension specs

Bands (not gradients) — explainable, debuggable.

### Urgency (0.25 weight)
- Explicit deadline ≤ 24h: **1.0**
- Deadline 24-48h: **0.9**
- Deadline 2-7 days: **0.7**
- Urgency keywords without specific deadline ("urgent", "ASAP", "today"): **0.8**
- Action verbs without urgency ("please review", "could you"): **0.7**
- No urgency signal: **0.5**
- FYI / "no rush" language: **0.3**

### Importance (0.25 weight)
- Tenant safety / habitability: **1.0**
- Compliance / regulatory: **0.95**
- Revenue (rent, payment, lease execution): **0.9**
- Contract / legal: **0.9**
- Routine operations (maintenance, scheduling): **0.6**
- Internal coordination (team updates): **0.5**
- Personal / family / non-work: **0.4** (no penalty — it's still important; the formula just biases toward work for the "what should I do at the desk now" question)

### Sender authority (0.20 weight)
- Look up `sender_email` in `efc.people`. If found, use `efc.people.importance_score` directly.
- If not found, fall back to domain heuristics:
  - `*.gov`: **0.9**
  - `*.bank`, known financial institution: **0.85**
  - `*.com` business email matching format `<name>@<company>`: **0.7**
  - Free email (gmail, yahoo, hotmail, icloud, outlook.com): **0.4**
  - Suspicious / unfamiliar / mismatched: **0.3**

### Deadline proximity (0.15 weight)
- If task has a deadline `D` days away (negative if past):
  - For `D ≤ 2`: `0.5 + (2 - D)/2 * 0.5` (linear ramp from 0.5 at D=2 to 1.0 at D=0)
  - For `D > 2`: **0.5**
- No deadline: **0.5**

### Financial impact (0.10 weight)
- Banded by dollar amount mentioned in body:
  - > $10,000: **1.0**
  - $5,000-10,000: **0.9**
  - $1,000-5,000: **0.7**
  - $100-1,000: **0.5**
  - < $100 or no amount: **0.3**
- **+0.1** if "penalty", "late fee", "interest" appears with the amount (capped at 1.0)

### Context richness (0.05 weight)
- Body length:
  - > 500 chars: **0.7**
  - 100-500: **0.5**
  - < 100: **0.3**
- **+0.2** if attachments present
- **+0.1** if it's a thread continuation (3+ messages)
- **+0.2** if specific details present (dates, names, dollar amounts, addresses, contract numbers)
- **−0.2** if vague language only ("we should chat", "let's catch up")
- Floor 0.1, cap 1.0.

## Special rules (applied AFTER composite, in this order)

1. **YMYL floor.** If `ymyl_classification` is set, apply the severity floor (`critical: 0.95, high: 0.85, medium: 0.70`). Score = `max(score, floor)`.
2. **Unknown sender + free email floor.** If sender not in `efc.people` AND from a free-email provider AND first contact ever from this address: floor at **0.45** (so it surfaces enough to triage).
3. **CC-only ceiling.** If Dave's email is in `cc_addresses` only (not `to_addresses`): cap at **0.50**. Exception: Dave's name appears in body explicitly addressing him.
4. **Newsletter ceiling.** If `classification = NEWSLETTER`: cap at **0.20**. (Newsletters are content, not action; surface via digest, not as tasks.)
5. **Rule modifiers.** Apply boost/suppress from active `efc.inbox_rules` matching this email (capped at ±0.30 cumulative).
6. **Score decay** (display-time only, NOT stored): tasks without deadlines lose **5%/day** since `created_at`. YMYL tasks decay at half rate (2.5%/day).
7. **Deadline boost** (display-time only, NOT stored): in the final 48 hours before deadline, linear ramp toward 1.0. `boost = (1.0 - score) * (1.0 - hours_to_deadline/48)`.

## Cold-start heuristics (session 1, before contacts table populated)

When `efc.people` has fewer than ~50 rows (system is fresh), bias the dimensions:
- Email To-only Dave: urgency `+0.15`
- Email CC-only Dave: urgency `−0.10`
- Direct question for Dave detected: importance `+0.12`
- Specific date in body: deadline_proximity `+0.18` if date is within 7 days
- Dollar amount > $1,000 with "due/owed/pay": financial_impact floored at `0.7`
- These bias terms taper to zero as `efc.people.interaction_count` accumulates.

## Score reason string (Dave-facing)

Always populate `efc.tasks.score_reason` with a one-sentence English explanation. Example:

> "Score 0.91: YMYL critical floor (HUD inspection deadline), high sender authority (.gov), deadline 5 days out."

These explanations are gold for the precision-monitoring loop — when Dave drops a high-scoring item, we can see which dimension was misled.

## Storage

Final result written to `efc.tasks` columns (added in Phase 4 M1):
- `priority_score numeric(4,3)` — the composite
- `score_dimensions jsonb` — `{"urgency":0.9,"importance":0.95,"sender_authority":0.7,...}`
- `score_reason text` — one-sentence explanation

The display-time transforms (decay, deadline boost) are computed on read in the `/briefing`, `/inbox-tasks`, and `/inbox-start` queries — not stored. This keeps the stored score stable and the display fresh.

## Tuning (later, not now)

- The 6 dimension weights (0.25/0.25/0.20/0.15/0.10/0.05) sum to 1.0. They're calibrated for Dave's mix. If after a month of use the wrong things keep ranking high, adjust weights — don't change the formula shape.
- Severity floors (0.95/0.85/0.70) are intentionally aggressive. If YMYL floor is keeping non-urgent stuff above genuinely urgent normal tasks, lower the medium floor to 0.65.
- Decay rate (5%/day) and deadline boost (48h ramp) are tuneable in the routine code, not in this skill.
