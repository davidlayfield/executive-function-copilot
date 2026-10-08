#!/usr/bin/env python3
"""
Dave OS extraction routine (extract-pending), deterministic runner.

Why this exists: the hourly routine used to hand an email row to the lenses as
"subject (from sender)" only. The lenses then either answered in prose ("I don't
see any text to analyze", logged as JSON_PARSE_FAIL) or invented open questions
from a subject line, and the row was marked processed either way. This runner
only feeds rows that carry real text:

  * journal_entries, interactions, knowledge_atoms: their own text, as before.
  * inbox_email_log: the email body joined from openbrain.email_bodies on
    message_id. A row with no usable body is NOT selected and NOT marked, so it
    waits until a body lands (the body backfill fills these over time).

All active lenses run in ONE model call per row (one JSON object back, keyed by
lens name) instead of six calls, so a batch can keep up with new mail. Lens
prompts are read from efc.extraction_lenses at run time; nothing personal lives
in this file.

The model is called through the Claude Code CLI (`claude -p`), so it bills the
subscription token the routine runner already selected (CLAUDE_CODE_OAUTH_TOKEN),
never an API key.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   required (/etc/efc/env on Ralph)
  CLAUDE_CODE_OAUTH_TOKEN                   inherited from run-routine.sh; or
  EXTRACT_TOKEN_SLOT=N                      use CLAUDE_TOKEN_N from the env file
  EXTRACT_BATCH (default 10), EXTRACT_WORKERS (4), EXTRACT_TIME_BUDGET (480 s)
  EXTRACT_MODEL (sonnet), EXTRACT_CLAUDE_BIN (claude on PATH, else ~/.local/bin)

Usage:
  extract_pending.py [--dry-run] [--batch N] [--workers N] [--time-budget S]

--dry-run reads rows and runs the model, prints what WOULD be written per row
(counts only), and writes nothing: no inserts, no marks, no poller_state.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

EMAIL_CLASSES_EXCLUDED = ("noise", "spam")
BODY_MIN_CHARS = 40       # shorter bodies are signatures or blank shells
BODY_MAX_CHARS = 6000     # long newsletters are truncated, not dropped
LENS_ORDER = ["entity_extraction", "relationship_extraction",
              "categorical_resolution", "open_questions", "behavior_signals"]
META_LENS = "lens_discovery"

SUPA_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPA_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

lock = threading.Lock()
stats = {k: 0 for k in ("processed", "mentions", "candidates", "relationships",
                        "rel_candidates", "open_questions", "behavior_signals",
                        "lens_candidates", "parse_fail", "skipped_budget")}
stats["cost_usd"] = 0.0
errors = []
DRY = False


def bump(key, n=1):
    with lock:
        stats[key] += n


def err(msg):
    with lock:
        errors.append(msg)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── PostgREST ────────────────────────────────────────────────────────────────

def _req(method, path, params=None, body=None, extra_headers=None):
    url = f"{SUPA_URL}/rest/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
               "Content-Type": "application/json", "Accept-Profile": "efc",
               "Content-Profile": "efc"}
    headers.update(extra_headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} {e.code}: {e.read().decode()[:200]}")


def sql(query):
    """Read-only SELECT through the exec_readonly_atlas RPC (must start with SELECT)."""
    q = " ".join(query.split())
    return _req("POST", "rpc/exec_readonly_atlas", body={"query_text": q},
                extra_headers={"Accept-Profile": "public", "Content-Profile": "public"}) or []


def insert(table, row):
    if DRY:
        return
    _req("POST", table, body=row, extra_headers={"Prefer": "return=minimal"})


def patch(table, row_id, body):
    if DRY:
        return
    _req("PATCH", table, params={"id": f"eq.{row_id}"}, body=body,
         extra_headers={"Prefer": "return=minimal"})


def resolve_entity(text):
    if not text:
        return []
    try:
        return _req("GET", "entities", params={
            "status": "eq.active", "name": f"ilike.{text}",
            "select": "id,name", "limit": 5}) or []
    except Exception as e:
        err(f"resolve: {str(e)[:80]}")
        return []


# ── Work queue ───────────────────────────────────────────────────────────────

def lit(s):
    return "'" + str(s).replace("'", "''") + "'"


def build_queue(version, limit):
    """Rows with real text only. Priority: journal > interactions > atoms > email."""
    todo = f"(last_extracted_at is null or extraction_version < {int(version)})"
    queue = []
    plain = [
        ("journal_entries", "entry_text", "created_at"),
        ("interactions", "summary", "created_at"),
        ("knowledge_atoms",
         "topic || ': ' || coalesce(summary,'') || coalesce(' | Outcome: ' || decision_or_outcome, '')",
         "created_at"),
    ]
    for table, expr, order in plain:
        if len(queue) >= limit:
            break
        rows = sql(f"select id, {expr} as text from efc.{table} where {todo} "
                   f"order by {order} asc limit {limit - len(queue)}")
        queue += [(table, r["id"], (r.get("text") or "").strip()) for r in rows]
    if len(queue) < limit:
        excluded = ",".join(lit(c) for c in EMAIL_CLASSES_EXCLUDED)
        # Newest first: current mail is what task capture needs; the old
        # backlog drains behind it. Rows with no usable body are left alone.
        rows = sql(f"""
            select l.id, l.subject, coalesce(l.sender_name, l.sender_email) as sender,
                   l.received_at, b.body_plain
            from efc.inbox_email_log l
            join lateral (
                select body_plain from openbrain.email_bodies b
                where b.message_id = l.message_id
                  and length(coalesce(b.body_plain, '')) > {BODY_MIN_CHARS}
                order by b.ingested_at desc limit 1) b on true
            where (l.last_extracted_at is null or l.extraction_version < {int(version)})
              and l.classification is not null
              and l.classification not in ({excluded})
            order by l.received_at desc
            limit {limit - len(queue)}""")
        for r in rows:
            body = re.sub(r"\n{3,}", "\n\n", r["body_plain"].strip())[:BODY_MAX_CHARS]
            text = (f"Subject: {r.get('subject') or ''}\nFrom: {r.get('sender') or 'unknown'}\n"
                    f"Received: {r.get('received_at')}\n\n{body}")
            queue.append(("inbox_email_log", r["id"], text))
    return queue


# ── Model call ───────────────────────────────────────────────────────────────

def system_prompt(lenses):
    parts = [
        "You run several extraction lenses over ONE piece of source text from "
        "Dave's data (a journal entry, an interaction note, a knowledge atom, or "
        "an email with its body). Apply every lens below to the text the user "
        "sends. Then apply the meta-lens last, using the other lenses' outputs.",
        "",
        "Reply with ONE JSON object and nothing else: no prose, no code fences. "
        "Its keys are exactly: " + ", ".join(LENS_ORDER + [META_LENS]) + ". "
        "Each lens key holds that lens's JSON output (an array; [] when the lens "
        f"finds nothing). {META_LENS} holds an object or null.",
    ]
    for name in LENS_ORDER + [META_LENS]:
        if name in lenses:
            parts += ["", f"### LENS {name}", lenses[name].strip()]
    return "\n".join(parts)


def claude_bin():
    b = os.environ.get("EXTRACT_CLAUDE_BIN") or shutil.which("claude")
    return b or os.path.expanduser("~/.local/bin/claude")


def child_env():
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # bill the subscription token, never an API key
    slot = env.get("EXTRACT_TOKEN_SLOT")
    if slot and not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = env.get(f"CLAUDE_TOKEN_{slot}", "")
    return env


def parse_object(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        try:
            obj = json.loads(t[i:j + 1])
            return obj if isinstance(obj, dict) else None
        except ValueError:
            return None
    return None


def run_lenses(sys_prompt, text, model):
    cmd = [claude_bin(), "-p", "--model", model, "--output-format", "json",
           "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--max-turns", "1", "--system-prompt", sys_prompt]
    p = subprocess.run(cmd, input=text, capture_output=True, text=True,
                       timeout=180, env=child_env())
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude exit {p.returncode}: {(p.stderr or p.stdout)[:200]}")
    with lock:
        stats["cost_usd"] += float(out.get("total_cost_usd") or 0)
    if out.get("is_error"):
        raise RuntimeError(f"claude error: {str(out.get('result'))[:200]}")
    return parse_object(out.get("result"))


# ── Writers (column names verified against the live schema) ──────────────────

def as_list(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def write_all(out, table, row_id, text, counts):
    snippet = text[:300]
    ts = now_iso()

    for e in as_list(out.get("entity_extraction")):
        name = (e.get("surfaced_text") or e.get("name") or "").strip()
        if not name:
            continue
        aliases = e.get("suggested_aliases")
        conf = float(e.get("confidence") or 0.7)
        matches = resolve_entity(name)
        if len(matches) == 1:
            insert("entity_mentions", {
                "entity_id": matches[0]["id"], "source_table": table,
                "source_row_id": row_id, "source": "extraction",
                "surfaced_text": name, "extracted_fact": e.get("extracted_fact") or None,
                "via_group": None, "confidence": conf, "surfaced_at": ts})
            patch("entities", matches[0]["id"], {"last_seen_at": ts})
            counts["mentions"] += 1
        else:
            row = {"surfaced_text": name, "suggested_type": e.get("suggested_type") or "other",
                   "suggested_aliases": aliases if isinstance(aliases, list) else [],
                   "context_snippet": snippet, "source_table": table,
                   "source_row_id": row_id, "confidence": conf,
                   "status": "pending", "surfaced_at": ts}
            if matches:
                row["ambiguity_note"] = f"Matched {len(matches)} entities"
            insert("entity_candidates", row)
            counts["candidates"] += 1

    for r in as_list(out.get("relationship_extraction")):
        a, b = (r.get("entity_a_text") or "").strip(), (r.get("entity_b_text") or "").strip()
        if not a or not b:
            continue
        conf = float(r.get("confidence") or 0.5)
        am, bm = resolve_entity(a), resolve_entity(b)
        a_id = am[0]["id"] if len(am) == 1 else None
        b_id = bm[0]["id"] if len(bm) == 1 else None
        if a_id and b_id and conf >= 0.6:
            try:
                insert("entity_relationships", {
                    "entity_a_id": a_id, "entity_b_id": b_id,
                    "relationship_type": r.get("relationship_type") or "knows",
                    "notes": r.get("notes") or None, "source": "extracted",
                    "confidence": conf, "first_observed_in": table})
                counts["relationships"] += 1
            except RuntimeError as ex:
                if "23505" not in str(ex) and "duplicate" not in str(ex).lower():
                    raise
        else:
            insert("relationship_candidates", {
                "entity_a_id": a_id, "entity_b_id": b_id,
                "candidate_a_text": a, "candidate_b_text": b,
                "suggested_type": r.get("relationship_type") or None,
                "context_snippet": snippet, "source_table": table,
                "source_row_id": row_id, "confidence": conf,
                "status": "pending", "surfaced_at": ts})
            counts["rel_candidates"] += 1

    for c in as_list(out.get("categorical_resolution")):
        if c.get("resolution") != "specific":
            continue
        group = c.get("categorical_text") or ""
        for name in c.get("resolved_to") or []:
            m = resolve_entity(str(name))
            if len(m) == 1:
                insert("entity_mentions", {
                    "entity_id": m[0]["id"], "source_table": table,
                    "source_row_id": row_id, "source": "extraction",
                    "surfaced_text": str(name),
                    "extracted_fact": f'via categorical "{group}": {c.get("context_note") or ""}',
                    "via_group": group, "confidence": 0.8, "surfaced_at": ts})
                counts["mentions"] += 1

    for q in as_list(out.get("open_questions")):
        question = (q.get("question") or "").strip()
        if not question:
            continue
        ent = (q.get("entity_text") or "").strip()
        m = resolve_entity(ent)
        eid = m[0]["id"] if len(m) == 1 else None
        insert("entity_open_questions", {
            "entity_id": eid, "candidate_text": None if eid else (ent or None),
            "question": question, "source_table": table, "source_row_id": row_id,
            "status": "pending", "surfaced_at": ts})
        counts["open_questions"] += 1

    for s in as_list(out.get("behavior_signals")):
        obs = (s.get("observation") or "").strip()
        if not obs:
            continue
        insert("behavior_signals", {
            "signal_type": s.get("signal_type") or "other", "observation": obs,
            "suggested_action": s.get("suggested_action") or None,
            "source_table": table, "source_row_id": row_id,
            "surfaced_at": ts, "status": "open"})
        counts["behavior_signals"] += 1

    meta = out.get(META_LENS)
    if isinstance(meta, dict):
        name = (meta.get("suggested_lens_name") or meta.get("suggested_name") or "").strip()
        if name:
            insert("lens_candidates", {
                "suggested_name": name, "rationale": meta.get("rationale") or "",
                "example_input": str(meta.get("example_output") or "")[:500] or None,
                "suggested_by": "meta-lens", "source_table": table,
                "source_row_id": row_id, "status": "pending", "surfaced_at": ts})
            counts["lens_candidates"] += 1


# ── Per row ──────────────────────────────────────────────────────────────────

def process(item, sys_prompt, version, model, deadline):
    table, row_id, text = item
    if time.time() > deadline:
        bump("skipped_budget")
        return
    mark = {"last_extracted_at": now_iso(), "extraction_version": version}
    if not text:
        patch(table, row_id, mark)
        bump("processed")
        return
    out = None
    for _ in range(2):
        try:
            out = run_lenses(sys_prompt, text, model)
        except Exception as e:
            err(f"MODEL_ERR {table} row={row_id}: {str(e)[:120]}")
            return  # not marked: retried next run
        if out is not None:
            break
    if out is None:
        # Two unparseable answers to real text: mark it so one bad row cannot
        # be retried forever, and count it loudly.
        bump("parse_fail")
        err(f"JSON_PARSE_FAIL {table} row={row_id}")
        patch(table, row_id, mark)
        return
    counts = {k: 0 for k in ("mentions", "candidates", "relationships", "rel_candidates",
                             "open_questions", "behavior_signals", "lens_candidates")}
    try:
        write_all(out, table, row_id, text, counts)
    except Exception as e:
        err(f"WRITE_ERR {table} row={row_id}: {str(e)[:120]}")
        return  # not marked: retried next run
    patch(table, row_id, mark)
    bump("processed")
    for k, v in counts.items():
        bump(k, v)
    tag = "WOULD WRITE" if DRY else "wrote"
    print(f"  {table} {row_id} chars={len(text)} {tag}: "
          + " ".join(f"{k}={v}" for k, v in counts.items() if v), flush=True)


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=int(os.environ.get("EXTRACT_BATCH", 10)))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("EXTRACT_WORKERS", 4)))
    ap.add_argument("--time-budget", type=int,
                    default=int(os.environ.get("EXTRACT_TIME_BUDGET", 480)))
    ap.add_argument("--model", default=os.environ.get("EXTRACT_MODEL", "sonnet"))
    a = ap.parse_args()
    DRY = a.dry_run
    if not SUPA_URL or not SUPA_KEY:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    started = time.time()
    lenses_rows = _req("GET", "extraction_lenses", params={
        "status": "eq.active", "select": "name,prompt_template,version"}) or []
    if not lenses_rows:
        print("no lenses active, nothing to do.")
        return
    version = max(r["version"] for r in lenses_rows)
    lenses = {r["name"]: r["prompt_template"] for r in lenses_rows}
    sys_prompt = system_prompt(lenses)

    queue = build_queue(version, a.batch)
    by_src = {}
    for t, _, _ in queue:
        by_src[t] = by_src.get(t, 0) + 1
    print(f"{'DRY RUN, nothing written. ' if DRY else ''}Work queue: {len(queue)} rows "
          f"{by_src or ''} (lens version {version}, model {a.model}, {a.workers} workers)",
          flush=True)

    deadline = started + a.time_budget
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        for item in queue:
            pool.submit(process, item, sys_prompt, version, a.model, deadline)

    notes = (f"Processed {stats['processed']} of {len(queue)} rows with real text. "
             f"parse_fail={stats['parse_fail']} errors={len(errors)} "
             f"cost=${stats['cost_usd']:.2f}")
    if errors:
        notes += " | " + "; ".join(errors[:3])
    if not DRY:
        try:
            _req("POST", "poller_state", body={
                "source": "extract-pending", "last_polled_at": now_iso(),
                "last_run_status": "ok" if not errors else "partial",
                "last_run_notes": notes[:1000], "updated_at": now_iso()},
                extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        except Exception as e:
            print(f"POLLER_STATE_ERR: {e}")

    print(f"""
{'DRY RUN (nothing written)' if DRY else 'Extraction routine complete'} in {time.time() - started:.0f}s

Processed: {stats['processed']} of {len(queue)} rows   skipped (time budget): {stats['skipped_budget']}
Generated: {stats['mentions']} mentions  {stats['candidates']} candidates  {stats['relationships']} relationships  {stats['rel_candidates']} rel candidates
           {stats['open_questions']} open questions  {stats['behavior_signals']} behavior signals  {stats['lens_candidates']} lens candidates
JSON parse failures: {stats['parse_fail']}   model cost: ${stats['cost_usd']:.2f}
Errors ({len(errors)}): {errors[:5] if errors else 'none'}""")


if __name__ == "__main__":
    main()
