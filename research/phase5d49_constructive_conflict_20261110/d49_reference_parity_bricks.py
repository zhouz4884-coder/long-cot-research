"""Compare only the two authorized author constructions with independent checks."""
from hashlib import sha256
import json
from pathlib import Path

from d49_controls_parity_bricks import (
    BRICK_ID, PARITY_ID, measure, parity_analysis, verify_bricks, verify_bricks_voxels,
)
from d49_reference_literals import decode_reference


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCAL = ROOT / "outputs/d49_combench_sealed_20261110"


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def canonical_hash(data):
    return sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def brick_endpoints_to_slots(ends, n):
    slots = []
    for pair in ends:
        if type(pair) not in (list, tuple) or len(pair) != 2 or any(
            type(end) not in (list, tuple) or len(end) != 3 for end in pair
        ):
            raise ValueError("Malformed author brick endpoint")
        p, q = pair
        if not all(type(x) is int and 1 <= x <= n for x in (*p, *q)):
            raise ValueError("Author brick endpoint outside fixed cube")
        moved = [i for i in range(3) if p[i] != q[i]]
        if len(moved) != 1 or {p[moved[0]], q[moved[0]]} != {1, n}:
            raise ValueError("Author brick does not span one full axis")
        axis = moved[0]
        slots.append((axis, *(p[i] - 1 for i in range(3) if i != axis)))
    return slots


def main():
    seal, seal_sha = read(HERE / "D49_SELECTED_REFERENCE_PROJECTION_RECEIPT.json")
    refs, refs_sha = read(LOCAL / "d49_selected_reference_constructions.json")
    keys, keys_sha = read(LOCAL / "d49_selected_answer_keys.json")
    if refs_sha != seal["private_reference_sha256"] or keys_sha != seal["private_reference_keys_sha256"]:
        raise ValueError("Reference projection hash differs")
    cases = (PARITY_ID, BRICK_ID)
    constructions = {row["id"]: row for row in refs["rows"] if row["id"] in cases}
    answer_keys = {row["id"]: row for row in keys["rows"] if row["id"] in cases}
    expected = {row["id"]: row for row in seal["rows"] if row["id"] in cases}
    if set(constructions) != set(cases) or set(answer_keys) != set(cases) or set(expected) != set(cases):
        raise ValueError("Authorized reference comparison denominator differs")
    pre, pre_sha = read(HERE / "D49_ORDINARY_PARITY_BRICKS_PRE_REFERENCE.json")
    output = []
    for cid in cases:
        ref, key = constructions[cid], answer_keys[cid]
        for field in ("question_sha256", "instruction_sha256"):
            if ref[field] != key[field] or ref[field] != expected[cid][field]:
                raise ValueError("Reference has different mathematical scope")
        text = ref["ref_construction"]
        (data, visits), decode_time = measure(lambda: decode_reference(text))
        frozen_value = pre["cases"][cid]["complete_fixed_instance"]["value"]
        if cid == PARITY_ID:
            result, verify_time = measure(lambda: parity_analysis(data, 101))
            value = result.get("maximum_even_for_this_board")
            key_ok = ("n^2-n+1" in key["ref_answer"] and "even" in key["ref_answer"]
                      and "odd" in key["ref_answer"])
            key_scope = "Both original parity families. The odd formula evaluated at 101 matches the fixed score."
            extra = {}
        else:
            data = brick_endpoints_to_slots(data, 20)
            result, verify_time = measure(lambda: verify_bricks(data, 20))
            (valid, voxel_work), voxel_time = measure(lambda: verify_bricks_voxels(data, 20))
            value = result.get("brick_count")
            if not valid:
                raise ValueError("Author brick witness fails independent voxel check")
            key_ok = key["ref_answer"].strip() == str(3 * 2020 // 2)
            key_scope = "Original width 2020 key. Fixed width 20 is scored against the independently proved minimum."
            extra = {"voxel_check_named_work": voxel_work, "voxel_check_time": voxel_time}
        if result["status"] != "COMPLETE_FEASIBLE" or value != frozen_value or not key_ok:
            raise ValueError("Author construction or original key differs from the independent proof")
        output.append({"id": cid, "question_sha256": ref["question_sha256"],
                       "instruction_sha256": ref["instruction_sha256"],
                       "author_expression_sha256": sha256(text.encode()).hexdigest(),
                       "author_key_sha256": canonical_hash(key["ref_answer"]),
                       "materialized_data_sha256": canonical_hash(data), "bounded_decoder_visits": visits,
                       "decode_time": decode_time, "checker_named_work": result["named_work"],
                       "checker_time": verify_time, "fixed_objective": value, "original_key_agrees": key_ok,
                       "independent_full_witness_valid": True, "original_key_scope": key_scope, **extra})
    result = {"status": "D49_PARITY_BRICK_AUTHOR_WITNESSES_CHECKED_WITHOUT_SOURCE_EXECUTION",
              "projection_receipt_sha256": seal_sha, "ordinary_pre_reference_sha256": pre_sha,
              "decoder_source_sha256": sha256((HERE / "d49_reference_literals.py").read_bytes()).hexdigest(),
              "audit_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "rows": output}
    raw = (json.dumps(result, indent=2) + "\n").encode()
    with (HERE / "D49_REFERENCE_PARITY_BRICKS.json").open("xb") as stream:
        stream.write(raw)
    print(sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
