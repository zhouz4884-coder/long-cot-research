"""Later gated projection of selected reference constructions without execution."""
from __future__ import annotations

import argparse
from hashlib import sha1, sha256
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COHORT_SHA = "2ef60c97ae05c2b811f873457682c8be4a650fdd9556f26c332e1203b2671617"
INTAKE_SHA = "6f2ede5fce96cf8b33740bc6dedf214267eba3684604992854969bbdf9abb368"
SOURCE_SHA = "6f38ee5f41846cadaa00a024c627a431b6e4df9ed9c67bab2be8174075e179db"
SOURCE_GIT = "1597f9cb0c5aa0739d7d7194c051bfdff46890e4"
SOURCE_BYTES = 487780
GATE_STATUS = "D49_ALL_TEN_ORDINARY_CONTROLS_FROZEN_BEFORE_REFERENCES"
SCOPE_KEYS = ("id", "question_sha256", "instruction_sha256")


def require(test, message):
    if not test:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def is_sha(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def unique_pairs(pairs):
    obj = dict(pairs)
    require(len(obj) == len(pairs), "Duplicate JSON keys")
    return obj


def load_exact(path, sha):
    require(is_sha(sha), "Invalid expected digest")
    raw = path.read_bytes()
    require(digest(raw) == sha, f"Frozen artifact differs: {path.name}")
    return json.loads(raw, object_pairs_hook=unique_pairs)


def index(rows):
    result = {row["id"]: row for row in rows}
    require(len(rows) == len(result), "Repeated cohort or gate ID")
    return result


def receipt_has_scope(receipt, expected):
    """Allow direct question binding or case ID beneath the exact cohort binding."""
    if type(receipt) is dict and receipt.get("cohort_sha256") == COHORT_SHA:
        cases = receipt.get("cases")
        entry = cases.get(expected["id"]) if type(cases) is dict else None
        if (type(entry) is dict and entry.get("question_sha256") == expected["question_sha256"]
                and entry.get("instruction_sha256", expected["instruction_sha256"]) == expected["instruction_sha256"]):
            return True
    pending = [(receipt, False)]
    while pending:
        node, cohort_bound = pending.pop()
        if isinstance(node, list):
            pending.extend((value, cohort_bound) for value in node)
        elif isinstance(node, dict):
            cohort_bound = cohort_bound or node.get("cohort_sha256") == COHORT_SHA
            cid = node.get("case_id", node.get("id", node.get("problem_id")))
            if cid == expected["id"]:
                hashes = ("question_sha256", "instruction_sha256")
                if all(node.get(key) == expected[key] for key in hashes):
                    return True
                if cohort_bound and all(key not in node or node[key] == expected[key] for key in hashes):
                    return True
            pending.extend((value, cohort_bound) for value in node.values() if isinstance(value, (list, dict)))
    return False


def verify_ordinary_gate(cohort, gate):
    require(gate["status"] == GATE_STATUS and gate["cohort_sha256"] == COHORT_SHA,
            "Ordinary controls are not explicitly frozen for this cohort")
    rows = index(cohort["rows"])
    receipts = index(gate["rows"])
    require(len(rows) == 10 and set(rows) == set(receipts), "Ordinary freeze must cover exactly ten cases")
    bound = []
    parsed = {}
    for cid, row in rows.items():
        lock = receipts[cid]
        require(all(lock[key] == row[key] for key in SCOPE_KEYS)
                and type(lock["ordinary_status"]) is str and bool(lock["ordinary_status"].strip()),
                "Exact question/instruction scope or ordinary result status differs")
        items = lock["ordinary_receipts"]
        require(type(items) is list and bool(items), "Missing actual ordinary receipt")
        linked = []
        for item in items:
            path = (ROOT / item["path"]).resolve()
            sha = item["sha256"]
            require(path.is_relative_to(ROOT.resolve()) and path.suffix == ".json" and is_sha(sha),
                    "Ordinary receipt path or digest invalid")
            key = path, sha
            if key not in parsed:
                parsed[key] = load_exact(path, sha)
            require(receipt_has_scope(parsed[key], row), "Ordinary receipt is not bound to this case")
            linked.append(sha)
        require(len(linked) == len(set(linked)), "Duplicate ordinary receipt in scope")
        bound.append({**{key: row[key] for key in SCOPE_KEYS}, "ordinary_receipt_sha256": linked})
    return rows, bound


def project_source(source, expected, key_records=None):
    """Project selected references, and optionally their separate answer keys."""
    raw = source.read_bytes()
    require(len(raw) == SOURCE_BYTES and digest(raw) == SOURCE_SHA
            and sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == SOURCE_GIT,
            "Pinned source JSONL differs")
    selected = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=unique_pairs)
        except (ValueError, RecursionError):
            raise ValueError("Malformed pinned construction row") from None
        require(type(row) is dict and type(row.get("id")) is str, "Malformed source identity")
        pid = row["id"]
        if pid not in expected:
            continue
        scope = expected[pid]
        require(pid not in selected and row["split"] == "construction"
                and row["source"] == scope["source"] and type(row["query"]) is str
                and type(row["instruction"]) is str
                and digest(row["query"].encode()) == scope["question_sha256"]
                and digest(row["instruction"].encode()) == scope["instruction_sha256"],
                "Selected reference row identity or scope changed")
        value = row.get("ref_construction")
        selected[pid] = {
            **{key: scope[key] for key in SCOPE_KEYS},
            "status": "REFERENCE_PRESENT" if value is not None else "REFERENCE_UNAVAILABLE",
            "ref_construction": value,
        }
        if key_records is not None:
            key_value = row.get("ref_answer")
            key_records[pid] = {**{key: scope[key] for key in SCOPE_KEYS},
                                "status": "KEY_PRESENT" if key_value is not None else "KEY_UNAVAILABLE",
                                "ref_answer": key_value}
    require(set(selected) == set(expected), "Pinned selected reference rows incomplete")
    return [selected[pid] for pid in expected]


