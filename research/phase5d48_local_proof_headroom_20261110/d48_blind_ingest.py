"""Verify HMMT/MathArena identities and materialize only frozen, separated channels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest, sha256
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COHORT_SHA = "622e581c19323b1089f3fa1716ee130579edabede1200f20138eea38e82f84cd"
CODE_REVISION = "d98156fa67822629b7554faabeeea5682f4ad0ca"
MODEL_KEY = ("QED-Nano", "other/qed-nano")
DRAW = 0
IDENTITY_COLUMNS = ("problem_idx", "problem", "model_name", "model_config", "idx_answer", "source")
TRAJECTORY_COLUMNS = (*IDENTITY_COLUMNS, "all_messages", "input_tokens", "output_tokens")
BLOCKED_COLUMNS = {"answer", "gold_answer", "parsed_answer", "correct", "user_message"}
ARCHIVES = {
    2025: {
        "revision": "e3fb6c74f24eabf83413eb9e62b9816c1f3f7d2e", "bytes": 163542911,
        "sha256": "afb629b9ff576f74426acab054b2036244ba539ebaacfd118bb923163619822a",
        "rows": 7680, "row_groups": 5,
        "readme_sha256": "465d079c3b142a0cf4f4fe2533041c64792f8775aff9bc478872d9a19fdcf29c",
        "official_pdf_sha256": "ee5ce8e248dc4edae912ed0449dc4d504020d59ed914c806894d15f8fab9312b",
        "question_repository_revision": "6fdc4277120810ff75aa22d2d5489b91f7a262a1",
        "question_shard_sha256": "ccca64d248b89dc0765e40b893fe4ebeab242226a4336027d95d256886a3d5f2",
    },
    2026: {
        "revision": "4523bd2724d5da98d36b89b1609b839cbc03ef00", "bytes": 113581005,
        "sha256": "763eeb014e9e6d6370dce512ab99754af7cb575cee9c18e2c9fc61e5a0761ca1",
        "rows": 3783, "row_groups": 3,
        "readme_sha256": "5cb1a5cda54544ca7e05b5abb37eea1bd1f3585d667b3dd806c70f95fd836484",
        "official_pdf_sha256": "c5b8d47964e0b6bcae46659e8de4e08522615ea4037deca2a632983485b1d7b0",
        "question_repository_revision": "589a53fe152febc0f4f99f3e561007bf8da8e664",
        "question_shard_sha256": "0b66a6f02933030bec1785e1e6284eeb633bb101267418b4bc12b5091ed829cb",
    },
}
# Reviewed join from question-only projection against original printed questions.
# Exact archive hashes bind the rendered problem. PDF bytes bind original notation.
JOINS = {
    2025: {
        "13": (3, "2512a9ba7a4b5924072fda32d58679cb573f9cdebefdd7878ac8469513853b2f",
               "74d136f74045c8ac58fda8b3d9c4366caa2d6e6f99eeec5e5d00637f0e514a27"),
        "15": (5, "e103f900aaa1d05ff2d7aa86d29e62fc24a18bddfbf6556997579dbbb90f574f",
               "7f0c55a1fa63ae08a6cec3e8aeb0f4410aaa05b603de71978ce31cfac4025c7b"),
        "17": (7, "a6f7b1426ac39584abbcb998eea20719b2d37315f92aa7f644e2c16f040d4b09",
               "16162bba9ff3a5b627c8240e65e4561b955280dafba6a3267e24ac9e64265da8"),
        "18": (8, "7d2bf8a412c891a5bc37646321515d86fb52f69903e680b62e7f701f52b184fe",
               "66868f32b85baec4f3a52a6b08fab962b596094c755a9774ba75481dcdb13d39"),
        "20": (10, "caaa8d40dff4a94a699189b71926eb5930da8d7e834ee43fd3e14f94de417bab",
               "4d57e918182f59053bff81a89b0199b13495af683935939669a6d5ab46ef75eb"),
    },
    2026: {
        "15": (5, "d5652e9c1bf4b499aab12a4fbe8133a4115762691e4283c96c38becfbec5845a",
               "82afbc5e3d91908c404dc9e92f31a559377287feb1d669bad4159b6f0cc9937c"),
        "17": (7, "faf89d6047e00132d5692428048fdec17465fa0d564e4fd7f087c91a64cbacd9",
               "bf6cc13533542d551aa5b9801537f0d44dfdd3dec5e9e42947d44ae0f0d5c15e"),
        "19": (9, "443a38bf63cd2c58a3dcca86f87155d9da3b529941ac3f84649d99324d51779d",
               "0b3aa305fb1d0b997f83adcbafbe6419950bd44bfc3d0f2e80605beccf8dc1b4"),
        "20": (10, "82b776d1d7c370b9a31408efaabc4eb57db890d62f4dda439e09d8c5860e7f36",
               "8e7dff8a5e7ee7253d159d37043c5fe37574260d2913c148961bfa3058d2a2b5"),
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def wire(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = wire(data)
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def case_id(year, idx):
    return f"HMMT-{year}-FEB-COMB-P{JOINS[year][idx][0]:02d}"


def check_cohort(path, original):
    raw = path.read_bytes()
    require(digest(raw) == COHORT_SHA, "Question-only cohort hash differs")
    cohort = json.loads(raw)
    wanted = {case_id(year, idx) for year in JOINS for idx in JOINS[year]}
    require({cid for cid, admitted, _ in cohort["rows"] if admitted} == wanted, "Changed selected question IDs")
    for year, archive in ARCHIVES.items():
        h = digest((original / f"{year}-comb-problems.pdf").read_bytes())
        require(h == archive["official_pdf_sha256"] == cohort["sources"][str(year)]["sha256"],
                "Original problem PDF hash differs")


def _verified_stream(raw_dir, year):
    path = raw_dir / f"hmmt_feb_{year}_outputs.parquet"
    stream = path.open("rb")
    try:
        asset = ARCHIVES[year]
        require(path.stat().st_size == asset["bytes"]
                and file_digest(stream, "sha256").hexdigest() == asset["sha256"], "Archive asset differs")
        stream.seek(0)
        return stream
    except Exception:
        stream.close()
        raise


def _rows(raw_dir, year, columns, *, model=None, gold=False):
    import pyarrow.parquet as pq

    allowed = set(TRAJECTORY_COLUMNS) | ({"gold_answer"} if gold else set())
    forbidden = BLOCKED_COLUMNS - ({"gold_answer"} if gold else set())
    require(set(columns) <= allowed and not set(columns) & forbidden, "Unexpected or blocked archive column")
    require(not gold or model is not None, "Gold projection requires a frozen exact model")
    filters = [("problem_idx", "in", sorted(JOINS[year])), ("idx_answer", "=", DRAW)]
    if model is not None:
        filters += [("model_name", "=", model[0]), ("model_config", "=", model[1])]
    with _verified_stream(raw_dir, year) as stream:
        footer = pq.ParquetFile(stream).metadata
        asset = ARCHIVES[year]
        require(footer.num_rows == asset["rows"] and footer.num_row_groups == asset["row_groups"],
                "Archive footer shape differs")
        stream.seek(0)
        rows = pq.read_table(stream, columns=list(columns), filters=filters, use_threads=False).to_pylist()
    for row in rows:
        idx = row["problem_idx"]
        require(idx in JOINS[year] and row["idx_answer"] == DRAW and set(row) == set(columns)
                and (model is None or (row["model_name"], row["model_config"]) == model),
                "Projection returned an unauthorized identity")
        require(type(row["problem"]) is str and digest(row["problem"].encode()) == JOINS[year][idx][1],
                "Exact archive question hash differs from the reviewed question join")
    return rows


def method_receipt(cohort, original, raw_dir):
    check_cohort(cohort, original)
    availability = {}
    complete = []
    for year in ARCHIVES:
        rows = _rows(raw_dir, year, IDENTITY_COLUMNS)
        groups = defaultdict(set)
        for row in rows:
            key = row["model_name"], row["model_config"]
            require(all(type(value) is str and value for value in key), "Malformed model identity")
            require(row["problem_idx"] not in groups[key], "Duplicate model, problem and draw")
            groups[key].add(row["problem_idx"])
        availability[str(year)] = {
            "identity_rows": len(rows), "model_keys": [
                {"model_name": k[0], "model_config": k[1], "covered_problem_indices": sorted(groups[k])}
                for k in sorted(groups)],
        }
        complete.append({key for key, indices in groups.items() if indices == set(JOINS[year])})
    common = set.intersection(*complete)
    require(MODEL_KEY in common, "Predeclared fallback lacks complete exact coverage")
    require(not any("qwen3-8b" in key[0].casefold() for key in common),
            "Preferred model became available; re-freeze policy")
    code_sha = digest(Path(__file__).read_bytes())
    return {
        "status": "D48_DRAW0_QED_NANO_MODEL_AND_METHOD_FROZEN_BEFORE_MESSAGES",
        "cohort_sha256": COHORT_SHA, "ingest_code_sha256": code_sha,
        "archive_assets": ARCHIVES, "archive_license": "CC-BY-NC-SA-4.0",
        "source_terms": "HMMT retains rights to official documents. Publish source URLs, hashes and derived statistics; keep raw material local.",
        "question_joins": [
            {"case_id": case_id(year, idx), "year": year, "problem_idx": idx,
             "archive_problem_sha256": values[1], "original_pdf_text_extract_sha256": values[2],
             "statement_review": "Literal mathematics matched to original printed question; no problem-specific diagram supplied."}
            for year in JOINS for idx, values in JOINS[year].items()
        ],
        "original_text_extraction": "PyMuPDF page get_text(sort=True), join with LF, drop copyright lines, "
                                    "split by the numbered item and strip outer whitespace.",
        "projected_identity_columns": list(IDENTITY_COLUMNS),
        "projected_trajectory_columns": list(TRAJECTORY_COLUMNS),
        "blocked_archive_columns": sorted(BLOCKED_COLUMNS),
        "identity_availability": availability,
        "complete_common_model_keys": [{"model_name": k[0], "model_config": k[1]} for k in sorted(common)],
        "selection": {
            "model_name": MODEL_KEY[0], "model_config": MODEL_KEY[1], "draw_index": DRAW,
            "rationale": "No exact common Qwen3-8B or Qwen-named configuration. The smallest documented common "
                         "open reasoning model is QED-Nano, a 4B Qwen3-4B-Thinking-2507 derivative. "
                         "Select by exact presence and documented total parameters before reading responses.",
            "model_card": "https://huggingface.co/lm-provers/QED-Nano/blob/80845b62165499d193c7fcef76fe9b1114fe30ad/README.md",
        },
        "reference_config": {
            "github_commit": CODE_REVISION, "path": "configs/models/other/qed-nano.yaml",
            "sha256": "c564b089039e4a71776f5e17bb35f05dcc6c96c8e7920df4f721b3473fc8540f",
            "model": "lm-provers/QED-Nano", "api": "custom", "max_tokens": 120000,
            "temperature": 0.6, "top_p": 0.95,
            "scope": "Current pinned repository reference, not row-bound historical checkpoint, provider revision or decoding.",
        },
        "archival_scope": "Keep model-year strata separate. Neither archive has a dedicated finish_reason, sampled stop "
                          "ID or token-state column. The current publisher's API client can keep cot or summary "
                          "messages while logging provider finish reasons separately. This is archive text evidence, "
                          "not proof of native EOS, exact resume, historical model equivalence or complete reasoning.",
        "api_client_reference": {
            "github_commit": CODE_REVISION, "path": "src/matharena/api_client.py",
            "sha256": "939d33b754974f594eacb472c8ad7721d6ba52467d0db84f4f3af232d29b7fa7",
        },
    }


def _unique_pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON keys")
    return result


def _finish(message):
    reasons = [message[key] for key in ("finish_reason", "stop_reason") if key in message]
    if not reasons or any(type(reason) is not str for reason in reasons):
        return "UNKNOWN", []
    classes = {
        "stop": "EXPLICIT_PROVIDER_STOP", "end_turn": "EXPLICIT_PROVIDER_STOP",
        "stop_sequence": "EXPLICIT_PROVIDER_STOP", "length": "EXPLICIT_CAP", "max_tokens": "EXPLICIT_CAP",
        "max_output_tokens": "EXPLICIT_CAP", "content_filter": "EXPLICIT_FILTER", "refusal": "EXPLICIT_FILTER",
        "safety": "EXPLICIT_FILTER", "tool_calls": "EXPLICIT_TOOL_STOP", "function_call": "EXPLICIT_TOOL_STOP",
    }
    normalized = [reason.casefold() for reason in reasons]
    kinds = {classes.get(reason, "UNKNOWN") for reason in normalized}
    if len(kinds) != 1 or "UNKNOWN" in kinds:
        return "UNKNOWN", []
    return next(iter(kinds)), normalized


def separate(messages_json, problem):
    """Return only source-derived channel strings and explicitly bounded metadata."""
    empty = {"thinking": None, "final": None, "reasoning_kind": "UNAVAILABLE", "finish": "UNKNOWN",
             "provider_finish_reasons": [], "prompt_binding": "UNKNOWN"}
    if type(messages_json) is not str or len(messages_json) > 3_000_000:
        return {**empty, "status": "INVALID_MESSAGE_CONTAINER"}
    try:
        messages = json.loads(messages_json, object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError):
        return {**empty, "status": "INVALID_MESSAGE_JSON"}
    if not isinstance(messages, list) or not messages or any(type(m) is not dict for m in messages):
        return {**empty, "status": "INVALID_MESSAGE_LAYOUT"}
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if (len(users) != 1 or any(m.get("role") not in {"system", "developer"} for m in messages[:users[0]])
            or any(m.get("role") != "assistant" or m.get("tool_calls") or m.get("function_call")
                   for m in messages[users[0] + 1:])):
        return {**empty, "status": "NON_SINGLE_REQUEST_OR_TOOL_TRANSCRIPT"}
    prompt = messages[users[0]].get("content")
    if type(prompt) is str and problem.strip() in prompt:
        binding = "EXACT_PROBLEM_IN_PROMPT"
    elif type(prompt) is str and " ".join(problem.split()) in " ".join(prompt.split()):
        binding = "WHITESPACE_NORMALIZED_PROBLEM_IN_PROMPT"
    else:
        return {**empty, "status": "PROMPT_QUESTION_UNBOUND"}
    assistant = messages[users[0] + 1:]
    cot = [m.get("content") for m in assistant if m.get("type") == "cot"]
    visible = [m for m in assistant if m.get("type") in (None, "response")]
    if (len(visible) != 1 or not assistant or visible[0] is not assistant[-1]
            or len(cot) + len(visible) != len(assistant)
            or type(visible[0].get("content")) is not str or any(type(part) is not str for part in cot)):
        return {**empty, "status": "AMBIGUOUS_ASSISTANT_CHANNELS", "prompt_binding": binding}
    terminal = visible[0]
    text = terminal["content"]
    native = [terminal[k] for k in ("reasoning_content", "reasoning")
              if type(terminal.get(k)) is str and terminal[k].strip()]
    details = terminal.get("reasoning_details")
    summary = False
    if isinstance(details, list):
        for detail in details:
            if type(detail) is dict and detail.get("type") == "reasoning.text" and type(detail.get("text")) is str:
                if detail["text"].strip():
                    native.append(detail["text"])
            elif type(detail) is dict and detail.get("type") == "reasoning.summary":
                summary = True
    native = list(dict.fromkeys(native))
    if text.startswith("<think>") and text.count("<think>") == text.count("</think>") == 1 and not cot and not native:
        thinking, final = text[len("<think>"):].split("</think>", 1)
        reasoning_kind = "INLINE_EXPLICIT_THINK_DELIMITERS"
    elif "<think>" in text or "</think>" in text:
        return {**empty, "status": "AMBIGUOUS_OR_UNCLOSED_INLINE_CHANNEL", "prompt_binding": binding}
    else:
        final = text
        if len(native) == 1 and not summary and (not cot or cot == native):
            thinking, reasoning_kind = native[0], "RECORDED_EXPLICIT_REASONING_TEXT_FIELD"
        elif native and (len(native) != 1 or summary or cot != native):
            return {**empty, "status": "AMBIGUOUS_OR_MIXED_REASONING_FIELDS", "prompt_binding": binding}
        elif len(cot) == 1 and cot[0].strip():
            thinking = cot[0]
            reasoning_kind = "RECORDED_REASONING_SUMMARY" if summary else "ARCHIVE_COT_POSSIBLY_SUMMARY"
        elif len(cot) > 1:
            return {**empty, "status": "MULTIPLE_UNJOINED_COT_CHUNKS", "prompt_binding": binding}
        else:
            thinking, reasoning_kind = None, "NO_VISIBLE_REASONING_CHANNEL"
    finish, reasons = _finish(terminal)
    return {"status": "SEPARATED_SOURCE_CHANNELS", "thinking": thinking, "final": final,
            "reasoning_kind": reasoning_kind, "prompt_binding": binding, "finish": finish,
            "provider_finish_reasons": reasons}


def _method(path, expected):
    raw = path.read_bytes()
    require(digest(raw) == expected, "External method freeze hash differs")
    method = json.loads(raw)
    require(method["status"] == "D48_DRAW0_QED_NANO_MODEL_AND_METHOD_FROZEN_BEFORE_MESSAGES"
            and method["cohort_sha256"] == COHORT_SHA and method["ingest_code_sha256"] == digest(Path(__file__).read_bytes())
            and method["selection"]["model_name"] == MODEL_KEY[0]
            and method["selection"]["model_config"] == MODEL_KEY[1]
            and method["selection"]["draw_index"] == DRAW, "Method or model freeze differs")
    return method


def _sample(year, row):
    key = [year, ARCHIVES[year]["revision"], row["problem_idx"], *MODEL_KEY, DRAW]
    return {"case_id": case_id(year, row["problem_idx"]), "year": year, "problem_idx": row["problem_idx"],
            "model_name": MODEL_KEY[0], "model_config": MODEL_KEY[1], "draw_index": DRAW,
            "archive_revision": ARCHIVES[year]["revision"], "sample_uid": digest(wire(key)),
            "archive_problem_sha256": JOINS[year][row["problem_idx"]][1]}


def _selected(raw_dir, year, columns, *, gold=False):
    rows = _rows(raw_dir, year, columns, model=MODEL_KEY, gold=gold)
    require(len(rows) == len(JOINS[year]) and {row["problem_idx"] for row in rows} == set(JOINS[year]),
            "Exact frozen model/draw does not cover the cohort uniquely")
    return sorted(rows, key=lambda row: int(row["problem_idx"]))


def _private(path):
    require(path.resolve().is_relative_to((ROOT / "outputs").resolve()), "Payload must stay in local outputs")


def project(raw_dir, method, expected_method_sha, thinking_path, final_path, receipt_path):
    _method(method, expected_method_sha)
    _private(thinking_path)
    _private(final_path)
    require(len({p.resolve() for p in (thinking_path, final_path, receipt_path)}) == 3
            and all(not path.exists() for path in (thinking_path, final_path, receipt_path)), "Output already exists or collides")
    shared = {"method_sha256": expected_method_sha, "cohort_sha256": COHORT_SHA, "draw_index": DRAW}
    thinking, final, public = [], [], []
    for year in ARCHIVES:
        for row in _selected(raw_dir, year, TRAJECTORY_COLUMNS):
            sample = _sample(year, row)
            channels = separate(row["all_messages"], row["problem"])
            meta = {k: value for k, value in channels.items() if k not in {"thinking", "final"}}
            meta.update({"exact_native_eos_proven": False, "archive_conversation_sha256": digest(row["all_messages"].encode())
                         if type(row["all_messages"]) is str else None,
                         "recorded_input_tokens": row["input_tokens"], "recorded_output_tokens": row["output_tokens"]})
            thinking.append({**sample, **meta, "question": row["problem"], "reasoning_text": channels["thinking"]})
            final.append({**sample, "status": channels["status"], "finish": channels["finish"],
                          "prompt_binding": channels["prompt_binding"], "final_text": channels["final"]})
            public.append({**sample, **meta, "reasoning_available": channels["thinking"] is not None,
                           "final_available": channels["final"] is not None})
    t_sha = save(thinking_path, {"status": "D48_LOCAL_REASONING_ONLY_BLIND", **shared, "rows": thinking})
    f_sha = save(final_path, {"status": "D48_LOCAL_FINAL_ONLY_SEALED", **shared, "rows": final})
    result = {"status": "D48_DRAW0_CHANNELS_SEPARATED_WITHOUT_GOLD", **shared, "rows": public,
              "reasoning_local_sha256": t_sha, "final_local_sealed_sha256": f_sha,
              "separation_counts": dict(Counter(row["status"] for row in public)),
              "finish_counts": dict(Counter(row["finish"] for row in public)),
              "reasoning_kind_counts": dict(Counter(row["reasoning_kind"] for row in public)),
              "scope": "Only fixed cohort and draw 0. Reviewers receive reasoning channel and original question only. "
                       "Intermediate claimed answers within the source reasoning remain visible. Final channel is separate."}
    return save(receipt_path, result)


def gold_only(raw_dir, method, method_sha, outcomes, outcomes_sha, output):
    """Prepare a distinct, explicitly hash-gated later operation. Never used by project."""
    _method(method, method_sha)
    _private(output)
    raw = outcomes.read_bytes()
    require(digest(raw) == outcomes_sha and not output.exists(), "External outcome freeze differs")
    frozen = json.loads(raw)
    require(frozen["status"] == "D48_BLIND_LOCAL_CHECKS_AND_FINAL_READOUT_FROZEN_BEFORE_GOLD"
            and frozen["method_sha256"] == method_sha and len(frozen["sample_uids"]) == 9
            and len(set(frozen["sample_uids"])) == 9, "Blind checks and final readouts must be frozen first")
    expected = set(frozen["sample_uids"])
    require(expected == {_sample(year, {"problem_idx": idx})["sample_uid"] for year in JOINS for idx in JOINS[year]},
            "Blind outcome freeze differs from exact archive sample set")
    rows = []
    columns = (*IDENTITY_COLUMNS, "gold_answer")
    for year in ARCHIVES:
        for row in _selected(raw_dir, year, columns, gold=True):
            sample = _sample(year, row)
            require(sample["sample_uid"] in expected and type(row["gold_answer"]) is str,
                    "Gold row identity or type differs")
            rows.append({**sample, "gold_answer": row["gold_answer"]})
    require({row["sample_uid"] for row in rows} == expected, "Gold projection identity differs")
    return save(output, {"status": "D48_PRIVATE_GOLD_ONLY", "method_sha256": method_sha,
                         "blind_outcomes_sha256": outcomes_sha, "rows": rows})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    defaults = ROOT / "outputs/d48_matharena_raw_20261110"
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--raw", type=Path, default=defaults)
    freeze.add_argument("--cohort", type=Path, default=HERE / "D48_QUESTION_FREEZE.json")
    freeze.add_argument("--original", type=Path, default=ROOT / "outputs/d48_hmmt_original_local_20261110")
    freeze.add_argument("--output", type=Path, required=True)
    response = commands.add_parser("project")
    gold = commands.add_parser("gold-only")
    for child in (response, gold):
        child.add_argument("--raw", type=Path, default=defaults)
        child.add_argument("--method", type=Path, required=True)
        child.add_argument("--expected-method-sha256", required=True)
    for name in ("thinking", "final", "receipt"):
        response.add_argument("--" + name, type=Path, required=True)
    gold.add_argument("--outcomes", type=Path, required=True)
    gold.add_argument("--expected-outcomes-sha256", required=True)
    gold.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        require(not args.output.exists(), "Existing method receipt is immutable")
        sha = save(args.output, method_receipt(args.cohort, args.original, args.raw))
    elif args.command == "project":
        sha = project(args.raw, args.method, args.expected_method_sha256, args.thinking, args.final, args.receipt)
    else:
        sha = gold_only(args.raw, args.method, args.expected_method_sha256, args.outcomes,
                        args.expected_outcomes_sha256, args.output)
    print(args.command, "receipt_sha256", sha)


if __name__ == "__main__":
    main()
