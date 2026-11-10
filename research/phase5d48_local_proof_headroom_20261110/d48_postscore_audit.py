"""Independent ordinary-label comparison and non-gating late failure controls."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter_ns, thread_time_ns

from d48_final_readout import exact
from d48_ordinary_c10 import directed_step


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEALED = ROOT / "outputs/d48_matharena_sealed_20261110"


def digest(raw):
    return sha256(raw.encode() if type(raw) is str else raw).hexdigest()


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), digest(raw)


def anchor(text, start, stop):
    if not 0 <= start < stop <= len(text):
        raise ValueError("Archived postscore anchor out of bounds")
    return {"span": [start, stop], "source_excerpt_sha256": digest(text[start:stop])}


def adjacent_pair_cut():
    # A bisector points between vertices 0 and 1. Dot products strictly
    # decrease with angular distance on [0, pi]. Units are half a vertex step.
    angles = [min(abs(2 * i - 1), 20 - abs(2 * i - 1)) for i in range(10)]
    selected = [i for i, distance in enumerate(angles) if distance < 2]
    if selected != [0, 1]:
        raise AssertionError("Wrong strict half-step separation")
    return {"selected_a_layer_indices_zero_based": selected, "b_layer_empty": True,
            "angular_distance_half_step_units": angles,
            "integer_cut_between_distance_ranks": 2,
            "relation": "The odd nontrivial vertex-centred cuts miss this two-element legal cut.",
            "named_work": {"exact_rank_vertex_checks": 10, "separate_layer_threshold_arguments": 1}}


def two_lap_path():
    width = 20
    first, second = [], []
    for x in range(width):
        first.extend((x, y) for y in ((2, 1) if x == width - 1 else (2,)))
        if x == width - 1:
            second.append((x, 0))
        else:
            second.extend((x, y) for y in ((1, 0) if x % 2 == 0 else (0, 1)))
    path = first + second
    if len(path) != 60 or len(set(path)) != 60 or path[0][1] != 2 or path[-1][1] != 0:
        raise AssertionError("Wrong length, vertex set or endpoints")
    if not all(0 <= x < width and 0 <= y <= 2 for x, y in path):
        raise AssertionError("Invalid vertex")
    edges = tuple(zip(path, path[1:]))
    if not all(directed_step(a, b, width) for a, b in edges):
        raise AssertionError("Invalid directed edge")
    horizontal = sum(a[1] == b[1] for a, b in edges)
    if horizontal != 39:
        raise AssertionError("Expected two horizontal sweeps")
    return {"path_sha256": digest(json.dumps(path, separators=(",", ":"))), "horizontal_steps": horizontal,
            "vertical_steps": len(edges) - horizontal, "start": path[0], "finish": path[-1],
            "named_work": {"distinct_vertices": 60, "vertex_range_checks": 60, "directed_edges": 59}}


def measured(fn):
    wall, cpu = perf_counter_ns(), thread_time_ns()
    out = fn()
    return {**out, "wall_ns": perf_counter_ns() - wall, "thread_cpu_ns": thread_time_ns() - cpu}


def ordinary_values():
    values = {}
    old, _ = load(HERE / "D48_ORDINARY_2025_FREEZE.json")
    for row in old["rows"]:
        values[row["case_id"]] = row["ordinary_complete"]["result"]["answer"]
    new, _ = load(HERE / "D48_ORDINARY_HMMT_2026_CONTROLS.json")
    for row in new["rows"]:
        result = row["ordinary_short_complete"]
        values[row["case_id"]] = str(result.get("value", result.get("side_subsets_including_empty_and_full")))
    both, _ = load(HERE / "D48_ORDINARY_C10_PRE_GOLD.json")
    values["HMMT-2025-FEB-COMB-P10"] = both["2025-P10"]["answer"]
    values["HMMT-2026-FEB-COMB-P10"] = str(both["2026-P10"]["closed_form"]["answer"])
    return values


def main():
    scores, score_sha = load(HERE / "D48_ARCHIVE_SCORES.json")
    blind, blind_sha = load(HERE / "D48_BLIND_OUTCOME_FREEZE.json")
    archived, archive_sha = load(ROOT / "outputs/d48_matharena_blind_20261110/d48_reasoning_only.json")
    final, final_sha = load(SEALED / "d48_final_only.json")
    official, official_sha = load(SEALED / "d48_official_reference.json")
    _, channels_sha = load(HERE / "D48_MATHARENA_CHANNEL_RECEIPT.json")
    if not (blind_sha == scores["blind_outcomes_sha256"] == official["blind_outcomes_sha256"]
            and archive_sha == blind["blind_input_sha256"] and channels_sha == blind["archive_channels_sha256"]
            and official_sha == scores["official_reference_manifest_sha256"]):
        raise ValueError("Postscore inputs are not attached to the frozen study")
    channels, _ = load(HERE / "D48_MATHARENA_CHANNEL_RECEIPT.json")
    if final_sha != channels["final_local_sealed_sha256"]:
        raise ValueError("Final channel differs from its seal")
    thinking = {r["case_id"]: r["reasoning_text"] for r in archived["rows"]}
    delivery = {r["case_id"]: r["final_text"] for r in final["rows"]}
    controls = ordinary_values()
    labels = {r["case_id"]: r["value"] for r in official["rows"]}
    if set(controls) != set(labels) or len(labels) != 9:
        raise ValueError("Different ordinary and official denominators")
    agreement = {}
    for case, value in controls.items():
        ordinary, target = exact(value)[0], exact(labels[case])[0]
        agreement[case] = ordinary is not None and ordinary == target
    if not all(agreement.values()):
        raise ValueError("Ordinary structural solution and official label disagree")

    wrong = {r["case_id"] for r in scores["rows"] if r["archive_last_box_matches_official_reference"] is False}
    snake, prism, path = "HMMT-2025-FEB-COMB-P10", "HMMT-2026-FEB-COMB-P07", "HMMT-2026-FEB-COMB-P10"
    if wrong != {snake, prism, path}:
        raise ValueError("Wrong-answer case identities differ")
    rows = [
        {"case_id": snake, "mechanism": "LATE_GUESS_WITHOUT_VALID_COMPLETE_EXPECTATION",
         "thinking_tail": anchor(thinking[snake], 278533, len(thinking[snake])),
         "final": anchor(delivery[snake], 0, len(delivery[snake])),
         "counterexample": None,
         "ordinary_control": "Cubic gap potential with bounded stopped expectation."},
        {"case_id": prism, "mechanism": "ALL_DIRECTIONS_FORCED_TO_VERTEX_CENTRED_THRESHOLD_SETS",
         "thinking_generic_direction": anchor(thinking[prism], 118020, 118280),
         "thinking_late_vertex_symmetry": anchor(thinking[prism], 264506, 264770),
         "final": anchor(delivery[prism], 960, 1880),
         "counterexample": measured(adjacent_pair_cut),
         "ordinary_control": "Exact sector sweep and short cut-count formula."},
        {"case_id": path, "mechanism": "EAST_STEP_ORDER_CONFUSED_WITH_CONTIGUOUS_ROW_VISITATION",
         "thinking_late_count": anchor(thinking[path], 79517, 80434),
         "final": anchor(delivery[path], 609, 1084),
         "counterexample": measured(two_lap_path),
         "ordinary_control": "Closed form for even cylinder width, independently checked by transfer."},
    ]
    cutoff = "HMMT-2026-FEB-COMB-P05"
    sentinel = delivery[cutoff].index("f(a)=-1")
    repairs = {"case_id": cutoff, "sentinel_restored_in_final": anchor(delivery[cutoff], sentinel - 37, sentinel + 17),
               "last_box_correct": True, "scope": "Early typed counterexample was addressed before final delivery."}
    counts = {str(year): dict(Counter("match" if r["archive_last_box_matches_official_reference"] else "mismatch"
                                     for r in scores["rows"] if r["year"] == year)) for year in (2025, 2026)}
    result = {
        "status": "D48_POSTSCORE_DIAGNOSIS_NO_CHANGE_TO_BLIND_GATE",
        "source_sha256": digest(Path(__file__).read_bytes()), "archive_scores_sha256": score_sha,
        "blind_outcomes_sha256": blind_sha, "stratified_archive_last_box_counts": counts,
        "ordinary_agrees_with_official": agreement,
        "ordinary_full_controls_available": len(agreement),
        "postscore_failure_diagnostics": rows, "additional_visible_self_repair": repairs,
        "typed_early_local_refutations_followed_by_visible_self_correction": 4,
        "repair_gate": {"minimum_independent_uncovered_cases": 2, "observed_independent_uncovered_cases": 0,
                        "passes": False, "new_gpu_runs": 0},
    }
    path_out = HERE / "D48_POSTSCORE_AUDIT.json"
    raw = (json.dumps(result, indent=2) + "\n").encode()
    with path_out.open("xb") as stream:
        stream.write(raw)
    print(digest(raw))


if __name__ == "__main__":
    main()
