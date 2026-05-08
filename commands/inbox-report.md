---
description: Weekly inbox-AI metrics report — classification breakdown, task throughput, draft acceptance, automation efficiency, top senders, recommendations. Plain-English brief, not a dashboard.
argument-hint: [period — week (default) | last-week | last-30-days | last-90-days | all-time]
---

You are producing Dave's inbox-AI report. Read-only — no writes; this is pure analytics over the data the M2 routine has been collecting.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse period

| Arg | Period |
|---|---|
| (empty) or `week` | Last 7 days |
| `last-week` | The Mon-Sun before this week |
| `last-30-days` | Now − 30 days |
| `last-90-days` | Now − 90 days |
| `all-time` | All recorded data |

## Step 2 — Pull metrics

For the chosen period, run:

```sql
WITH p AS (SELECT '<start>'::timestamptz AS s, '<end>'::timestamptz AS e),

-- Inbox activity
classification AS (
  SELECT classification, count(*) AS n
  FROM efc.inbox_email_log iel, p
  WHERE iel.classified_at BETWEEN p.s AND p.e
  GROUP BY 1
),

-- Task throughput
tasks_summary AS (
  SELECT
    count(*) AS extracted,
    count(*) FILTER (WHERE status='done')        AS completed,
    count(*) FILTER (WHERE status='dropped')     AS dropped,
    count(*) FILTER (WHERE status='deferred')    AS deferred,
    count(*) FILTER (WHERE status='waiting')     AS waiting,
    count(*) FILTER (WHERE status IN ('todo','doing'))  AS active,
    count(*) FILTER (WHERE ymyl_classification IS NOT NULL) AS ymyl_count,
    avg(EXTRACT(EPOCH FROM (completed_at - created_at))/3600) FILTER (WHERE status='done') AS avg_hours_to_done
  FROM efc.tasks t, p
  WHERE t.created_at BETWEEN p.s AND p.e
    AND source_email_id IS NOT NULL
),

-- Top senders by volume + by importance
top_senders AS (
  SELECT iel.sender_email,
         count(*) AS volume,
         count(*) FILTER (WHERE iel.classification IN ('actionable','ymyl')) AS actioned,
         max(per.importance_score) AS importance
  FROM efc.inbox_email_log iel, p
  LEFT JOIN efc.people per ON lower(per.email_normalized) = lower(iel.sender_email)
  WHERE iel.classified_at BETWEEN p.s AND p.e
  GROUP BY iel.sender_email
  ORDER BY volume DESC
  LIMIT 10
),

-- Rules fired
rules_fired AS (
  SELECT name, times_applied, last_applied_at
  FROM efc.inbox_rules
  WHERE active = true AND last_applied_at >= (SELECT s FROM p)
  ORDER BY times_applied DESC
  LIMIT 5
),

-- Unsubscribe activity
unsub AS (
  SELECT
    count(*) FILTER (WHERE status='completed' AND completed_at BETWEEN (SELECT s FROM p) AND (SELECT e FROM p)) AS completed_this_period,
    count(*) FILTER (WHERE status='failed') AS still_failed
  FROM efc.unsubscribe_queue
),

-- Newsletter digest activity
digests AS (
  SELECT count(*) AS digest_count, sum(jsonb_array_length(stories)) AS total_stories
  FROM efc.newsletter_digests
  WHERE period_end BETWEEN (SELECT s FROM p) AND (SELECT e FROM p)
)

SELECT * FROM classification, tasks_summary, unsub, digests;
```

(Pull `top_senders` and `rules_fired` separately for readability.)

## Step 3 — Compute derived metrics

- **Time-saved estimate:** assume each NOISE/SPAM auto-archived saved Dave ~10 sec of human triage = (`noise_count + spam_count`) * 10 / 60 = N minutes
- **Automation rate:** `(noise + spam + newsletter) / total` — % of emails handled without Dave-action
- **Task completion rate:** `completed / extracted` (last period)
- **YMYL rate:** `ymyl_count / total` — % of emails that needed urgent attention

Compare to previous period of same length where possible:
```sql
-- Previous-period comparison
WITH p2 AS (SELECT (<start> - (<end> - <start>))::timestamptz AS s, <start>::timestamptz AS e)
SELECT count(*) FROM efc.inbox_email_log, p2 WHERE classified_at BETWEEN p2.s AND p2.e;
```

Surface as deltas (e.g. "+18% vs prior period").

## Step 4 — Output (plain English, one screen)

```
📊 INBOX REPORT — <period description>

Inbox activity
  • <total> emails classified  (<delta>% vs prior period)
  • Breakdown:
        ACTIONABLE  <n>  (<%>)
        YMYL         <n>  (<%>)
        INFORMATIONAL <n>  (<%>)
        NEWSLETTER   <n>  (<%>)
        NOISE        <n>  (<%>)
        SPAM         <n>  (<%>)
  • Automation rate: <%> (NOISE+SPAM+NEWSLETTER auto-handled)

Task management
  • <extracted> tasks extracted from email
  • <completed> done • <deferred> pushed • <dropped> dropped • <waiting> waiting on someone
  • <active> still in your queue
  • Avg time-to-done: <hours>h
  • Completion rate: <%>

YMYL alerts
  • <ymyl_count> alerts surfaced
  • Critical: <n>  • High: <n>  • Medium: <n>

Top senders by volume (this period)
  • <email> — <volume> emails, <actioned> resulted in tasks, importance <X>
  • ...

Rules fired
  • "<rule name>" fired <N>x (last <date>)
  • ...

Unsubscribe
  • <completed_this_period> auto-unsubscribed this period
  • <still_failed> waiting on manual handling

Newsletters
  • <digest_count> digests generated
  • <total_stories> stories surfaced
  • Top topic: <topic name>

Time saved (estimated)
  • <minutes> min of triage automated this period
  • Extrapolated: ~<weekly minutes> min/week

📌 Recommendations
  1. <first actionable suggestion based on the data — see below>
  2. ...
  3. ...
```

## Step 5 — Generate 3-4 plain-English recommendations

Look at the data and identify the most useful actions:

- High-volume sender that's all NOISE → "Consider unsubscribing from <sender>; <volume> emails this period, all auto-archived."
- High completion rate (>80%) → "You're crushing it on response time. Average <X>h to done."
- Lots of `deferred` items → "Consider running /weekly-review; <N> tasks deferred, may indicate stalled commitments."
- Missing whitelist coverage (NOISE rate going up) → "Run /inbox-whitelist suggest — <N> unreviewed senders this week."
- YMYL rate spiking → "<X> YMYL alerts this period (vs <Y> prior). Worth checking what's escalating."
- Long-deferred items → "Tasks deferred more than 30 days: <N>. Drop or reframe?"
- No tasks completed in N days → "<N> days since last task marked done. Coaching window?"

Pick the 3-4 most impactful for THIS period's data. Don't manufacture recommendations if the data is fine.

## Rules

- One screen if possible. If multi-screen, prioritize: top-line metrics → recommendations → details.
- Use real numbers, not vague "many" or "some".
- Year-over-year comparisons only for `all-time` period.
- If a metric is null/zero, show "—" not "0" (cleaner).
- No coaching tone. This is a report. Recommendations are observational, not prescriptive.
- If the period has 0 emails (system not running yet), say so plainly: "No inbox-AI data for this period."
