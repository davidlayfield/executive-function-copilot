---
name: ymyl-detection
description: Detect Your Money Your Life emails — financial, legal, compliance, health, deadline content with real consequences. Two-pass design (cheap keyword scan first, LLM confirmation second). Bias to false-positive over false-negative. Use whenever an email is being classified or scored in Dave OS Phase 4.
---

# YMYL Detection (Dave OS Phase 4)

YMYL = Your Money Your Life. Emails that, if missed, have real-world cost: money lost, contracts breached, deadlines blown, compliance violated, health/safety jeopardized.

**Architectural priority: zero missed YMYL.** False positive (an email flagged as YMYL when it wasn't critical) is recoverable — Dave reclassifies, system learns. False negative (a real YMYL filed as NOISE) costs real money or worse.

## Detection requires BOTH keyword AND context

A keyword alone is not enough. A consequence alone is not enough. Both signals must be present.

- "Payment received, thank you" — keyword present, no consequence → NOT YMYL.
- "We will be unable to continue services" — consequence present, no keyword → check for YMYL anyway, bias yes.
- "Final notice: $4,200 payment due Friday or service termination" — both → YMYL Critical.

## Two-pass detection

**Pass 1 — cheap deterministic scan** (no LLM cost, runs on every email):
- Scan `from_address` for high-trust domains: `*.gov`, `*.irs.gov`, known financial-institution domains, sender's own domain matches a record in `efc.people.relationship_tags @> ARRAY['financial']` or `['government']`.
- Scan `subject` + `body_plain` for keywords from the lists below.
- Scan body for currency patterns: `\$[\d,]+(\.\d{2})?`, especially with words like "due", "owed", "balance".
- Scan for date patterns near deadline language: `\b(by|before|deadline)\s+\w+\s+\d`.

If Pass 1 flags any signal → run Pass 2.

**Pass 2 — LLM confirmation** (Haiku-class is fine; cheap):
- Send full body + headers to LLM.
- Output: `{is_ymyl: bool, severity: critical|high|medium, deadline: ISO date or null, consequence: string, recommended_next_step: string, confidence: 0-1}`
- Only emails where Pass 2 returns `is_ymyl=true AND confidence ≥ 0.6` are flagged YMYL in `efc.inbox_email_log`.

## YMYL keyword lists

### Financial
payment, invoice, penalty, fee, fine, late fee, interest charge, overdue, past due, balance due, final notice, collection, foreclosure, lien, garnishment

### Legal
lawsuit, legal action, court, hearing, summons, subpoena, contract termination, breach of contract, arbitration, settlement, demand letter, cease and desist

### Compliance / Regulatory
citation, violation, compliance, inspection, audit, regulatory, HUD, EPA, OSHA, ADA, Fair Housing, notice of violation, corrective action, REAC, MOR, DHCD

### Deadlines with consequences
deadline, due date, must respond by, final deadline, failure to respond, or else, consequences, action required by

### Insurance / Health / Safety
insurance claim, coverage denied, policy cancellation, liability, accident report, injury, emergency, safety violation, hazard, exposure

### Tax / Government
tax, IRS, FTB (state tax), property tax, assessment, levy, tax lien, government notice, official notice, MD comptroller

## Severity tiers

| Severity | Meaning | Score floor | Examples |
|---|---|---|---|
| **Critical** | Action needed within 7 days; consequence is significant ($1k+, lawsuit, eviction, compliance failure, safety) | 0.95 | "Final notice — payment overdue, account suspension Friday" |
| **High** | Action needed within 30 days; consequence is real but not immediate | 0.85 | "Insurance renewal — submit forms by month end" |
| **Medium** | Long deadline (30+ days) or smaller consequence | 0.70 | "Annual compliance filing due in 60 days" |

These floors are applied **after** the 6-dimension scoring (see `email-scoring` skill). They guarantee YMYL emails surface above ordinary tasks even if their other dimensions score low.

## Override rules — YMYL beats everything

YMYL emails override the rules engine. Specifically:
- An `auto_archive` rule that would match a YMYL email is **ignored**. The email surfaces.
- An `auto_unsubscribe` rule never fires on YMYL.
- The autonomy-level gating allows zero autonomous action on YMYL — every YMYL alert requires Dave's explicit per-item approval, even at Delegator level.
- YMYL emails never get auto-classified to NOISE/SPAM regardless of sender pattern.

## Alert format (the message Dave sees)

When the inbox-process routine surfaces YMYL alerts in `/inbox-start` or the morning brief, format each as:

```
🚨 YMYL: <one-line subject>
  WHAT:        <one sentence — what's happening>
  DEADLINE:    <date and "in N days">
  CONSEQUENCE: <what happens if missed>
  NEXT STEP:   <one verb-first action Dave should take>
  Source:      <sender — date received — account>
```

Always shown FIRST in any inbox surface, before regular tasks. Decay rate is half of normal (decay 2.5%/day instead of 5%) — YMYL stays prominent.

## Deadline-language escalation

As deadline approaches, the alert escalates language:
- > 7 days: normal alert format
- 3-7 days: prefix subject with "⏰ "
- 1-2 days: prefix with "⏰⏰ DEADLINE TOMORROW: "
- 0 days: prefix with "⏰⏰⏰ DEADLINE TODAY: "
- past: prefix with "❌ DEADLINE PASSED: " — but DO NOT auto-archive; leave for Dave to decide

## Audit trail

Every YMYL detection (including those filtered out at Pass 2) is logged to `efc.inbox_email_log.ymyl_alert` (jsonb) with:
```json
{
  "severity": "critical|high|medium",
  "what": "...",
  "deadline": "2026-05-15",
  "consequence": "...",
  "next_step": "...",
  "confidence": 0.92,
  "detected_at": "2026-05-08T07:04:00Z",
  "model": "claude-haiku-4-5"
}
```

This makes precision-monitoring possible: query `efc.v_extractor_precision_weekly` later to see how often Dave's `/triage` keeps vs drops YMYL flags by model.

## False-positive reduction (NOT false-negative reduction)

Some patterns are usually NOT YMYL despite triggering keywords:
- Newsletter articles ABOUT financial topics (e.g., a Bay Area Letters issue mentioning "tax tips") — sender is a known newsletter source.
- Marketing emails from financial vendors ("New rates available!") — sender domain matches `efc.unsubscribe_queue.sender_pattern` or has a List-Unsubscribe header.
- Receipt confirmations ("Your payment was received") — past-tense + no future action.
- Calendar invites for routine internal meetings — even if subject mentions "compliance", attendee list is internal.

Pass 2 should explicitly check for these patterns and lower confidence.

**Still — when truly uncertain, classify as YMYL.** The bar for filtering OUT a YMYL candidate must be high.