def write_once(path, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return digest(raw)


def run(args):
    local = [args.output] + ([args.key_output] if args.key_output is not None else [])
    destinations = [*local, args.receipt]
    require(all(not path.exists() for path in destinations)
            and len({path.resolve() for path in destinations}) == len(destinations)
            and all(path.resolve().is_relative_to((ROOT / "outputs").resolve()) for path in local),
            "Reference output scope invalid")
    cohort = load_exact(args.cohort, COHORT_SHA)
    intake = load_exact(args.intake, INTAKE_SHA)
    require(cohort["intake_receipt_sha256"] == INTAKE_SHA
            and intake["source_assets"][0]["sha256"] == SOURCE_SHA, "Intake/source authority differs")
    gate = load_exact(args.ordinary_freeze, args.expected_ordinary_freeze_sha256)
    expected, bound = verify_ordinary_gate(cohort, gate)
    # The first access to combined JSONL bytes is after all ten ordinary gates.
    keys = {} if args.key_output is not None else None
    rows = project_source(args.source, expected, keys)
    common = {
        "cohort_sha256": COHORT_SHA, "intake_receipt_sha256": INTAKE_SHA,
        "source_construction_sha256": SOURCE_SHA, "ordinary_freeze_sha256": args.expected_ordinary_freeze_sha256,
        "projector_code_sha256": digest(Path(__file__).read_bytes()),
    }
    private_sha = write_once(args.output, {
        "status": "D49_SELECTED_REFERENCE_CONSTRUCTIONS_LOCAL_UNEXECUTED", **common, "rows": rows,
    })
    key_sha = None
    if keys is not None:
        require(set(keys) == set(expected), "Selected key rows incomplete")
        key_sha = write_once(args.key_output, {
            "status": "D49_SELECTED_REFERENCE_ANSWER_KEYS_LOCAL_UNEXECUTED",
            **common, "rows": [keys[pid] for pid in expected],
        })
    safe = [{**bound_row, "reference_status": row["status"]} for bound_row, row in zip(bound, rows)]
    return write_once(args.receipt, {
        "status": "D49_SELECTED_REFERENCE_PROJECTION_RECEIPT", **common,
        "private_reference_sha256": private_sha, "private_reference_keys_sha256": key_sha, "rows": safe,
        "scope": "Ten exact identities after ordinary receipt freeze. The raw JSONL is parsed within the trusted projector. "
                 "Selected ref_construction values and explicitly requested separate ref_answer keys are emitted locally. "
                 "No solution, rubric or verifier is emitted. "
                 "No reference expression or embedded code is executed.",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=HERE / "D49_COHORT_FREEZE.json")
    parser.add_argument("--intake", type=Path, default=HERE / "D49_COMBENCH_INTAKE_RECEIPT.json")
    parser.add_argument("--source", type=Path,
                        default=ROOT / "outputs/d49_combench_source_20261110/data/construction.jsonl")
    parser.add_argument("--ordinary-freeze", type=Path, required=True)
    parser.add_argument("--expected-ordinary-freeze-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-output", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print("D49 selected reference receipt", run(args))


if __name__ == "__main__":
    main()
