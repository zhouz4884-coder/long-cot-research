"""Reconcile the frozen ten-case ordinary and reference-check denominators."""
from hashlib import sha256
import json
from pathlib import Path

from d49_controls_extremal_a import CASES, IDS, timed
from d49_project_selected_references import verify_ordinary_gate
from d49_reference_literals import decode_reference


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    cohort, cohort_sha = read(HERE / "D49_COHORT_FREEZE.json")
    freeze, freeze_sha = read(HERE / "D49_ORDINARY_FREEZE.json")
    ids, _ = verify_ordinary_gate(cohort, freeze)
    source, source_sha = read(HERE / "D49_SELECTED_REFERENCE_PROJECTION_RECEIPT.json")
    require(source["ordinary_freeze_sha256"] == freeze_sha, "Reference projection precedes ordinary freeze")
    projected, projected_sha = read(ROOT / "outputs/d49_combench_sealed_20261110/d49_selected_reference_constructions.json")
    require(projected_sha == source["private_reference_sha256"], "Selected references changed")
    refs = {row["id"]: row["ref_construction"] for row in projected["rows"]}
    all_rows = {}
    checks = (
        ("D49_REFERENCE_A.json", lambda r: r["reference_witness_check"]["status"] == "VALID"),
        ("D49_REFERENCE_B.json", lambda r: r["matches_independent_bound_and_relevant_key"]),
        ("D49_REFERENCE_PARITY_BRICKS.json", lambda r: r["independent_full_witness_valid"] and r["original_key_agrees"]),
    )
    hashes = {}
    for name, accept in checks:
        data, hashes[name] = read(HERE / name)
        for row in data["rows"]:
            key = row["id"]
            require(key not in all_rows and accept(row)
                    and all(row[k] == ids[key][k] for k in ("question_sha256", "instruction_sha256")),
                    "Independent author witness comparison differs")
            all_rows[key] = name
    name = "D49_REFERENCE_RMO.json"
    rmo, hashes[name] = read(HERE / name)
    require(rmo["ordinary_freeze_sha256"] == freeze_sha and rmo["fixed_reference_witness"]["reference_valid"]
            and rmo["case_id"] not in all_rows
            and all(rmo[k] == ids[rmo["case_id"]][k] for k in ("question_sha256", "instruction_sha256")),
            "RMO reference does not match the fixed task")
    all_rows[rmo["case_id"]] = name
    require(set(all_rows) == set(ids), "Expected nine extrema and one fixed feasibility task")
    # The four A checks are also independently rerun here on the decoded data.
    authored, _ = read(HERE / "D49_REFERENCE_A.json")
    a_rows = {r["id"]: r for r in authored["rows"]}
    for cid, (_, checker, _, _) in zip(IDS, CASES, strict=True):
        witness, _ = decode_reference(refs[cid])
        validation, _ = timed(checker, witness)
        require(validation == a_rows[cid]["reference_witness_check"], "Reference replay disagrees")
    summary = {
        "status": "D49_CONSTRUCTIVE_CPU_ADMISSION_COMPLETE_NO_GO",
        "cohort_sha256": cohort_sha, "ordinary_freeze_sha256": freeze_sha,
        "reference_projection_receipt_sha256": source_sha, "comparison_receipts": hashes,
        "independent_fixed_questions": len(ids), "ordinary_complete_and_verified": 10,
        "optima_proven": 9, "feasibility_only_complete": 1,
        "author_reference_witnesses_verified": len(all_rows), "reference_witness_conflicts": 0,
        "archive_model_runs_acquired": 0, "new_gpu_calls": 0,
        "required_independent_residuals": 2, "observed_independent_residuals": 0,
        "admitted_to_native_generation": False, "admitted_to_model_repair": False,
        "rows": [{"id": cid, "reference_receipt": name} for cid, name in sorted(all_rows.items())],
        "scope": "Ordinary structured controls cover each published fixed construction scope. "
                 "Proof-discovery time, generalization to novel sizes, and model accuracy were not measured.",
    }
    raw = (json.dumps(summary, indent=2) + "\n").encode()
    with (HERE / "D49_RESULTS.json").open("xb") as stream:
        stream.write(raw)
    print(sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
