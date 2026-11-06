"""Presence-only resumption plan for the frozen Phase5-C readout conditions.

No file access, Gold, grade or correctness decision. All saved complete outputs,
including empty/incorrect/capped answers, remain authoritative. A partial pair
is recomputed at its ORIGINAL batch shape; existing rows are marked discard.
"""

METHODS = ("ForcedBoxCue", "FullContinue", "FullContract", "FullContractEvidence", "TailContract", "ProjectedContractEvidence", "RestartP")
PAIRS = (METHODS[:2], METHODS[2:4], METHODS[4:6], METHODS[6:])


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def plan_resume(compiled_jobs, worker, existing_records):
    """Return original-pair jobs and keep/discard roles, never select by score.

    compiled_jobs must be the already hash-verified compiled frozen bank (the
    execution worker enforces that full-bank identity). existing_records must
    contain only this worker's UNIQUE authoritative saved rows, across waves.
    Duplicate saved jobs are rejected even when their bytes are identical.
    """
    _need(type(worker) is int and worker in (0, 1), "worker must be integer0/1")
    _need(isinstance(compiled_jobs, (list, tuple)), "compiled_jobs must be rows")
    _need(isinstance(existing_records, (list, tuple)), "existing_records must be rows")
    lookup = {}
    ranks = set()
    for job in compiled_jobs:
        _need(isinstance(job, dict), "compiled job must be a dictionary")
        for key in ("job_id", "rank", "bank_id", "method", "prompt_ids", "prompt_tokens", "prompt_text", "assistant_prefill", "scoring_prefix", "contract_hash", "shared_packet_sha256"):
            _need(key in job, "compiled job missing field: " + key)
        rank, method, jid = job["rank"], job["method"], job["job_id"]
        _need(type(rank) is int and rank > 0, "invalid compiled rank")
        _need(method in METHODS, "unknown compiled method")
        _need(jid == f"{rank:02}__{method}", "compiled ID/rank/method mismatch")
        _need(jid not in lookup, "duplicate compiled job: " + jid)
        _need(isinstance(job["bank_id"], str) and bool(job["bank_id"]), "invalid bank ID")
        _need(type(job["prompt_tokens"]) is int and job["prompt_tokens"] > 0, "invalid prompt length")
        _need(isinstance(job["prompt_ids"], list) and len(job["prompt_ids"]) == job["prompt_tokens"], "compiled prompt length mismatch")
        _need(all(type(v) is int for v in job["prompt_ids"]), "invalid prompt token IDs")
        _need(isinstance(job["prompt_text"], str), "invalid prompt text")
        expected_prefill = r"Final answer: \boxed{" if method == "ForcedBoxCue" else ""
        expected_scoring = r"\boxed{" if method == "ForcedBoxCue" else ""
        _need(job["assistant_prefill"] == expected_prefill and job["scoring_prefix"] == expected_scoring, "compiled prefix policy mismatch")
        _need(not expected_prefill or job["prompt_text"].endswith(expected_prefill), "assistant prefix not in prompt")
        lookup[jid] = job; ranks.add(rank)
    for rank in ranks:
        rows = [lookup.get(f"{rank:02}__{m}") for m in METHODS]
        _need(all(row is not None for row in rows), "incomplete frozen seven-method case")
        _need(len({row["bank_id"] for row in rows}) == 1, "rank maps to different bank IDs")
    selected_ranks = sorted(rank for rank in ranks if (rank-1) % 2 == worker)
    selected_ids = [f"{rank:02}__{method}" for rank in selected_ranks for method in METHODS]
    selected = set(selected_ids)
    saved = {}
    for row in existing_records:
        _need(isinstance(row, dict), "saved row must be a dictionary")
        for key in ("job_id", "rank", "bank_id", "method", "prompt_tokens", "contract_hash", "shared_packet_sha256", "text", "answer_text", "token_ids", "new_tokens", "eos_reached", "hit_cap"):
            _need(key in row, "saved row missing field: " + key)
        jid = row["job_id"]
        _need(jid in lookup, "unknown saved job: " + str(jid))
        _need(jid in selected, "saved row belongs to another worker: " + str(jid))
        _need(jid not in saved, "duplicate authoritative saved job: " + str(jid))
        planned = lookup[jid]
        for key in ("rank", "bank_id", "method", "prompt_tokens", "contract_hash", "shared_packet_sha256"):
            _need(row[key] == planned[key] and type(row[key]) is type(planned[key]), "saved metadata mismatch: " + key)
        _need(isinstance(row["text"], str) and isinstance(row["answer_text"], str), "saved output must be text")
        _need(row["answer_text"] == planned["scoring_prefix"] + row["text"], "saved scoring prefix mismatch")
        _need(type(row["new_tokens"]) is int and 1 <= row["new_tokens"] <= 384, "saved token count out of contract")
        _need(isinstance(row["token_ids"], list) and len(row["token_ids"]) == row["new_tokens"], "saved token length mismatch")
        _need(all(type(v) is int for v in row["token_ids"]), "invalid saved token IDs")
        _need(type(row["eos_reached"]) is bool and type(row["hit_cap"]) is bool, "invalid saved stop flags")
        _need(row["eos_reached"] != row["hit_cap"], "incomplete or inconsistent saved stop")
        _need(not row["hit_cap"] or row["new_tokens"] == 384, "cap row violates frozen384 guard")
        saved[jid] = row
    batches, skipped = [], []
    for rank in selected_ranks:
        for methods in PAIRS:
            ids = [f"{rank:02}__{method}" for method in methods]
            missing = [jid for jid in ids if jid not in saved]
            batch_id = f"{rank:02}_{methods[0]}"
            if not missing:
                skipped.append(batch_id)
                continue
            batches.append({"batch_id": batch_id, "rank": rank, "job_ids": ids,
                            "missing_job_ids": missing, "discard_job_ids": [jid for jid in ids if jid in saved]})
    missing_ids = [jid for jid in selected_ids if jid not in saved]
    _need(sorted(j for b in batches for j in b["missing_job_ids"]) == sorted(missing_ids), "planner lost or duplicated missing jobs")
    return {"worker": worker, "planned_authoritative_jobs": len(selected_ids), "existing_authoritative_jobs": len(saved),
            "missing_job_ids": missing_ids, "batches": batches, "skipped_complete_batch_ids": skipped,
            "scope": "Presence/metadata only; original pairs retained. Saved empty, capped or wrong outputs are never retried for quality."}
