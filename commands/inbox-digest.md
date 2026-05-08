---
description: Show the most recent newsletter digest, or generate a fresh one on-demand. Stories grouped by Dave's interest topics, source breakdown, unreviewed-newsletter prompts.
argument-hint: [latest | this-week | last-week | now (force regenerate) | source <name>]
---

You are showing Dave a newsletter digest. Either pull the most recent one from `efc.newsletter_digests` or generate a fresh one by extracting stories from this period's NEWSLETTER-classified emails.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse argument

| Arg | Behavior |
|---|---|
| (empty) or `latest` | Show the most recent digest from `efc.newsletter_digests` |
| `this-week` | Generate a fresh digest for week starting Monday this week |
| `last-week` | Generate fresh for week starting Monday last week |
| `now` | Force regenerate for the current week, replacing any existing |
| `source <name>` | Show only stories from that source for the latest digest |

## "latest" — read most recent

```sql
SELECT period_start, period_end, stories, source_breakdown, generated_at
FROM efc.newsletter_digests
ORDER BY period_end DESC LIMIT 1;
```

If no digests exist → "No digest yet. Run /inbox-digest now to generate the first one." Stop.

Render per format below.

## "this-week" / "last-week" / "now" — generate fresh

This is the on-demand version of what the weekly Monday-8AM routine does.

1. Determine period (Mon 00:00 to Sun 23:59 in America/New_York).
2. Query newsletter emails in that period:

```sql
WITH wk AS (SELECT '<period_start>'::date AS s, '<period_end>'::date AS e)
SELECT
  iel.account, iel.message_id, iel.thread_id, iel.subject,
  iel.sender_email, iel.classified_at,
  ns.id AS source_id, ns.display_name AS source_name,
  eb.body_plain, eb.body_html
FROM efc.inbox_email_log iel
JOIN openbrain.email_bodies eb
  ON eb.account = iel.account AND eb.message_id = iel.message_id
LEFT JOIN efc.newsletter_sources ns
  ON iel.sender_email ILIKE replace(ns.sender_pattern, '%', '%') AND ns.status='whitelisted'
WHERE iel.classification = 'newsletter'
  AND iel.classified_at::date BETWEEN (SELECT s FROM wk) AND (SELECT e FROM wk);
```

3. Pull active interests:
```sql
SELECT id, topic, keywords, weight FROM efc.newsletter_interests WHERE active = true;
```

4. For each newsletter email, apply the `newsletter-extraction` skill rules:
   - Walk body, identify discrete stories (headline + url + summary)
   - Score each story HIGH/MEDIUM/LOW/SKIP against interests
   - Save HIGH+MEDIUM only

5. Aggregate stories grouped by best-matching interest topic.

6. Build source_breakdown: `{source_name: {emails: N, stories: M}, ...}`

7. Pull unreviewed newsletters seen in this period:
```sql
SELECT id, sender_pattern, total_processed, display_name
FROM efc.newsletter_sources
WHERE status = 'unreviewed'
  AND last_processed_at::date >= '<period_start>'
ORDER BY total_processed DESC LIMIT 5;
```

8. Write the digest:
```sql
INSERT INTO efc.newsletter_digests (period_start, period_end, stories, source_breakdown)
VALUES ('<start>', '<end>', '<stories jsonb>', '<source_breakdown jsonb>')
ON CONFLICT (period_start, period_end) DO UPDATE SET
  stories = EXCLUDED.stories,
  source_breakdown = EXCLUDED.source_breakdown,
  generated_at = now();
```

## Output format (both for latest and fresh)

```
📰 NEWSLETTER DIGEST — week of <date>

<topic 1> — <N> stories
  • <headline> [<source>]
    <summary, max 200 chars>
    <url>
  • ...

<topic 2> — <N> stories
  • ...

📊 SOURCES THIS WEEK
  • <Source name>: <N> emails, <M> stories surfaced
  • ...

📌 UNREVIEWED NEWSLETTERS — these look newslettery; not whitelisted yet
  • <pattern> (seen Nx) — add to whitelist? unsubscribe?
  • ...

— Reply: "add: <pattern>" / "unsub: <pattern>" / "remove topic: <name>" /
         "tell me more about: <story headline>"
```

## "source <name>" — filtered view

Pull the latest digest, filter `stories` jsonb to entries where `newsletter_source_name ILIKE '%<name>%'`. Output only those, with the source's overall stats.

## Rules

- One screen if possible. Cap at 3-5 stories per topic; show "and N more" if cut.
- For HIGH stories, lead with them visually (perhaps `★`).
- If the stored digest is older than this week and Dave asked for `latest`, note it: "Latest digest is from week of <date>. Want me to generate this week now? (/inbox-digest now)"
- If 0 stories surfaced for the period → "No HIGH/MEDIUM stories from your interests this week. Want to widen your interests? Run /inbox-whitelist suggest or add an interest topic."
- Don't summarize the summaries; let the source's own framing stand.
- For "tell me more about", that's a deeper /inbox-show-style action — for now just acknowledge and offer to look up the source email.
