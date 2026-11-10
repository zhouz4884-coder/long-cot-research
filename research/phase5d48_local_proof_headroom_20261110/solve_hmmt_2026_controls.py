"""Statement-only HMMT 2026 ordinary controls and exact local counterexamples."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations_with_replacement, product
import json
from math import comb, gcd, isqrt
from pathlib import Path
from time import perf_counter_ns, thread_time_ns


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / "outputs" / "d48_hmmt_original_local_20261110" / "2026-comb-problems.pdf"
FREEZE_SHA = "622e581c19323b1089f3fa1716ee130579edabede1200f20138eea38e82f84cd"
IDS = tuple(f"HMMT-2026-FEB-COMB-P{n:02}" for n in (5, 7, 9))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return sha256(raw).hexdigest()


def source_bindings(problem_pdf):
    raw = (HERE / "D48_QUESTION_FREEZE.json").read_bytes()
    require(digest(raw) == FREEZE_SHA, "Cohort changed")
    cohort = json.loads(raw)
    source = cohort["sources"]["2026"]
    require(set(IDS) <= {cid for cid, admitted, _ in cohort["rows"] if admitted}, "Unfrozen case")
    require(digest(problem_pdf.read_bytes()) == source["sha256"], "Wrong official Problems-only bytes")
    return {"cohort_sha256": FREEZE_SHA, "official_problem_pdf": source["problem_pdf"],
            "official_problem_pdf_sha256": source["sha256"], "case_ids": list(IDS)}


def p05_short(work):
    work.update({"integer_floor_divisions": 1, "integer_additions": 2, "integer_subtractions": 2,
                 "binomial_evaluations": 1})
    width, half = 10, 10 // 2
    first_row_options = width - half + 1
    answer = comb(first_row_options + half - 1, half)
    return {"value": answer, "half_rows": half, "allowed_half_height_values": first_row_options,
            "proof": "Divisors are indexed by two exponents 0..9. A downset is specified by ten nonincreasing row heights. Complementing both exponents pairs rows with height sums 10. The first five heights lie in 5..10 and determine the other five. Count weakly ordered selections of five heights from six values."}


def p05_enumerate(work):
    accepted = 0
    for heights in combinations_with_replacement(range(11), 10):
        work["downset_height_vectors"] += 1
        for i in range(5):
            work["paired_height_sum_checks"] += 1
            if heights[i] + heights[9 - i] != 10:
                break
        else:
            accepted += 1
    return {"value": accepted, "scope": "All downsets are weakly ordered height vectors; complement relation is tested exactly."}


def p05_local(work):
    original = {(a, b) for a, b in product(range(10), repeat=2) if a < 5}
    work.update({"grid_membership_initializations": 100, "membership_edits": 2})
    original.remove((2, 3))
    original.add((7, 6))
    for a, b in product(range(5), range(10)):
        work["complement_pair_checks"] += 1
        require(((a, b) in original) != ((9 - a, 9 - b) in original), "Complement premise fails")
    work.update({"directed_predecessor_checks": 1, "membership_checks": 2})
    require((2, 4) in original and (2, 3) not in original, "Downward closure is not violated")
    return {"claim": "Complement exclusivity implies the divisor-downset condition.", "antecedent": True,
            "consequent": False, "witness_encoding": "All rows a<5, then flip the complement pair (2,3) and (7,6).",
            "selected_exponents": [2, 4], "missing_divisor_exponents": [2, 3],
            "authority": "REFUTE_ONLY_THE_COMPLEMENT_IMPLIES_DOWNSET_CLAIM"}


def p07_short(work):
    n = 10
    work.update({"integer_floor_divisions": 1, "integer_subtractions": 3, "integer_squares": 2,
                 "integer_additions": 4, "integer_multiplications": 6})
    odd_sizes = n // 2
    even_sizes = odd_sizes - 1
    same_parity = n * (odd_sizes**2 + even_sizes**2)
    different_parity = 4 * n * odd_sizes * even_sizes
    one_trivial = 4 * n * (n - 1)
    all_sides = 4 + one_trivial + same_parity + different_parity
    return {"side_subsets_including_empty_and_full": all_sides, "both_parts_nonempty": all_sides - 2,
            "count_parts": {"both_trivial": 4, "one_trivial": one_trivial, "same_parity_nontrivial": same_parity,
                            "opposite_parity_nontrivial": different_parity},
            "proof": "The two aligned layers use one horizontal projection and two independent thresholds. A nontrivial k-vertex set is an arc whose admissible normal directions form one open sector of vertex-spacing width about its center. For equal-parity sizes, sectors overlap only at the same center. For opposite parity there are two adjacent half-offset choices. Empty and full layers impose no orientation restriction."}


def p07_sweep(work):
    n = 10
    period = 4 * n
    pairs = set()
    for sector in range(2 * n):
        normal = 2 * sector + 1
        distances = {}
        for vertex in range(n):
            work["exact_angular_distance_keys"] += 1
            gap = (4 * vertex - normal) % period
            distances[vertex] = min(gap, period - gap)
        require(len(set(distances.values())) == n, "Chosen sweep sector has a projection tie")
        work["layer_vertex_sorts"] += 1
        ranked = sorted(distances, key=distances.get)
        prefixes = [0]
        for vertex in ranked:
            work["prefix_bit_updates"] += 1
            prefixes.append(prefixes[-1] | (1 << vertex))
        for side in product(prefixes, repeat=2):
            work["threshold_pair_visits"] += 1
            pairs.add(side)
    full = (1 << n) - 1
    return {"side_subsets_including_empty_and_full": len(pairs),
            "both_parts_nonempty": len(pairs) - int((0, 0) in pairs) - int((full, full) in pairs),
            "proof": "Projection-order crossings occur at half-vertex-spacing orientations. A representative at each of the 20 open sectors has an exact cyclic angular order. A strict threshold at a tied orientation survives a small perturbation, so no additional side subsets occur only at ties."}


def p07_local(work):
    first, second = {0}, {5}
    work.update({"per_layer_singleton_separability_checks": 2, "nested_threshold_set_checks": 2})
    require(len(first) == len(second) == 1 and not (first <= second or second <= first), "Nested threshold counterexample fails")
    return {"claim": "Two separately separable layer cuts are jointly realizable by one plane.", "antecedent": True,
            "consequent": False, "opposite_singletons_in_aligned_vertex_indexing": [0, 5],
            "proof": "Each singleton is separable within its regular polygon by a normal toward it. A single plane induces superlevel sets of the same projected scores at both heights, hence nested subsets. These singleton labels are not nested.",
            "authority": "REFUTE_ONLY_THE_INDEPENDENT_LAYER_CUT_CLAIM"}


def p09_divisors(work):
    divisors = set()
    for d in range(1, isqrt(250) + 1):
        work["target_divisor_tests"] += 1
        if 250 % d == 0:
            divisors.update((d, 250 // d))
    return sorted(divisors)


def p09_short(work):
    divisors = p09_divisors(work)
    sizes = {}
    for d in divisors:
        size = d
        for p in (2, 5):
            work["totient_prime_divisor_tests"] += 1
            if d % p == 0:
                work["totient_factor_updates"] += 1
                size -= size // p
        sizes[d] = size
    work["block_order_sorts"] += 1
    order = sorted(divisors, key=lambda d: (sizes[d], d))
    position = {d: i for i, d in enumerate(order)}
    for a, b in product(divisors, repeat=2):
        work["divisor_precedence_tests"] += 1
        require(a == b or b % a != 0 or position[a] < position[b], "Shortest block order violates divisor precedence")
    total, ends = 0, []
    for d in order:
        work["block_completion_updates"] += 1
        total += sizes[d]
        ends.append(total)
    work["completion_sum_terms"] += len(ends)
    require(total == 250, "Target blocks do not partition A250")
    return {"value": sum(ends), "block_sizes": [[d, sizes[d]] for d in order], "block_end_labels": ends,
            "proof": "The gcd law and equal diagonal sizes imply A_i∩A_j=A_gcd(i,j). Each label has a least supporting index e and occurs exactly in multiples of e. Its disjoint block B_e has size phi(e). Sorting block maxima gives each maximum a lower bound by the cumulative block sizes. The sum of those completions is minimized by shortest block first, by the adjacent-exchange inequality. The order by (phi(e),e) here is divisor-compatible, so each target set's maximum equals its own block end. Assign contiguous labels 1..250 in this order, then give every other positive index its own fresh disjoint block of phi size. Unions over divisors extend the construction to all indices."}


def p09_subset_dp(work):
    divisors = p09_divisors(work)
    sizes = []
    for d in divisors:
        work["independent_totient_gcd_calls"] += d
        sizes.append(sum(gcd(t, d) == 1 for t in range(1, d + 1)))
    prerequisites = []
    for d in divisors:
        work["target_ancestor_membership_tests"] += len(divisors)
        prerequisites.append(sum(1 << i for i, e in enumerate(divisors) if d % e == 0))
    states = 1 << len(divisors)
    totals, complete, best = [], [], [None] * states
    for mask in range(states):
        work["subset_weight_membership_tests"] += len(divisors)
        totals.append(sum(size for i, size in enumerate(sizes) if mask & (1 << i)))
        work["subset_completed_target_tests"] += len(divisors)
        complete.append(sum((mask & req) == req for req in prerequisites))
    best[0] = 0
    for mask in range(states):
        for i in range(len(divisors)):
            bit = 1 << i
            if mask & bit:
                continue
            after = mask | bit
            work["subset_order_transitions"] += 1
            value = best[mask] + totals[after] * (complete[after] - complete[mask])
            if best[after] is None or value < best[after]:
                best[after] = value
    return {"value": best[-1], "block_order_states": states,
            "proof": "Every contiguous-block order is a subset path. A target maximum is finalized when its last divisor block is placed, so the cumulative label at that transition is charged exactly once."}


def p09_local(work):
    blocks = {1: {1}, 2: {2}, 5: {3, 4, 5, 6}, 10: {7, 8, 9, 10}}
    visible = {}
    for e, block in blocks.items():
        work["local_block_cardinality_checks"] += 1
        require(len(block) == sum(gcd(x, e) == 1 for x in range(1, e + 1)), "Block size differs")
        work["local_totient_gcd_calls"] += e
    for i in blocks:
        work["local_support_divisibility_tests"] += len(blocks)
        visible[i] = set().union(*(block for d, block in blocks.items() if i % d == 0))
    for i, j in product(visible, repeat=2):
        work["local_pair_intersection_gcd_checks"] += 1
        require(len(visible[i] & visible[j]) == gcd(i, j), "Finite gcd premise fails")
    work["counterexample_label_membership_checks"] += 2
    require(2 in visible[2] and 2 not in visible[5], "Numeric-index nesting is not violated")
    return {"claim": "Smaller numeric indices necessarily give subsets of larger numeric indices.",
            "antecedent": True, "consequent": False, "counterexample_indices": [2, 5], "counterexample_label": 2,
            "premises_checked_at": sorted(visible),
            "extendibility": "The disjoint displayed blocks have phi sizes. Add fresh phi-sized blocks for all remaining positive indices, then use unions over divisors. This certifies the finite witness can occur under the full infinite condition.",
            "authority": "REFUTE_ONLY_NUMERIC_INDEX_NESTING"}


def measured(fn):
    work = Counter()
    start, cpu = perf_counter_ns(), thread_time_ns()
    result = fn(work)
    elapsed = {"wall_ns": perf_counter_ns() - start, "thread_cpu_ns": thread_time_ns() - cpu}
    profile = None
    if elapsed["thread_cpu_ns"] < 31_250_000:
        repeats, batch = 0, 16
        began, began_cpu = perf_counter_ns(), thread_time_ns()
        while repeats < 65536 and thread_time_ns() - began_cpu < 31_250_000:
            count = min(batch, 65536 - repeats)
            for _ in range(count):
                repeated = Counter()
                require(fn(repeated) == result and repeated == work, "Repeated exact result or work differs")
            repeats += count
            batch *= 2
        profile = {"repetitions": repeats, "thread_cpu_ns": thread_time_ns() - began_cpu,
                   "wall_ns": perf_counter_ns() - began, "includes_consistency_comparisons": True}
    return {**result, "named_work": dict(sorted(work.items())), **elapsed, "repeat_cpu_profile": profile}


def run(problem_pdf):
    bindings = source_bindings(problem_pdf)
    methods = ((p05_short, p05_enumerate, p05_local), (p07_short, p07_sweep, p07_local),
               (p09_short, p09_subset_dp, p09_local))
    cases = []
    for cid, (short, independent, local) in zip(IDS, methods, strict=True):
        ordinary, full, counterexample = measured(short), measured(independent), measured(local)
        keys = ("side_subsets_including_empty_and_full", "both_parts_nonempty") if cid.endswith("P07") else ("value",)
        require(all(ordinary[key] == full[key] for key in keys), "Independent complete controls disagree")
        require(counterexample["antecedent"] and not counterexample["consequent"], "Invalid local counterexample")
        cases.append({"case_id": cid, "ordinary_short_complete": ordinary, "independent_complete": full,
                      "local_counterexample": counterexample})
    return {"status": "D48_QUESTION_ONLY_ORDINARY_HMMT_2026_CONTROLS_FROZEN", "sources": bindings,
            "code_sha256": digest(Path(__file__).read_bytes()), "rows": cases,
            "P07_label_review_before_gold": {"both_sides_may_be_empty_at_extremes": 1574, "both_parts_nonempty": 1572,
                       "scope": "The Problems PDF says partitions the vertices into two sets and does not explicitly settle emptiness. Retain both mathematically scoped counts until independent official-label review."},
            "cost_boundary": "Single-call CPU and wall include exact checking or solving. Repeated timings are separate and include consistency comparisons. Named work units are algorithm primitives with different costs. Proof derivation by the reviewer is not included.",
            "scope": "Official Problems PDF and frozen question IDs only. No official solutions, labels, trajectories or GPU work. Local synthetic assertions are method controls, not claims made by a model."}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--problem-pdf", type=Path, default=SOURCE)
    cli.add_argument("--output", type=Path, default=HERE / "D48_ORDINARY_HMMT_2026_CONTROLS.json")
    args = cli.parse_args()
    require(not args.output.exists(), "Refuse to overwrite ordinary controls")
    raw = (json.dumps(run(args.problem_pdf), indent=2, ensure_ascii=False) + "\n").encode()
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(digest(raw))
