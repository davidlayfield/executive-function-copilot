---
name: newsletter-extraction
description: Extract relevant news stories from whitelisted newsletter emails using Dave's interest topics. Score each story HIGH/MEDIUM/LOW/SKIP. Aggregate into weekly digest. Use when an inbox-process routine has classified an email as NEWSLETTER, or when the weekly digest routine is processing the past week's newsletters.
---

# Newsletter Extraction (Dave OS Phase 4 M5)

Newsletters are content, not action items. The pipeline:

```
1. Classification → 'NEWSLETTER' (handled in email-classification skill)
2. Story extraction (this skill) → individual stories scored against Dave's interests
3. Weekly digest aggregation → one Monday 8 AM brief surfacing the HIGH/MEDIUM stories
```

## What to extract per newsletter email

For each NEWSLETTER classified email, walk the body and identify discrete stories. A story is one of:
- A linked article with a headline + 1-3 sentence summary
- A standalone news blurb with a clear "thing happened" structure
- A linked tool/product launch
- A roundup item (e.g. "5 stories from this week" → 5 stories)

For each story, extract:

```json
{
  "headline": "...",
  "url": "...",
  "summary": "<the newsletter's own 1-3 sentence summary, or auto-summarize if missing>",
  "topic_match": ["<topic name from efc.newsletter_interests>", ...],
  "relevance": "HIGH|MEDIUM|LOW|SKIP",
  "relevance_reason": "<one sentence>",
  "newsletter_source_id": "<uuid from efc.newsletter_sources>",
  "newsletter_source_name": "<display_name>"
}
```

## Relevance scoring

Score each story against Dave's `efc.newsletter_interests`:

```sql
SELECT id, topic, keywords, weight
FROM efc.newsletter_interests
WHERE active = true;
```

For each story:
- **HIGH** — story matches 2+ keywords from one interest, or 1+ keyword from a high-weight interest (weight ≥ 1.2)
- **MEDIUM** — story matches 1 keyword from a normal-weight interest (weight ~1.0)
- **LOW** — story tangentially related (sender's general topic but no specific keyword match)
- **SKIP** — no match; don't include in digest

Save HIGH and MEDIUM stories. SKIP and LOW are dropped (don't pollute the digest with noise).

## Weekly digest format

When the digest routine fires (Monday 8 AM ET) it aggregates HIGH+MEDIUM stories from the past 7 days into one message:

```
📰 NEWSLETTER DIGEST — week of <date>

<topic name 1> — <count> stories
  • <headline> [<source>]
    <summary>
    <url>
  • ...

<topic name 2> — <count> stories
  • ...

<topic name 3> — ...

📊 SOURCES THIS WEEK
  • AI Secret: 12 emails, 8 stories surfaced
  • Robotics Herald: 4 emails, 1 story
  • Bay Area Letters: 1 email, 0 stories
  • TechCrunch: 6 emails, 3 stories
  • Axios Morning: 5 emails, 2 stories
  • Axios AI: 7 emails, 4 stories

📌 UNREVIEWED NEWSLETTERS (looks newslettery, not yet whitelisted)
  • newsletter@brex.com (seen 3x this week) — add to whitelist? unsubscribe?
  • info@otherthing.com (seen 12x this week) — add? unsub?

— Reply with topics to add or remove from your interests, or "add: <pattern>"
   to whitelist, or "unsub: <pattern>" to queue an unsubscribe.
```

Group stories by topic, then by relevance HIGH-then-MEDIUM. One screen if possible — if too many stories, cap at top 3-5 per topic and say "and N more."

## Interest-learning loop

When Dave reads the digest:

- Stories he clicks on (URLs) → topic gets `weight += 0.05` (cap 2.0)
- Stories he asks about ("tell me more about X") → same boost
- Topics where 4+ consecutive digests had HIGH stories Dave didn't engage with → suggest reducing weight
- Topics that consistently surface 0 stories from current sources → suggest removing or asking what new newsletters to whitelist

These adjustments happen in a separate loop driven by Dave's chat replies; this skill just extracts and scores.

## Storage

Each digest is one row in `efc.newsletter_digests`:

```sql
INSERT INTO efc.newsletter_digests (
  period_start, period_end,
  stories,              -- jsonb array of story objects (above)
  source_breakdown,     -- {"AI Secret": {emails: 12, stories: 8}, ...}
  generated_at
) VALUES (...);
```

Per-newsletter `efc.newsletter_sources.last_processed_at` and `total_processed` should be updated when each newsletter email is processed.

## Edge cases

- **Empty newsletter** (just a "no new content this week" message): write to `inbox_email_log` as NEWSLETTER but skip story extraction. Don't pollute the digest.
- **Newsletter with one mega-story** (e.g. a deep-dive issue): treat the whole email as one story.
- **Newsletter where Dave is in the body** (cited, mentioned, linked): bump relevance to HIGH automatically — it's a personal hit.
- **Newsletter from a sender on the whitelist that's clearly NOT a newsletter** (e.g. someone replied to a newsletter sender): reclassify as ACTIONABLE/INFORMATIONAL on the fly. Newsletter classification is sender-based; person-replies override.
- **Same story from multiple newsletters**: dedupe by URL match. Keep one entry, list all sources.

## What this skill does NOT do

- Doesn't classify the email — that's `email-classification`'s job (NEWSLETTER is the upstream tag)
- Doesn't manage the whitelist — that's `/inbox-whitelist` command
- Doesn't write the digest — that's the `dave-os-newsletter-digest` routine (weekly Monday 8 AM)
- Doesn't unsubscribe — that's `unsubscribe-manager` skill
