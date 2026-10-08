"""Fake-database / fake-model drive of extract_pending.py failure handling.

No network, no model spend, made-up data only. Run: python3 -I test_extract_pending.py
"""
import importlib.util, os, sys, time

os.environ["SUPABASE_URL"] = "http://fake"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "fake"
spec = importlib.util.spec_from_file_location("ep", os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract_pending.py"))
ep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ep)

calls = []          # (method, path, params, body)
fail_on = set()     # (method, path) pairs that raise
seen_timeouts = []

def fake_req(method, path, params=None, body=None, extra_headers=None, timeout=60):
    calls.append((method, path, params, body))
    if (method, path) in fail_on:
        raise RuntimeError(f"{method} {path} 500: boom")
    if method == "GET" and path == "entities":
        return []
    return None

MODEL_OUT = {
    "entity_extraction": [
        {"surfaced_text": "Acme Plumbing", "suggested_type": "vendor", "confidence": "high"},
        {"surfaced_text": "Fake Person", "suggested_type": "person", "confidence": 0.9,
         "suggested_aliases": ["FP", None]},
        {"surfaced_text": "Oak Street", "suggested_type": "place", "confidence": None},
    ],
    "relationship_extraction": [{"entity_a_text": "Fake Person", "entity_b_text": "Acme Plumbing",
                                 "relationship_type": "vendor_for", "confidence": "likely"}],
    "categorical_resolution": [],
    "open_questions": [{"entity_text": "Acme Plumbing", "question": "Who is the contact?"}],
    "behavior_signals": [{"signal_type": "friction", "observation": "Chased twice."}],
    "lens_discovery": None,
}

def fake_model(sys_prompt, text, model, timeout):
    seen_timeouts.append(timeout)
    return MODEL_OUT

ep._req = fake_req
ep.run_lenses = fake_model

def reset():
    calls.clear(); fail_on.clear(); seen_timeouts.clear(); ep.errors.clear()
    for k in ep.stats: ep.stats[k] = 0 if k != "cost_usd" else 0.0

def inserts():
    return [c for c in calls if c[0] == "POST"]

def marks():
    return [c for c in calls if c[0] == "PATCH" and c[1] == "inbox_email_log"]

def run(item=("inbox_email_log", "row-1", "Subject: x\n\nbody text"), deadline=None, hard=None):
    now = time.time()
    ep.process_safe(item, "sys", 1, "sonnet", deadline or now + 400, hard or now + 490)

ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# 1. bad confidence values do not throw; everything lands once; row claimed BEFORE writes
reset(); run()
order = [c[0] + " " + c[1] for c in calls if c[0] in ("POST", "PATCH")]
check("1 no errors on 'high'/'likely'/None confidence", not ep.errors, ep.errors)
check("1 six inserts landed (3 cand, 1 relc, 1 oq, 1 sig)", len(inserts()) == 6, len(inserts()))
check("1 claim is the first write", order and order[0] == "PATCH inbox_email_log", order[:2])
check("1 bad confidence fell back to default 0.7",
      [c[3]["confidence"] for c in inserts() if c[1] == "entity_candidates"] == [0.7, 0.9, 0.7])
check("1 null alias dropped", [c[3]["suggested_aliases"] for c in inserts()
                               if c[1] == "entity_candidates"][1] == ["FP"])

# 2. claim (mark) fails: NOTHING written, error recorded
reset(); fail_on.add(("PATCH", "inbox_email_log")); run()
check("2 failed claim writes nothing", len(inserts()) == 0, len(inserts()))
check("2 failed claim is reported", any("ROW_ERR" in e for e in ep.errors), ep.errors)

# 3. one insert table fails: others land, row stays claimed, error recorded, no retry path
reset(); fail_on.add(("POST", "entity_open_questions")); run()
check("3 other five inserts landed", len(inserts()) == 6 and
      sum(1 for c in inserts() if c[1] != "entity_open_questions") == 5)
check("3 row claimed exactly once", len(marks()) == 1)
check("3 insert failure reported", any("WRITE_ERR" in e and "entity_open_questions" in e
                                       for e in ep.errors), ep.errors)

# 4. model gets only the time actually left
reset(); now = time.time(); run(deadline=now + 5, hard=now + 75)
check("4 model timeout capped to time left", seen_timeouts and seen_timeouts[0] <= 75,
      seen_timeouts)
reset(); now = time.time(); run(deadline=now + 5, hard=now + 20)
check("4 no model call with <30s left, row unmarked, nothing written",
      not seen_timeouts and not marks() and not inserts() and ep.stats["skipped_budget"] == 1)
reset(); now = time.time(); run(deadline=now - 1, hard=now + 100)
check("4 no row starts after the budget", not seen_timeouts and ep.stats["skipped_budget"] == 1)

# 5. model error: unmarked, nothing written, reported
reset()
def boom(*a, **k): raise RuntimeError("cap")
ep.run_lenses = boom; run(); ep.run_lenses = fake_model
check("5 model error leaves row unmarked and writes nothing",
      not marks() and not inserts() and any("MODEL_ERR" in e for e in ep.errors))

# 6. two unparseable answers: marked once, counted, nothing else written
reset(); ep.run_lenses = lambda *a, **k: None; run(); ep.run_lenses = fake_model
check("6 parse fail marks once and counts", len(marks()) == 1 and not inserts()
      and ep.stats["parse_fail"] == 1)

# 7. empty-text mark failure is reported, not swallowed
reset(); fail_on.add(("PATCH", "journal_entries")); run(item=("journal_entries", "j1", ""))
check("7 empty-text mark failure reported", any("ROW_ERR" in e for e in ep.errors), ep.errors)

# 8. main() reads futures: an exception escaping a worker shows in errors
reset()
real_ps = ep.process_safe
ep.process_safe = lambda *a: (_ for _ in ()).throw(RuntimeError("escaped"))
ep.build_queue = lambda v, n: [("inbox_email_log", "r9", "Subject: x\n\nbody")]
ep._req = lambda m, p, params=None, body=None, extra_headers=None, timeout=60: (
    [{"name": "entity_extraction", "prompt_template": "x", "version": 1}]
    if p == "extraction_lenses" else fake_req(m, p, params, body, extra_headers, timeout))
sys.argv = ["x", "--batch", "1"]
ep.main()
ep.process_safe = real_ps
check("8 escaped worker exception recorded", any("WORKER_ERR" in e for e in ep.errors), ep.errors)
ps = [c for c in calls if c[1] == "poller_state"]
check("8 poller_state says partial", ps and ps[-1][3]["last_run_status"] == "partial")

# 9. ilike pattern escaping
captured = []
ep._req = lambda m, p, params=None, body=None, extra_headers=None, timeout=60: captured.append(params) or []
ep.resolve_entity("50%_off"); ep.resolve_entity("A*B")
check("9 % and _ escaped", captured and captured[0]["name"] == "ilike.50\\%\\_off", captured)
check("9 name with * never queried", len(captured) == 1)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
