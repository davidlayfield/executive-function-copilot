---
description: Show full detail for one inbox-AI task — email body, headers, score breakdown, project link, classification reasoning.
argument-hint: <task id (full or 7-char prefix)>
---

You are showing Dave the full context of one task. The id may be a full UUID or a 7-char prefix (per /inbox-tasks output).

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Resolve id

If user gave 7+ chars, do prefix match:
```sql
SELECT id FROM efc.tasks WHERE id::text LIKE '<prefix>%' LIMIT 2;
```

If 0 matches → "No task with id starting <prefix>." stop.
If 2+ matches → list ambiguous, ask user to give more chars. Stop.

## Step 2 — Pull task + email body + project + log

```sql
SELECT
  t.id, t.title, t.notes, t.status, t.priority,
  t.priority_score, t.score_dimensions, t.score_reason,
  t.ymyl_classification, t.ymyl_alert,
  t.due_date, t.deadline, t.deferred_until,
  t.source_email_id, t.source_account, t.sender_name, t.sender_email, t.thread_id,
  t.created_at, t.updated_at, t.completed_at,
  t.openbrain_memory_id,
  p.name AS project_name, p.id AS project_id, p.desired_outcome AS project_outcome,
  -- Full email body (if from email)
  eb.subject AS email_subject,
  eb.body_plain AS body_plain,
  eb.body_html AS body_html,
  eb.from_address AS from_address,
  eb.from_name AS from_name,
  eb.to_addresses AS to_addresses,
  eb.cc_addresses AS cc_addresses,
  eb.date_received AS date_received,
  eb.has_attachments,
  eb.attachment_summary,
  eb.list_unsubscribe IS NOT NULL AS has_unsubscribe,
  -- Classification log entry
  iel.classification AS log_classification,
  iel.classification_confidence,
  iel.classified_by_model,
  iel.classified_at AS log_classified_at,
  iel.rule_hits AS log_rule_hits
FROM efc.tasks t
LEFT JOIN efc.projects p ON p.id = t.project_id
LEFT JOIN openbrain.email_bodies eb
  ON eb.account = t.source_account AND eb.message_id = t.source_email_id
LEFT JOIN efc.inbox_email_log iel
  ON iel.account = t.source_account AND iel.message_id = t.source_email_id
WHERE t.id = '<full-uuid>'
LIMIT 1;
```

If no rows → "Task not found." stop.

## Step 3 — Output

```
📋 TASK — <full title>
       id: <full uuid>      created: <relative> ago    updated: <relative> ago
       status: <status>     priority: <priority>       score: <score>
       <YMYL row if applicable>

⚡ Why this scored <X>
       <score_reason in full>

📊 Score dimensions
       Urgency:           <0.0–1.0> ████░░░░  weight 0.25
       Importance:        <0.0–1.0> █████░░░  weight 0.25
       Sender authority:  <0.0–1.0> ████░░░░  weight 0.20
       Deadline proximity:<0.0–1.0> ███░░░░░  weight 0.15
       Financial impact:  <0.0–1.0> ██░░░░░░  weight 0.10
       Context richness:  <0.0–1.0> █░░░░░░░  weight 0.05

🚨 YMYL ALERT (only if ymyl_classification IS NOT NULL)
       Severity: <critical|high|medium>
       What:     <ymyl_alert.what>
       Deadline: <ymyl_alert.deadline>
       Consequence: <ymyl_alert.consequence>
       Next step:   <ymyl_alert.next_step>

🗂 Project
       <project name> — <project outcome>
       (or: "Not yet attached to a project")

📧 SOURCE EMAIL
       Subject: <email_subject>
       From:    <from_name> <<from_address>>
       To:      <to_addresses joined>
       CC:      <cc_addresses joined or "—">
       Date:    <date_received>
       Account: <source_account>
       Model:   classified by <classified_by_model> @ <log_classified_at>, confidence <classification_confidence>
       <"Has unsubscribe link" if has_unsubscribe>
       <"Attachments: filename, filename" if has_attachments>

📜 BODY (truncated to 2000 chars; full available via SQL on openbrain.email_bodies)
       <body_plain or stripped body_html>

📝 EXTRACTED NOTES
       <task notes>

⚙️  ACTIONS
       /inbox-update <id> done           Mark complete.
       /inbox-update <id> push <date>    Defer to a date or "next-week" or "monday".
       /inbox-update <id> drop           Drop entirely.
       /inbox-update <id> waiting <person>  Mark waiting on someone.
       /inbox-update <id> reclassify <category>   Override the classification (and learn).
```

## Rules

- One screen if possible. If body is long, truncate body_plain at 2000 chars and say "...truncated, see full via SQL."
- Show body_html stripped to text if body_plain is null.
- If `from_address` is in `efc.people`, append the person's `importance_score` and `relationship_tags` after the From line.
- The Score dimensions block uses 8-char ASCII bars: `█` for filled, `░` for empty. Each dim shows `round(value * 8)` filled chars.
- If there's no source email (manually captured task), skip the SOURCE EMAIL block and the BODY block; just show the manual notes.
- Don't coach. Don't suggest action. Just present the data clearly.
