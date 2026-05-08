---
description: Search and explore institutional knowledge atoms surfaced by deep-dive mining. Filter by atom type, topic, participant, or date range. Show full atom detail. Archive low-value atoms.
argument-hint: [list | search <text> | type <atom-type> | from <person-or-email> | recent | show <id> | archive <id>]
---

You are exploring Dave's institutional knowledge atoms (`efc.knowledge_atoms`). These are decisions, vendor relationships, processes, playbooks, war stories that the deep-dive mining routine has distilled from email history.

Use the **supabase MCP** with project_id `psmkklhyfkivyokhaiga`.

## Step 1 — Parse subcommand

| Subcommand | Behavior |
|---|---|
| (empty) or `recent` | Show 20 most recently extracted, archived=false |
| `search <text>` | Topic + summary ILIKE search |
| `type <atom-type>` | Filter by atom_type (decision/vendor_relationship/process/outcome/playbook/policy/war_story/contact_intel) |
| `from <person-or-email>` | Atoms where person is a participant |
| `show <id>` | Full detail of one atom |
| `archive <id>` | Soft-archive (atom stays but doesn't surface) |
| `unarchive <id>` | Bring back |

## recent (default)

```sql
SELECT id, atom_type, topic, summary, decision_or_outcome,
       what_worked, what_did_not_work, participant_emails,
       source_count, confidence, date_period_start, date_period_end,
       extracted_at
FROM efc.knowledge_atoms
WHERE archived = false
ORDER BY extracted_at DESC
LIMIT 20;
```

Output grouped by atom_type:

```
🧠 KNOWLEDGE ATOMS — recent (showing 20)

📌 Decisions (<count>)
  • <topic>
        <summary>
        Outcome: <decision_or_outcome>
        Period: <start> – <end>  | Confidence: <X>
        id: <short>
  • ...

🤝 Vendor relationships (<count>)
  • ...

⚙️ Processes (<count>)
  • ...

⚔️ War stories (<count>)
  • ...

— /mine-knowledge search <text>  to find by topic
   /mine-knowledge show <id>  for full detail incl. source threads
   /mine-knowledge archive <id>  if not useful
```

## search <text>

```sql
SELECT id, atom_type, topic, summary, source_count, confidence, extracted_at
FROM efc.knowledge_atoms
WHERE archived = false
  AND (topic ILIKE '%<text>%' OR summary ILIKE '%<text>%')
ORDER BY confidence DESC, extracted_at DESC
LIMIT 25;
```

Output:

```
🔍 KNOWLEDGE — "<search>" (<count> matches)

  • [<atom_type>] <topic>
        <summary>
        confidence <X>  | <N> source emails  | id <short>
  • ...
```

If 0 matches → "No knowledge atoms matching '<text>'. Try a broader term or run /mine-knowledge type vendor_relationship to browse by category."

## type <atom-type>

Validate against allowed types. Filter and show ranked by confidence:

```sql
SELECT id, topic, summary, source_count, confidence, extracted_at
FROM efc.knowledge_atoms
WHERE archived = false AND atom_type='<type>'
ORDER BY confidence DESC, extracted_at DESC
LIMIT 25;
```

## from <person-or-email>

Resolve person via efc.people lookup (name or email match). Then:

```sql
SELECT id, atom_type, topic, summary, source_count, confidence, extracted_at
FROM efc.knowledge_atoms
WHERE archived = false
  AND (
    '<person_id>' = ANY(participants)
    OR lower('<email>') = ANY(participant_emails)
  )
ORDER BY extracted_at DESC;
```

## show <id>

Pull the atom + resolve participant names + source thread previews:

```sql
SELECT * FROM efc.knowledge_atoms WHERE id = '<full_id>';

-- Lookup participants by email
SELECT name, organization FROM efc.people
WHERE email_normalized = ANY('<participant_emails>'::text[]);

-- Source thread previews
SELECT thread_id, subject, from_address, date_received,
       substring(body_plain, 1, 300) AS preview
FROM openbrain.email_bodies
WHERE thread_id = ANY('<source_thread_ids>'::text[])
ORDER BY date_received
LIMIT 10;
```

Output:

```
🧠 ATOM — <topic>
   Type: <atom_type>     id: <full uuid>     extracted: <date>
   Period: <date_period_start> – <date_period_end>
   Confidence: <X>      Source: <N> emails analyzed

📝 Summary
   <full summary>

✅ What worked
   <what_worked or "—">

❌ What didn't work
   <what_did_not_work or "—">

🎯 Outcome / Decision
   <decision_or_outcome or "—">

👥 Participants
   • <name> (<organization>) — <email>
   • ...

📧 Source threads (<N>)
   • <date>  <subject>  — <from_address>
     <preview>
   • ...

— /mine-knowledge archive <id>  if no longer useful
```

## archive <id>

```sql
UPDATE efc.knowledge_atoms SET archived=true, updated_at=now()
WHERE id='<id>' RETURNING topic;
```

```
✓ Archived: <topic>. Run /mine-knowledge unarchive <id> to bring back.
```

## Rules

- Default to recent + unarchived. Archived atoms only show on explicit request.
- Group recent view by atom_type for scannable structure.
- Show full source thread previews on `show` so Dave can verify the atom isn't hallucinated.
- Don't archive without explicit Dave action.
