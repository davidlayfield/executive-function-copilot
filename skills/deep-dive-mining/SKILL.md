---
name: deep-dive-mining
description: Deep-dive Opus-powered analysis of historical email clusters to extract sales leads (warm contacts worth re-engaging) and operational knowledge atoms (decisions, vendor relationships, processes, war stories). Use when the dave-os-mine-deep routine fires or when /mine commands are invoked.
---

# Deep-Dive Mining (Dave OS Phase 4.5)

The M2 inbox-process routine is fast + cheap (Sonnet, classification + scoring). The deep-dive is **slow + Opus** — it analyzes clusters of emails as a unit, extracting structured insight that's hard to get email-by-email.

Two outputs:
- `efc.sales_leads` — warm-contact intelligence for HousrAI / Atlas / consulting business development
- `efc.knowledge_atoms` — decisions, vendor relationships, processes, playbooks, war stories from operational history

This skill defines the analysis. The `dave-os-mine-deep` routine and `/mine` commands orchestrate.

## Cluster identification (upstream of analysis)

The routine identifies clusters worth analyzing using deterministic signals (no LLM):

### Cluster types

| Type | Signal | Example |
|---|---|---|
| `sender_domain` | All emails from same external domain (≥3 emails, ≥30 days span) | All exchanges with `*@gsccapital.com` over 18 months |
| `thread` | Long single thread (≥5 messages, ≥3 distinct participants) | Mallard Ridge negotiations |
| `project` | Group of threads sharing property address or topic keywords | All emails mentioning "Fruitland" + financial keywords |
| `property_address` | Multiple threads referencing same address | All "123 Main St" mentions across senders |
| `recurring_subject` | Recurring subject prefix (e.g. "Monthly Update — X") | Quarterly reports series |

Each cluster gets one row in `efc.deep_dive_clusters` with deterministic `cluster_key` (so re-runs don't duplicate). The routine prioritizes pending clusters by `email_count` (more = more material to analyze).

## Analysis prompt (Opus)

For each pending cluster, gather all source emails (full body from `openbrain.email_bodies` JOIN `openbrain.v_email_with_body`). Send to Opus with this system prompt:

```
You are analyzing a cluster of related emails from Dave Layfield's history. Dave is:
- Co-founder of HousrAI (proptech AI for affordable housing — products: Vitals, Atlas)
- Executive at Green Street Housing (affordable housing dev/ops)
- Personally interested in: AI agents, LIHTC compliance, MD housing policy

This cluster is type: {cluster_type}
Signal: {cluster signals — what made this group}
Emails: {N emails over {timespan}}

Your job: extract two things.

A) SALES LEAD ANALYSIS (only if external — non-housrai/non-greenstreethousing/non-personal contacts):
   - Is this a warm contact? cold? dormant?
   - What was discussed? What was the opportunity (if any)?
   - Why did communication stall (if it did)?
   - Recommended re-engagement action (specific, verb-first), or "no action — confirmed dead"
   - Confidence 0-1

B) KNOWLEDGE ATOMS (always):
   - What decisions were made and by whom?
   - What vendor relationships are documented?
   - What processes / playbooks are revealed?
   - What outcomes (good or bad) are recorded?
   - What war stories ("we tried X and Y happened") emerge?

Output JSON only:
{
  "sales_lead": null | {
    "contact_name": "...",
    "contact_email": "primary email of contact",
    "organization": "...",
    "lead_status": "cold|warm|hot|engaged|closed_won|closed_lost|dormant|dead",
    "product_or_service": "what we're/were trying to sell or partner on",
    "opportunity_summary": "1-3 sentence what this is about",
    "last_meaningful_summary": "one sentence what we last substantively talked about",
    "why_stalled": "one sentence (or 'no stall — actively engaged')",
    "recommended_action": "verb-first action or 'no action — dead lead'",
    "recommended_reasoning": "why this action makes sense",
    "confidence": 0.0-1.0
  },
  "knowledge_atoms": [
    {
      "atom_type": "decision|vendor_relationship|process|outcome|playbook|policy|war_story|contact_intel",
      "topic": "short topic name",
      "summary": "1-3 sentence atom of knowledge",
      "decision_or_outcome": "if applicable",
      "what_worked": "if applicable",
      "what_did_not_work": "if applicable",
      "participant_emails": ["email1","email2",...],
      "date_period_start": "YYYY-MM-DD",
      "date_period_end": "YYYY-MM-DD",
      "confidence": 0.0-1.0
    }
  ]
}
```

The routine then writes outputs to `efc.sales_leads` and `efc.knowledge_atoms`, links them to the cluster row.

## Quality bar

This is not the M2 fast-path. Bias toward **fewer, higher-confidence outputs** rather than catching everything. Better to miss a lead than create a bad one. Better to miss a knowledge atom than create a wrong one.

If a cluster doesn't surface anything useful (sales_lead=null AND knowledge_atoms=[]), mark cluster `status='analyzed'` with notes='no signal'. Don't create empty rows.

## Storage flow

```
deep_dive_clusters row created (status='pending')
  ↓
deep-dive-mining routine picks up pending clusters
  ↓
gathers source emails
  ↓
Opus analysis (this skill)
  ↓
sales_lead row(s) created (status='identified', reviewed_by_dave=false)
knowledge_atom row(s) created (archived=false)
  ↓
deep_dive_clusters row updated to status='analyzed' with produced ids
```

## Surfacing to Dave

These outputs do NOT auto-surface in the morning brief (would be too much). Instead:

- `/mine-leads` command — show unreviewed leads ranked by confidence + opportunity score
- `/mine-knowledge <topic-or-search>` — search and explore knowledge atoms
- Weekly `dave-os-weekly-mining-summary` routine (Sunday evening) — top 5 leads, top 5 knowledge atoms found this week, prompt review

When Dave reviews a lead via `/mine-leads`, he can act, defer, dismiss, or convert it to an `efc.tasks` row to actually re-engage.

## Cost discipline

Even on Max 20x plan, Opus consumption isn't unlimited. Cap:
- Process at most 20 clusters per routine run
- Each cluster's analysis caps at ~10K input tokens (truncate or sample if larger)
- If quota throttling detected → pause, retry next run

## What this skill does NOT do

- Doesn't classify or score individual emails (M2's job)
- Doesn't manage the unsubscribe queue or rules (M5/M4)
- Doesn't auto-act on leads (always Dave-reviewed-and-decided)
- Doesn't write to people graph directly — relies on M2's per-email people upserts
