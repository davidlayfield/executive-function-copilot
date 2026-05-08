---
name: email-task-extraction
description: Extract actionable tasks from ACTIONABLE/YMYL emails into efc.tasks rows. Includes verb-first title construction, deadline parsing, deduplication via 3-check cascade, project linking, and the "split or merge multiple actions" rule. Use whenever the inbox-process routine has classified an email as ACTIONABLE or YMYL.
---

# Email Task Extraction (Dave OS Phase 4)

Turn one email into one or more `efc.tasks` rows. Source design: Clearpath PRD §10.4 — ported intact.

## When to extract

| Classification | Extract task? |
|---|---|
| ACTIONABLE | Yes |
| YMYL | Yes — and copy `ymyl_classification` + `ymyl_alert` onto the task |
| INFORMATIONAL | No (just log to `efc.inbox_email_log`) |
| NEWSLETTER | No (route to `newsletter-extraction` skill) |
| NOISE | No (log + auto-archive per autonomy level) |
| SPAM | No (log + auto-trash) |

## Task components

### Title — verb-first, ≤ 60 chars

**Good:**
- "Review contract for 123 Main St"
- "Approve invoice #4521 ($8,500)"
- "Sign lease amendment for Tenant A"
- "Schedule HUD pre-walkthrough"
- "Respond to Fair Housing complaint"

**Bad:**
- "Contract" (no verb)
- "John wants to know about the contract" (not imperative; about the sender, not the action)
- "There's a contract that needs reviewing for the property at 123 Main St and it has some issues" (too long)

