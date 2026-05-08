---
description: Show sales leads surfaced by deep-dive mining. Filter by status / unreviewed / org. Act on a lead (convert to task), dismiss, or change status.
argument-hint: [list | unreviewed | hot | warm | dormant | from <org> | act <id> | dismiss <id> | status <id> <new-status>]
---

You are managing the sales leads that the deep-dive mining routine has surfaced. Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse subcommand

| Subcommand | Behavior |
|---|---|
| (empty) or `list` | Show all unreviewed leads, ranked by confidence |
| `unreviewed` | Same as default |
| `hot` / `warm` / `cold` / `dormant` | Filter by lead_status |
| `from <org>` | Filter by organization ILIKE '%<org>%' |
| `act <id>` | Convert recommended_action to a task in efc.tasks; mark reviewed |
| `dismiss <id>` | Mark reviewed_by_dave=true with dave_decision='dismissed' |
| `status <id> <new>` | Update lead_status |
| `show <id>` | Full detail view |

## list / unreviewed (default)

```sql
SELECT id, contact_name, contact_email, organization, lead_status,
       opportunity_summary, last_meaningful_summary, recommended_action,
       recommended_reasoning, source_count, confidence,
       extracted_at, last_meaningful_at,
       reviewed_by_dave
FROM efc.sales_leads
WHERE reviewed_by_dave = false
ORDER BY confidence DESC NULLS LAST, source_count DESC NULLS LAST
LIMIT 25;
```

Output:

```
💼 SALES LEADS — <count> unreviewed (showing top 25)

Hot (<count>)
  ★ <contact_name> — <organization>
        Status: hot   Confidence: <X>   Sources: <N> emails
        💬 <opportunity_summary>
        🕓 Last we talked: <last_meaningful_summary>
        🎯 Action: <recommended_action>
              (<recommended_reasoning>)
        id: <short>
  • ...

Warm (<count>)
  • ...

Dormant (<count>)
  • ...

— /mine-leads act <id>  to create a task
   /mine-leads dismiss <id>  to mark reviewed without action
   /mine-leads show <id>  for full detail incl. source emails
```

## act <id>

Pull lead. Create a task from the recommended action:

```sql
INSERT INTO efc.tasks (title, notes, status, priority, sender_email, source_account)
VALUES (
  <recommended_action>,
  format('Lead surface from deep-dive mining.\n\nOpportunity: %s\nLast: %s\nWhy stalled: %s\n\nReasoning: %s\n\nSource lead id: %s',
         <opportunity_summary>, <last_meaningful_summary>, <why_stalled>,
         <recommended_reasoning>, <lead_id>),
  'todo', 'should',
  <contact_email>, NULL  -- not from a specific email account
)
RETURNING id;

UPDATE efc.sales_leads
SET reviewed_by_dave=true, reviewed_at=now(), dave_decision='actioned'
WHERE id='<lead_id>';
```

Confirm:
```
✓ Task created: <task title>  (id: <task_short>)
   Lead marked actioned. /inbox-show <task_id> to inspect.
```

## dismiss <id>

```sql
UPDATE efc.sales_leads
SET reviewed_by_dave=true, reviewed_at=now(), dave_decision='dismissed'
WHERE id='<id>';
```

```
✓ Lead dismissed: <contact_name>. Will not resurface unless re-mined.
```

## status <id> <new-status>

Validate new-status against the CHECK constraint values (identified, cold, warm, hot, engaged, closed_won, closed_lost, dormant, dead).

```sql
UPDATE efc.sales_leads SET lead_status='<new>', updated_at=now()
WHERE id='<id>' RETURNING contact_name, lead_status;
```

## show <id>

Pull full lead row + related source emails:

```sql
SELECT * FROM efc.sales_leads WHERE id='<full_id>';

SELECT subject, from_address, date_received,
       substring(body_plain, 1, 500) AS body_preview
FROM openbrain.email_bodies
WHERE thread_id = ANY('<source_thread_ids>'::text[])
ORDER BY date_received
LIMIT 10;
```

Output:

```
💼 LEAD — <contact_name> (<organization>)
   id: <full uuid>     extracted: <date> by <model>     reviewed: <yes/no, decision>

📊 Status: <status>    Confidence: <X>    Source: <N> emails

💬 Opportunity
   <full opportunity_summary>

🕓 Last meaningful exchange
   <last_meaningful_summary>
   (<last_meaningful_at>)

🚧 Why it stalled
   <why_stalled>

🎯 Recommended action
   <recommended_action>
   Why: <recommended_reasoning>

📧 Source emails (<N>)
   • <date>  <subject>  — <from_address>
     <body_preview>
   • ...

— /mine-leads act <id> to create a task. dismiss to skip. status <id> <new> to retag.
```

## Rules

- Default to unreviewed. Reviewed leads stay in DB but don't surface unless explicitly asked.
- Show confidence and source count — Dave wants to evaluate the call before acting.
- Don't auto-act on any lead. Always Dave-decision.
- For `act`, generate a clean task title from recommended_action; include lead context in notes.
