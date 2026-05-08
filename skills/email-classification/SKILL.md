---
name: email-classification
description: Classify a single email into one of five buckets (ACTIONABLE, YMYL, INFORMATIONAL, NOISE, SPAM) for Dave OS Phase 4 inbox processing. Use when an inbox-AI routine is processing emails from openbrain.email_bodies.
---

# Email Classification (Dave OS Phase 4)

Classify every email into exactly **one** category. This skill is invoked by the inbox-process routine, which reads from `openbrain.v_email_with_body` and writes results to `efc.inbox_email_log.classification`.

Source design: ported from the dormant Clearpath plugin (PRD §10.2). Lift verbatim — it's already calibrated to Dave's affordable-housing + AI-product life.

## The five categories

### ACTIONABLE
Dave needs to do something. Contains a request, question, or task directed at him.

**Signals:** question marks at Dave; request verbs (send, approve, review, sign, confirm, schedule); Dave in `to_addresses` (not just CC); awaiting Dave's input; deadline implied or stated.

**Examples:**
- "Can you send over the lease agreement for 123 Main St?"
- "We need your signature on the attached contract by Friday."
- "Please approve invoice #4521."

### YMYL — Your Money Your Life
Financial, legal, health/insurance, or deadline with **real consequences.** Must have BOTH keyword AND context (see `ymyl-detection` skill for the full detection logic).

**Examples:**
- "Final notice: $5,000 payment due March 1 to avoid penalty"
- "HUD inspection scheduled for March 15 — site must be compliant"
- "Insurance claim denied — appeal deadline Feb 28"

### INFORMATIONAL
Useful context, no action needed. Status updates, FYI forwards, industry-relevant content.

**Signals:** "FYI", "For your information", "Heads up"; Dave is CC'd (not To); status reports without requests; confirmations of completed actions.

### NOISE
Low-value automated stuff. Marketing, social media, generic newsletters, system pings. Safe to auto-archive.

**Signals:** social media notifications; marketing pitches; automated system messages (backup complete, password reset); generic newsletters not on the whitelist (`efc.newsletter_sources WHERE status='whitelisted'`); "Unsubscribe" link present and not work-related.

### SPAM
Unwanted solicitation, phishing, junk. Safe to trash.

**Signals:** too-good-to-be-true offers; suspicious sender (generic name, mismatched domain); urgency tactics; generic greeting ("Dear customer"); credential-fishing.

## Decision tree (in this order)

1. **SPAM check** (obvious junk / phishing) → if yes, classify SPAM. Done.
2. **YMYL check** (delegate to `ymyl-detection` skill — needs keyword AND context). If YMYL → done.
3. **ACTIONABLE check** (request / question / task for Dave). If yes → done.
4. **INFORMATIONAL check** (Dave is CC'd, status update, useful context). If yes → done.
5. **Default to NOISE.**

## Tie-breakers (when two categories both look right)

| Conflict | Pick |
|---|---|
| ACTIONABLE vs INFORMATIONAL | ACTIONABLE |
| INFORMATIONAL vs NOISE | INFORMATIONAL |
| ACTIONABLE vs YMYL | YMYL (always wins on priority) |
| NOISE vs SPAM | NOISE (safer; recoverable from archive) |

## Edge cases

- **Calendar invites:** directed = ACTIONABLE; optional = INFORMATIONAL; **government/regulatory inspection = YMYL**.
- **CC-only emails:** default INFORMATIONAL. Exception: Dave's name appears in body asking for input → ACTIONABLE. Exception: legal/financial matter → YMYL.
- **Forwarded emails:** "FYI" → INFORMATIONAL. "Can you handle this?" → ACTIONABLE. No context → classify based on body content.
- **Thread continuations:** previous email was ACTIONABLE and Dave hasn't replied → still ACTIONABLE. Dave already replied → downgrade to INFORMATIONAL.
- **Attachments:** "Please review attached" → ACTIONABLE. "Attached for your records" → INFORMATIONAL. Unsolicited attachment from unknown sender → check for SPAM.
- **Automated alerts:** system error (server down, backup failed) → ACTIONABLE. System confirmation (job complete, report generated) → INFORMATIONAL. Marketing automation → NOISE.

## Newsletter handling

If `from_address` matches a row in `efc.newsletter_sources WHERE status='whitelisted'` → reclassify as **NEWSLETTER** (a sixth bucket added by Dave OS, distinct from NOISE; routed to `newsletter-extraction` skill instead of auto-archive).

If sender has a `List-Unsubscribe` header AND tone is marketing-shaped AND not whitelisted → log to `efc.newsletter_sources` with `status='unreviewed'` so Monday's whitelist suggest brief surfaces it.

## Classification prompt template

When the routine calls an LLM for classification, use this exact shape:

```
Classify this email for Dave Layfield (executive at Green Street Housing affordable
housing + co-founder of HousrAI). Choose ONE category:

ACTIONABLE — Dave personally needs to do something.
YMYL — Financial, legal, health, or compliance with real consequences (per ymyl-detection skill).
INFORMATIONAL — Useful context but no action needed.
NEWSLETTER — Sender on the whitelist (already determined upstream — only set if upstream said NEWSLETTER).
NOISE — Marketing, social media, automated notification, generic newsletter not on whitelist.
SPAM — Junk, phishing, suspicious solicitation.

Email:
  Account: {account}
  From: {from_name} <{from_address}>
  To: {to_addresses}
  Cc: {cc_addresses}
  Subject: {subject}
  Date: {date_received}
  Body (plain): {body_plain truncated to 3000 chars; if null, use HTML stripped to text}

Output JSON only:
{
  "classification": "ACTIONABLE|YMYL|INFORMATIONAL|NEWSLETTER|NOISE|SPAM",
  "confidence": 0.0-1.0,
  "reason": "one sentence — what signal drove the call"
}
```

## When to ask Dave instead of guessing

- Sender is high-importance (`efc.people.importance_score > 0.7`) but intent is unclear → flag for review, don't auto-classify.
- Potential YMYL but context is genuinely ambiguous → flag (false-positive YMYL is better than false-negative).
- First email from a new sender with unusual pattern → process normally but flag for sender-review at next `/triage`.

## Learning loop

When Dave's `/triage` reclassifies an item:
- Note the (sender, original_classification, corrected_classification) triple.
- Store in `efc.inbox_sessions.notes` for the session.
- After 3+ similar corrections from the same sender → suggest creating an `efc.inbox_rules` entry: *"Auto-archive emails from [sender] going forward?"*

## What this skill does NOT do

- It does not score (use `email-scoring`).
- It does not extract action items into tasks (use `task-extraction`, ported next).
- It does not write to the database — the calling routine does that based on the JSON output above.
- It does not decide autonomy actions (rules engine + autonomy level handles that).
