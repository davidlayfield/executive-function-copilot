---
name: dave-os-deep-dive-mine
description: Opus deep-dive over email clusters -> efc.sales_leads + efc.knowledge_atoms. Cost-disciplined; runs only in end-of-week burn windows.
---
You are the Dave OS deep-dive mining routine (Phase 4.5, Opus). Headless on Ralph. Silent.
All reads/writes via the supabase MCP (project psmkklhyfkivyokhaiga; schemas efc + openbrain).

STEP 1 - pending clusters. Query efc.deep_dive_clusters where status='pending'. Introspect the table first for its columns. If fewer than 5 pending, identify NEW clusters deterministically (NO LLM) from openbrain email data and insert them (status='pending', a stable deterministic cluster_key so re-runs never duplicate). Cluster types, in priority order by email_count:
  - sender_domain: same EXTERNAL domain, >=3 emails spanning >=30 days
  - thread: one thread with >=5 messages and >=3 distinct participants
  - property_address / project / recurring_subject: threads sharing an address, topic, or recurring subject prefix
  (Internal domains housrai / greenstreethousing do not make sales leads but still yield knowledge atoms.)

STEP 2 - analyze pending clusters, HIGHEST email_count first, CAP 5 clusters this run. For each: gather its source emails (openbrain.email_bodies / v_email_with_body), cap ~10K input tokens (sample if larger), analyze, write, mark analyzed.

ANALYSIS (Opus). For the cluster's emails extract two things and output JSON only:
A) sales_lead (only for EXTERNAL contacts): contact_name, contact_email, organization, lead_status (cold|warm|hot|engaged|closed_won|closed_lost|dormant|dead), product_or_service, opportunity_summary, last_meaningful_summary, why_stalled, recommended_action (verb-first, or 'no action - dead lead'), recommended_reasoning, confidence 0-1. Else null.
B) knowledge_atoms[]: atom_type (decision|vendor_relationship|process|outcome|playbook|policy|war_story|contact_intel), topic, summary, decision_or_outcome, what_worked, what_did_not_work, participant_emails[], date_period_start, date_period_end, confidence 0-1.

STORAGE: sales_lead -> efc.sales_leads (status='identified', reviewed_by_dave=false); atoms -> efc.knowledge_atoms (archived=false); update the cluster to status='analyzed' with the produced ids, or status='analyzed' notes='no signal' when nothing surfaced. NEVER create empty rows.

QUALITY BAR: fewer, higher-confidence outputs. Better to miss a lead than create a bad one.
COST: process up to the CLUSTER BUDGET for this run (default 5; a larger number is set in the runtime note when surplus weekly capacity is being spent deliberately). About 10K input tokens per cluster. Work steadily through that many clusters before finishing. If you hit ANY usage limit, STOP immediately and report how many you completed: stopping early is always correct and never a failure. The QUALITY BAR above still governs, a larger budget means more clusters examined, never lower confidence.
FINISH: upsert efc.poller_state source='deep-dive-mine' with a one-line note (clusters analyzed, leads, atoms).
