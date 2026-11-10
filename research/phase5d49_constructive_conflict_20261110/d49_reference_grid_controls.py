"""Read three post-freeze reference grids as bounded data and recheck the original constraints."""

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path

import d49_reference_literals as literals
from d49_ordinary_grid_controls import COHORT_SHA256, check_full, digest, measured, write_new


REF_SHA256 = "15b5e9c51caf3d175a55687e9650dc9eab0740ebe5774a8d6dacf49894c77b66"
KEY_SHA256 = "c308dff27a23d258ebef7cd632c34082c88695eb993ce99c31f29fcd92f9af21"
ORDINARY_SHA256 = "db06ced72444613b3b353493faa179c99e4ee9345e932bebdf0862f6d650ff1d"
STICK_LOOKUP_KEYS = {1, 3, 5, 7, 8}


def read_fixed(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("unexpected input digest")
    return json.loads(raw)


class StickLookupDecoder(literals.Decoder):
    """The one additional construct in CB-99: a fixed-key integer-map lookup."""

    def decode(self, node, names, depth=0):
        if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Dict)):
            return super().decode(node, names, depth)
        if depth > literals.MAX_DEPTH:
            raise literals.UnsupportedReference("lookup nesting limit")
        keys = node.value.keys
        if len(keys) != len(STICK_LOOKUP_KEYS) or any(
            not isinstance(key, ast.Constant) or type(key.value) is not int for key in keys
        ):
            raise literals.UnsupportedReference("lookup requires exactly five literal integer keys")
        integer_keys = [key.value for key in keys]
        if set(integer_keys) != STICK_LOOKUP_KEYS:
            raise literals.UnsupportedReference("lookup keys differ from the reviewed column set")
        self.charge(2 + len(keys))
        values = [self.bounded_integer(self.decode(value, names, depth + 1)) for value in node.value.values]
        offset = self.bounded_integer(self.decode(node.slice, names, depth + 1))
        if offset not in STICK_LOOKUP_KEYS:
            raise literals.UnsupportedReference("lookup uses an unreviewed column")
        return values[integer_keys.index(offset)]


def decode(case_id, source):
    if case_id != "CB-99":
        return literals.decode_reference(source)
    if type(source) is not str or len(source) > literals.MAX_TEXT:
        raise literals.UnsupportedReference("invalid reference source")
    decoder = StickLookupDecoder()
    result = decoder.decode(ast.parse(source, mode="eval").body, {})
    if type(result) is not list:
        raise literals.UnsupportedReference("reference must be a matrix")
    return result, decoder.visits


def min_sticks_for_even_board(size):
    return size**2 - ((size - 1) ** 2 + 4 * (size - 2)) // 2


def normalized_key(case_id, value, size):
    if case_id == "CB-46":
        if value != "(n^4-n^2)/12":
            raise ValueError("unexpected symbolic answer key")
        return {"scope": "original parameterized formula", "substitution": size, "fixed_value": (size**4 - size**2) // 12}
    if not value.isascii() or not value.isdecimal():
        raise ValueError("unexpected integer answer key")
    integer = int(value)
    if case_id == "CB-99":
        return {
            "scope": "original 2022 by 2022 board, distinct from fixed 10 by 10 witness",
            "original_size": 2022,
            "original_value": integer,
            "independent_original_value": min_sticks_for_even_board(2022),
            "fixed_value": min_sticks_for_even_board(size),
        }
    return {"scope": "same fixed original instance", "fixed_value": integer}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-constructions", required=True, type=Path)
    parser.add_argument("--answer-keys", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    phase = Path(__file__).parent
    ordinary = read_fixed(phase / "D49_GRID_ORDINARY_CONTROLS.json", ORDINARY_SHA256)
    refs = read_fixed(args.reference_constructions, REF_SHA256)
    keys = read_fixed(args.answer_keys, KEY_SHA256)
    if any(project["cohort_sha256"] != COHORT_SHA256 for project in (refs, keys)) or refs["ordinary_freeze_sha256"] != keys["ordinary_freeze_sha256"]:
        raise ValueError("reference and ordinary freeze identity mismatch")
    ref_by_id = {row["id"]: row for row in refs["rows"]}
    key_by_id = {row["id"]: row for row in keys["rows"]}
    rows = []
    for frozen in ordinary["rows"]:
        identity, case_id = frozen["id"], frozen["cb_id"]
        ref, key = ref_by_id[identity], key_by_id[identity]
        for field in ("question_sha256", "instruction_sha256"):
            if ref[field] != frozen[field] or key[field] != frozen[field]:
                raise ValueError("reference is for different question or instruction bytes")
        (grid, visits), decode_cost = measured(decode, case_id, ref["ref_construction"])
        checked, check_cost = measured(check_full, case_id, grid)
        parsed_key = normalized_key(case_id, key["ref_answer"], len(grid))
        expected = frozen["bound_certificate"]["bound"]
        exact_match = checked["valid"] and checked["objective"] == parsed_key["fixed_value"] == expected
        original_match = parsed_key.get("original_value") == parsed_key.get("independent_original_value")
        witness_sha256 = digest(grid)
        rows.append({
            "id": identity,
            "cb_id": case_id,
            "question_sha256": frozen["question_sha256"],
            "instruction_sha256": frozen["instruction_sha256"],
            "construction_payload_sha256": sha256(ref["ref_construction"].encode()).hexdigest(),
            "key_payload_sha256": sha256(key["ref_answer"].encode()).hexdigest(),
            "fixed_matrix_dimension": len(grid),
            "matrix_sha256": witness_sha256,
            "same_pointwise_matrix_as_blind_ordinary": witness_sha256 == frozen["witness_sha256"],
            "independent_full_check": checked,
            "independent_frozen_bound": expected,
            "key_normalization": parsed_key,
            "matches_independent_bound_and_relevant_key": exact_match and original_match,
            "bounded_decoder": "reviewed integer-map AST lookup extension" if case_id == "CB-99" else "shared bounded AST",
            "bounded_ast_visits": visits,
            "bounded_decode_cost": decode_cost,
            "independent_full_check_cost": check_cost,
        })
    if len(rows) != 3 or not all(row["matches_independent_bound_and_relevant_key"] for row in rows):
        raise ValueError("reference mismatch")
    write_new(args.receipt, {
        "status": "THREE_POST_FREEZE_REFERENCE_MATRICES_MATCH_INDEPENDENT_EXACT_BOUNDS",
        "frozen_cohort_sha256": COHORT_SHA256,
        "full_ordinary_freeze_sha256": refs["ordinary_freeze_sha256"],
        "independent_ordinary_control_sha256": ORDINARY_SHA256,
        "sealed_reference_projection_sha256": REF_SHA256,
        "sealed_key_projection_sha256": KEY_SHA256,
        "literal_decoder_sha256": sha256(Path(literals.__file__).read_bytes()).hexdigest(),
        "grid_reference_control_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Source expressions decoded as inert AST data only. Original grids checked by independently frozen code. No author verifier, raw model output, Python eval or reference formula execution. No raw reference payloads in this receipt.",
        "rows": rows,
    })


if __name__ == "__main__":
    main()