**Construction recipe:**
1. Start with action verb (review, approve, sign, schedule, respond, send, confirm, verify, pay, file)
2. Include key identifier (property address, invoice #, person name, dollar amount)
3. Keep under 60 chars
4. Be specific, not generic — "Approve invoice" is bad; "Approve invoice #4521 ($8,500) from Acme" is right

### Description — full context

Stored in `efc.tasks.notes`. Include:
- Sender's specific request (quote if helpful, ≤15 words)
- Relevant details: amounts, dates, parties, attachments
- Background from previous messages in thread (if multi-message thread)
- Pointer to source: account, sender_email, message_id

Example:
```
John Smith (Green Street Capital) requesting review of final refinancing contract
for 123 Main St. Attached: Contract_GreenSt_Final.pdf. Needs signature by Mar 1
to close Mar 8. Terms: $500K loan, 4.5%, 20yr. Legal already approved.
Source: dave@greenstreethousing.com — john@gsc.com — 2026-05-08T10:23:00Z
```

### Deadline — parse to ISO 8601

Extract a deadline from the email body. Heuristics:

| Email says | Deadline |
|---|---|
| "by Friday" | Next Friday in America/New_York |
| "EOD" | Today 17:00 ET |
| "EOW" | Friday 17:00 ET |
| "ASAP" / "urgent" / "immediately" | Now + 48 hours |
| "by March 15" | 2026-03-15 |
| "March 15, 2026" | 2026-03-15 |
| "next week" | 7 days from now |
| "this week" | This Friday |
| (no deadline mentioned) | NULL — let scoring handle it |

Store in `efc.tasks.deadline` (date) AND optionally `due_date` if you want time-of-day precision (currently the schema uses `date`, not timestamp; round to date).

### Other fields populated at extraction

| Column | Source |
|---|---|
| `source_email_id` | `message_id` from email_bodies |
| `source_account` | `account` from email_bodies |
| `sender_name` | `from_name` from email_bodies |
| `sender_email` | `from_address` from email_bodies |
| `thread_id` | `thread_id` from email_bodies |
| `external_source` | `'gmail'` |
| `external_id` | `<account>:<message_id>` |
| `priority` | `'must'` if YMYL critical, `'should'` otherwise (overridden by scoring) |
| `priority_score`, `score_dimensions`, `score_reason` | from `email-scoring` skill |
| `ymyl_classification`, `ymyl_alert` | from `ymyl-detection` skill |
| `status` | `'todo'` (Clearpath called it `'waiting'`; Dave OS uses `'todo'`) |
| `openbrain_memory_id` | join via `raw_entries.source_metadata.thread_id == email_bodies.thread_id` to find the related memory |

## Deduplication — 3-check cascade

Run in order; stop at first match.

1. **Exact source_email_id match** → already a task; skip extraction entirely. Log to `efc.inbox_email_log` with `task_id` pointing to the existing task.

2. **Same thread_id match** → existing task for an earlier message in this thread. UPDATE that task:
   - Append `[UPDATE 2026-05-08]` line to `notes` summarizing what's new
   - Refresh `deadline` if the new email has a different/closer deadline
   - Recompute `priority_score` (same formula, new context)
   - Do NOT create a new task

3. **Same `sender_email` + ≥80% fuzzy title match** → likely duplicate phrased differently. UPDATE the existing task as in step 2.

If none match → INSERT a new row in `efc.tasks`.

## Multiple actions in one email

When the body mentions several distinct actions:

**Single comprehensive task** if related (same deadline, same stakeholder, same project):
> "John needs you to review the contract, sign it, and send the wire by Friday."
> → ONE task: "Review + sign + wire transfer for 123 Main St contract" (deadline Friday).

**Split into multiple tasks** if independent (different deadlines, different stakeholders, one is YMYL and one isn't):
> "Quick housekeeping: please approve invoice #4521 today, and also start thinking about the Q3 budget for next month's review."
> → TWO tasks:
>   1. "Approve invoice #4521" (deadline today, ACTIONABLE)
>   2. "Draft Q3 budget for next month's review" (deadline +30d, ACTIONABLE)

## Project linking

After creating/updating a task, look for an existing project to attach it to:

1. Query active projects (`efc.projects WHERE status='active'`).
2. Score each candidate against the new task using the 5 project-clustering signals (see `project-detection` skill, ported later from Clearpath PRD §10.5):
   - Shared `thread_id` between this email and project's tracked threads
   - Overlapping participants (≥2 shared addresses)
   - Property address match (regex on body + project descriptions)
   - Project keywords + same vendor domain
   - Recurring subject prefix
3. If any signal scores → attach: set `efc.tasks.project_id` AND append the new email's thread_id to the project's tracked threads (jsonb).
4. If multiple signals across multiple projects → attach to highest-scoring; flag for Dave at next `/triage` if ambiguous.

If no project matches but the task signals start of a real project (multi-step, named entity, ongoing communication) → flag for project creation at next `/triage`.

## Auto-archive after extraction (autonomy-gated)

Once the task is extracted, the source email can be archived in Gmail — its information is preserved in `efc.tasks` + `openbrain.email_bodies`.

Gating:
- **Observer level (sessions 1-5):** never auto-archive; ask Dave per email
- **Drafter level (sessions 6-20):** auto-archive ACTIONABLE/INFORMATIONAL after task extraction; ask Dave for YMYL
- **Delegator level (20+):** auto-archive everything except YMYL; YMYL stays in inbox

(Autonomy level lookup: `efc.operating_manual.content` — Dave OS will surface a structured field once the bootstrap is done; for now, pin to Observer.)

## Output shape (what the routine writes)

After this skill processes one email, the routine should call something like:

```sql
INSERT INTO efc.tasks (
  title, notes, status, priority, priority_score, score_dimensions, score_reason,
  ymyl_classification, ymyl_alert, deadline,
  source_email_id, source_account, sender_name, sender_email, thread_id,
  external_source, external_id, openbrain_memory_id
) VALUES (...)
RETURNING id;

INSERT INTO efc.inbox_email_log (
  account, message_id, thread_id, sender_name, sender_email, subject,
  received_at, classification, classification_confidence,
  ymyl_alert, task_id, openbrain_memory_id, classified_by_model, extracted_at, extracted_by_model
) VALUES (...);
```

Both writes happen in one transaction-shaped routine call (PostgREST doesn't support multi-statement transactions; the routine should handle the failure recovery — if task INSERT succeeds and log INSERT fails, log the inconsistency).

## What this skill does NOT do

- It does not classify (use `email-classification`).
- It does not detect YMYL (use `ymyl-detection`).
- It does not score (use `email-scoring`).
- It does not draft replies (Phase 4 M3+).
- It does not auto-send (Phase 4 M6+).
- It does not write to Gmail (archive happens via separate Gmail API call after extraction succeeds).
