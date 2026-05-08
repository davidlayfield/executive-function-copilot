---
name: unsubscribe-manager
description: Manage the inbox unsubscribe queue. Three-tier fallback (best HTTP POST one-click, middle browser-driven, worst manual list). Auto-attempt on detection from M2 routine; queue failures for Monday brief. Use when an inbox-process routine flags an email for unsubscribe, when /inbox-unsubscribe is run, or when the weekly unsubscribe-brief routine fires.
---

# Unsubscribe Manager (Dave OS Phase 4 M5b)

Goal: every newsletter or marketing sender Dave doesn't actively want gets unsubscribed within 7 days, without Dave thinking about it. Three-tier fallback per Clearpath PRD §12.2.

## Detection (upstream)

The M2 `dave-os-inbox-process` routine already populates `efc.unsubscribe_queue` when:
- Email classified as NOISE or SPAM AND has `List-Unsubscribe` header AND not on whitelist AND sender not in queue already (or already-completed)
- Or Dave manually says "unsub: <pattern>" in a digest reply

Each row carries:
- `sender_email` (from from_address)
- `sender_pattern` (`%@<domain>` for sender's domain)
- `sample_subject` (the most recent subject from this sender)
- `times_seen` (incremented on each subsequent matching email)
- `unsubscribe_url` (from List-Unsubscribe header, parsed)
- `list_unsubscribe_post` (one-click POST URL if RFC 8058 supported)

## Three-tier auto-attempt

When this skill is asked to attempt an unsubscribe (by `/inbox-unsubscribe` or the routine):

### Tier 1 (best — RFC 8058 one-click POST)
If `list_unsubscribe_post` is set:
- HTTP POST to that URL with `Content-Type: application/x-www-form-urlencoded` body `List-Unsubscribe=One-Click`
- 2xx response → SUCCESS
- 4xx/5xx → fall through to Tier 2

### Tier 2 (middle — Chrome MCP browser-driven)
If `unsubscribe_url` is set and Tier 1 didn't apply or failed:
- Use Chrome MCP (claude-in-chrome) to load the URL
- Look for one-click confirm button: text matching "unsubscribe", "confirm", "yes, remove me"
- If found and visible without auth/CAPTCHA → click → SUCCESS
- If form requires email input → fill with the destination email → click → SUCCESS
- If CAPTCHA / login wall / form too complex → mark FAILED with reason

### Tier 3 (worst — surface to Dave)
If Tier 1 + 2 both failed or unavailable:
- Mark `status='failed'` with `failure_reason`
- Surface in next Monday's brief with the URL clickable for manual handling

## Auto-archive rule on success

When an auto-unsubscribe succeeds (any tier):
- Mark `efc.unsubscribe_queue.status='completed'`, `completed_at=now()`
- **Auto-create matching `efc.inbox_rules` entry** (action=auto_archive, condition.from=sender_pattern) so any stragglers vanish without classification cost

```sql
INSERT INTO efc.inbox_rules (name, rule_type, conditions, action, scope_account, active, created_by, notes)
VALUES (
  'Auto-archive after unsub: <sender>',
  'auto_archive',
  jsonb_build_object('from', '<sender_pattern>', 'match_logic', 'and'),
  jsonb_build_object('apply', 'archive_in_gmail'),
  NULL, true, 'autonomous',
  'Auto-created after successful unsubscribe at <date>'
);
```

## Monday 8:30 AM unsubscribe brief

The `dave-os-weekly-unsubscribe-brief` routine fires Mondays at 8:30 AM (after the newsletter digest at 8:07 to avoid notification stacking) and produces:

```
✂️ UNSUBSCRIBE BRIEF — week of <date>

✅ Auto-unsubscribed (this week): <N>
   • <sender pattern> — <times_seen> emails saved
   • ...

⏳ Recommended manual unsubscribe (auto failed): <N>
   • <sender pattern> — <reason>
     <unsubscribe_url> ← click to handle
   • ...

📊 All-time saved: <N> senders unsubscribed, ~<estimate> emails/year saved
   (estimate = sum of times_seen across completed * 52)

— Reply: "ignore: <pattern>" to stop tracking, "retry: <pattern>" to attempt again, "unsub: <pattern>" to add a new one
```

If 0 in any section, skip that section.

## What this skill does NOT do

- Doesn't classify emails (M2 routine does)
- Doesn't manage whitelist (`/inbox-whitelist` does)
- Doesn't run the actual HTTP/browser calls itself — the routine or `/inbox-unsubscribe` command orchestrates with the appropriate MCPs
- Doesn't promise success. Some senders ignore unsubscribe requests entirely; we surface failures honestly

## Edge cases

- **Sender uses redirect chain**: follow up to 3 redirects. If 4+, assume tracking shenanigans, mark FAILED with reason "redirect chain too deep".
- **Sender requires login**: cannot bypass; mark FAILED with reason "auth required".
- **Sender is on whitelist**: should never be queued. If it is, log inconsistency and skip.
- **Sender pattern matches multiple distinct list-unsubscribe URLs across runs**: keep latest URL but log; might mean multiple newsletters from the same sender.
- **Repeat after success**: if a sender continues to send after 14 days post-completion, mark `status='recommended'` again with note "still sending after unsub" — they ignored the request.
