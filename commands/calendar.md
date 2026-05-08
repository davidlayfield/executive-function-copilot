---
description: View Dave's calendar across all synced Google accounts. today / tomorrow / this-week / next-week / free / event <id>.
argument-hint: [today | tomorrow | this-week | next-week | free | event <id> | sync]
---

You are showing Dave his calendar from `efc.calendar_events`. Read-only at v1; write capability (decline, reschedule) is a later phase.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse subcommand

| Subcommand | Behavior |
|---|---|
| (empty) or `today` | Today's events (any account) |
| `tomorrow` | Tomorrow's events |
| `this-week` | Mon–Sun this week |
| `next-week` | Mon–Sun next week |
| `free` | Free-time blocks today + tomorrow |
| `event <id>` | Full detail of one event |
| `unresponded` | Events Dave hasn't RSVP'd to |
| `sync` | Trigger a fresh sync via the ingester (advisory — actual sync runs on Ralph) |

## today (default)

```sql
SELECT account, summary, start_at, end_at, is_all_day, location,
       num_attendees, dave_response, conference_link, conference_kind,
       organizer_email, organizer_name,
       to_char(start_at AT TIME ZONE 'America/New_York', 'HH24:MI') AS start_local,
       to_char(end_at AT TIME ZONE 'America/New_York', 'HH24:MI') AS end_local,
       duration_minutes,
       id
FROM efc.calendar_events
WHERE status = 'confirmed'
  AND (
    (start_at AT TIME ZONE 'America/New_York')::date = (now() AT TIME ZONE 'America/New_York')::date
    OR (is_all_day = true AND start_date = (now() AT TIME ZONE 'America/New_York')::date)
  )
ORDER BY start_at NULLS FIRST, start_date NULLS FIRST;
```

Output:

```
📅 TODAY — <day, date>

  ⛅️ All-day:
    • <summary>  [<account>]
    • ...

  🕘 Timed events:
    HH:MM  <summary>  [<account>]  <duration>m  <attendees>👥
            📍 <location if any>   🎥 <conference_link if any>
            <"⚠️ no RSVP" if dave_response='needsAction'>
            id: <short>
    ...

  📊 Today's load: <total_minutes> min in events, <meeting_minutes> min in meetings
```

If 0 events → "No events scheduled today. Open day."

## tomorrow

Same shape as today, with `+ interval '1 day'` math.

## this-week / next-week

Group by day. Each day shows count + total time.

```sql
SELECT
  (start_at AT TIME ZONE 'America/New_York')::date AS day,
  to_char(start_at AT TIME ZONE 'America/New_York', 'Dy Mon DD') AS day_label,
  to_char(start_at AT TIME ZONE 'America/New_York', 'HH24:MI') AS start_local,
  summary, duration_minutes, account, num_attendees, dave_response, id
FROM efc.calendar_events
WHERE status = 'confirmed'
  AND start_at >= date_trunc('week', now() AT TIME ZONE 'America/New_York')
  AND start_at <  date_trunc('week', now() AT TIME ZONE 'America/New_York') + interval '7 days'
ORDER BY start_at;
```

Output:

```
📅 THIS WEEK

Mon May 12 — <total> min, <count> events
  HH:MM  <summary>  [<account>]
  ...

Tue May 13 — light day, <count> events
  ...
```

## free

Compute free blocks for today + tomorrow during business hours (9-17 ET):

```sql
WITH today_events AS (
  SELECT start_at, end_at FROM efc.calendar_events
  WHERE status='confirmed' AND NOT is_all_day
    AND (start_at AT TIME ZONE 'America/New_York')::date = (now() AT TIME ZONE 'America/New_York')::date
  ORDER BY start_at
)
SELECT * FROM today_events;
```

Then in Python (or output): walk events, identify gaps ≥30 min between them within 9-17 ET window.

Output:

```
🆓 FREE BLOCKS (≥30 min, business hours ET)

TODAY (<date>):
  • 09:00 – 10:30  (1h 30m)
  • 13:00 – 14:00  (1h)
  • 16:30 – 17:00  (30m)
  Total free: 3h

TOMORROW (<date>):
  ...
```

## event <id>

```sql
SELECT * FROM efc.calendar_events WHERE id = '<full_id>';
```

Output:

```
📅 EVENT — <summary>
   id: <full uuid>     account: <account>     google_id: <google_event_id>
   <link to Google Calendar: html_link>

🕐 When
   <start in ET, e.g. "Friday May 9, 9:00 AM ET"> – <end>
   Duration: <minutes>m
   TZ: <timezone>

📍 Location
   <location or "—">

🎥 Conference
   <conference_kind>: <conference_link>

👥 Attendees (<count>)
   ✓ <name> <email> (<responseStatus>)
   ⏳ <name> (needsAction)
   ✗ <name> (declined)

📝 Description
   <description (truncated 1500 chars)>

📌 Your RSVP: <dave_response>
   You're <"organizer" or "attendee">
   Recurring: <yes/no, rrule if recurring>
```

## unresponded

```sql
SELECT id, summary, start_at, num_attendees, organizer_name
FROM efc.calendar_events
WHERE status='confirmed' AND dave_response IN ('needsAction','tentative')
  AND start_at > now()
ORDER BY start_at LIMIT 25;
```

Output a list with prompts to respond.

## sync (advisory)

Show last sync time + how to trigger:

```sql
SELECT account, last_synced_at, last_sync_status, last_sync_notes FROM efc.calendar_sync_state;
```

```
📡 Calendar sync state
  • <account>: last <relative time> ago — <status>
  • ...

To trigger an immediate sync, run on Ralph:
  ssh ralph 'sudo systemctl start dave-os-calendar-ingest.service'
```

## Rules

- Times in America/New_York (Dave's TZ). Show in 24h clock.
- Group multi-account view; tag account in brackets.
- Don't show CANCELLED events (status filter).
- For free blocks, only count business-hours by default. `free all-day` to include 6 AM – 10 PM.
- Don't coach. This is a calendar viewer.
