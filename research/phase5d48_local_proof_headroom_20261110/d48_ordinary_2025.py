"""Question-only complete and representative local controls for four HMMT problems."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from fractions import Fraction
from functools import cache
from hashlib import sha256
from itertools import combinations, permutations
import json
from pathlib import Path
from time import get_clock_info, perf_counter_ns, thread_time_ns


FREEZE_SHA256 = "622e581c19323b1089f3fa1716ee130579edabede1200f20138eea38e82f84cd"
PDF_SHA256 = "ee5ce8e248dc4edae912ed0449dc4d504020d59ed914c806894d15f8fab9312b"
CASE_IDS = tuple(f"HMMT-2025-FEB-COMB-P{n:02}" for n in (3, 5, 7, 8))


def digest(raw):
    return sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def timed(function, *args):
    work = Counter()
    wall, cpu = perf_counter_ns(), thread_time_ns()
    result = function(work, *args)
    return {"result": result, "named_work": dict(work), "wall_ns": perf_counter_ns() - wall, "thread_cpu_ns": thread_time_ns() - cpu}


def box_count(work):
    # Each box has either one run of length 4 or two of length 2.
    work["canonical_pair_count"] += 1
    pairs = 16 // 2
    count = 1
    for available in range(pairs, 0, -2):
        work["matching_count_multiplications"] += 1
        count *= available - 1
    return {"answer": str(count), "atomic_pairs": pairs}


def boxes_legal(boxes, work):
    labels = set()
    for box in boxes:
        work["box_capacity_checks"] += 1
        if len(box) != 4:
            return False
        for ball in box:
            work["ball_domain_and_uniqueness_checks"] += 1
            if not 1 <= ball <= 16 or ball in labels:
                return False
            labels.add(ball)
            work["same_box_neighbor_checks"] += 1
            if ball - 1 not in box and ball + 1 not in box:
                return False
    return len(labels) == 16


def box_local(work):
    groups = ((0, 2), (1, 3), (4, 5), (6, 7))
    used = set()
    for a, b in groups:
        work["canonical_pair_index_checks"] += 2
        require(0 <= a < b < 8 and a not in used and b not in used, "Pair partition has invalid or repeated indices")
        used.update((a, b))
    require(len(used) == 8, "Pair partition omits an original ball")
    work["consecutiveness_tests"] += 1
    require(groups[0][1] - groups[0][0] > 1, "The distinguished box is not a counterexample")
    return {"fixed_canonical_pair_groups": groups, "premises_true": True, "consequent_false": True}


def box_validation(work, answer, local):
    boxes = [tuple(ball for k in group for ball in (2*k + 1, 2*k + 2)) for group in local["fixed_canonical_pair_groups"]]
    require(boxes_legal(boxes, work) and max(boxes[0]) - min(boxes[0]) != 3,
            "The expanded box counterexample must satisfy all original constraints")
    candidates = [[] for _ in range(16)]
    for chosen in combinations(range(16), 4):
        work["four_set_feasibility_checks"] += 1
        if all(i - 1 in chosen or i + 1 in chosen for i in chosen):
            mask = sum(1 << i for i in chosen)
            for i in chosen:
                candidates[i].append(mask)

    @cache
    def cover(mask):
        work["exact_cover_states"] += 1
        if not mask:
            return 1
        anchor = (mask & -mask).bit_length() - 1
        result = 0
        for subset in candidates[anchor]:
            work["fixed_anchor_subset_checks"] += 1
            if mask & subset == subset:
                result += cover(mask ^ subset)
        return result

    value = cover((1 << 16) - 1)
    require(str(value) == answer, "Exact cover disagrees with the ordinary pairing formula")
    return {"independent_exact_cover_count": str(value)}


def edge(a, b):
    return tuple(sorted((a, b)))


def removed_grid_edges(work):
    result = []
    for k in (2, 4, 6, 8):
        work["constructed_within_side_deletions"] += 2
        result.extend((edge((0, k), (0, k + 1)), edge((k, 0), (k + 1, 0))))
    for k in (1, 3, 5, 7):
        work["constructed_within_side_deletions"] += 2
        result.extend((edge((10, k), (10, k + 1)), edge((k, 10), (k + 1, 10))))
    for a, b, c in (
        ((0, 1), (0, 0), (1, 0)),
        ((10, 9), (10, 10), (9, 10)),
    ):
        work["constructed_corner_path_deletions"] += 2
        result.extend((edge(a, b), edge(b, c)))
    return tuple(result)


def grid_count(work):
    # Each of four odd sides contributes an odd cross-cut incidence.
    work["common_side_group_parity_evaluations"] += 1
    side = 11 - 2
    require(side % 2 == 1, "This construction uses four odd side groups")
    work["grid_edge_count_formulas"] += 1
    total = 2 * 11 * 10
    work["deleted_degree_endpoint_bound_formulas"] += 1
    lower_deletions = (4 * side + 4) // 2
    removed = removed_grid_edges(work)
    require(len(set(removed)) == lower_deletions == len(removed), "Removal construction misses the endpoint lower bound")
    return {"answer": str(total - lower_deletions), "removed_edges": removed, "lower_deletions": lower_deletions}


def adjacency(edges, work, *, validate):
    neighbors = defaultdict(set)
    for a, b in edges:
        if validate:
            work["original_grid_door_checks"] += 1
            require(all(0 <= x < 11 for x in (*a, *b)) and abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1,
                    "A witness edge is not an original grid door")
            work["duplicate_door_checks"] += 1
            require(b not in neighbors[a], "A witness repeats a grid door")
        work["adjacency_insertions"] += 2
        neighbors[a].add(b)
        neighbors[b].add(a)
    return neighbors


def grid_local(work):
    cycle_a = ((0, 0), (0, 1), (1, 1), (1, 0))
    cycle_b = ((3, 3), (3, 4), (4, 4), (4, 3))
    for cycle in (cycle_a, cycle_b):
        work["simple_cycle_distinctness_checks"] += 1
        require(len(set(cycle)) == 4, "A witness cycle repeats a vertex")
        for k, a in enumerate(cycle):
            b = cycle[(k+1) % len(cycle)]
            work["original_grid_door_checks"] += 1
            require(all(0 <= x < 11 for x in (*a, *b)) and abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1,
                    "A witness edge is not an original grid door")
    work["disjoint_support_checks"] += 1
    require(set(cycle_a).isdisjoint(cycle_b), "The witness supports are connected")
    return {"cycle_vertices": [cycle_a, cycle_b], "premises_true": True, "consequent_false": True}


def grid_local_validation(work, local):
    cycle_a, cycle_b = local["cycle_vertices"]
    edges = tuple(edge(c[k], c[(k + 1) % 4]) for c in (cycle_a, cycle_b) for k in range(4))
    g = adjacency(edges, work, validate=True)
    for neighbors in g.values():
        work["used_cell_degree_parity_checks"] += 1
        require(len(neighbors) % 2 == 0, "A local premise requires all used degrees even")
    seen, queue = {cycle_a[0]}, deque([cycle_a[0]])
    while queue:
        u = queue.popleft()
        for v in g[u]:
            work["component_adjacencies_scanned"] += 1
            if v not in seen:
                seen.add(v)
                queue.append(v)
    require(cycle_b[0] not in seen, "The even support unexpectedly has one component")
    return {"local_seen_support_vertices": len(seen), "local_total_used_vertices": len(g)}


def grid_validation(work, result, local):
    checked_local = grid_local_validation(work, local)
    all_edges = set()
    for a in range(11):
        for b in range(11):
            for da, db in ((1, 0), (0, 1)):
                if a + da < 11 and b + db < 11:
                    work["original_edges_generated"] += 1
                    all_edges.add(edge((a, b), (a + da, b + db)))
    removed = set(result["removed_edges"])
    require(removed <= all_edges, "Removal uses a door outside the original graph")
    kept = all_edges - removed
    g = adjacency(kept, work, validate=False)
    for neighbors in g.values():
        work["remaining_degree_parity_checks"] += 1
        require(len(neighbors) % 2 == 0, "A retained vertex has odd degree")
    start = min(g)
    stack, trail = [start], []
    while stack:
        u = stack[-1]
        if not g[u]:
            trail.append(stack.pop())
        else:
            v = min(g[u])
            g[u].remove(v)
            g[v].remove(u)
            stack.append(v)
            work["euler_doors_traversed"] += 1
    checked = {edge(a, b) for a, b in zip(trail, trail[1:])}
    require(trail[0] == trail[-1] and len(trail) - 1 == len(kept) == len(checked) and checked == kept
            and len(kept) == int(result["answer"]), "Constructed even graph failed the exact closed-trail witness")
    return {**checked_local, "closed_trail_edges": len(checked), "euler_vertex_sequence_sha256": digest(json_bytes(trail))}


def word_count(work):
    n = 26
    total = 1
    for k in range(2, n + 1):
        work["permutation_count_multiplications"] += 1
        total *= k
    work["internal_cut_subset_cardinality"] += 1
    cuts = 1 << (n - 1)
    work["block_count_multiplications"] += 1
    return {"answer": str(total * cuts), "permutations": str(total), "cut_subsets": cuts}


def projection(word, a, b, work):
    out = []
    for char in word:
        work["projected_letter_visits"] += 1
        if char == a or char == b:
            out.append(char)
    return tuple(out)


def balanced(proj, a, b, work):
    for letter in (a, b):
        positions = [i for i, char in enumerate(proj) if char == letter]
        work["two_gap_equality_checks"] += 1
        if len(positions) != 3 or positions[1] - positions[0] != positions[2] - positions[1]:
            return False
    return True


def word_local(work):
    # The block certificate verifies all pairs without inspecting 650 directions.
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    blocks = (alphabet[:1], alphabet[1:])
    work["partition_letter_visits"] += sum(map(len, blocks))
    require(len(set("".join(blocks))) == len(alphabet) and set("".join(blocks)) == set(alphabet),
            "The witness block partition does not cover the alphabet exactly once")
    proj = tuple(block[0] for block in blocks for _ in range(3))
    work["compressed_projection_letter_occurrences"] += len(proj)
    require(balanced(proj, "a", "b", work), "The distinguishing projection must satisfy the original balance")
    work["global_repeated_order_consequent_checks"] += 1
    require(proj not in (tuple("ababab"), tuple("bababa")), "The counterexample repeats a single global permutation")
    return {"fixed_repeat_blocks": blocks,
            "distinguishing_projection": "".join(proj), "premises_true": True, "consequent_false": True}


def word_validation(work, local):
    accepted = []
    for positions in combinations(range(6), 3):
        work["two_letter_words_checked"] += 1
        word = tuple("a" if i in positions else "b" for i in range(6))
        if balanced(word, "a", "b", work):
            accepted.append("".join(word))
    require(set(accepted) == {"aaabbb", "bbbaaa", "ababab", "bababa"}, "Incorrect two-letter characterization")
    witness = "".join(block*3 for block in local["fixed_repeat_blocks"])
    for a, b in combinations("abcdefghijklmnopqrstuvwxyz", 2):
        require(balanced(projection(witness, a, b, work), a, b, work), "A pair violates original balance")
    return {"two_letter_patterns": sorted(accepted), "validated_local_unordered_pairs": 325}


def windows_count(work):
    n, t = 2025, 100
    work["window_width_formulas"] += 1
    width = 2*t + 1
    work["unwrapped_window_geometry_checks"] += 1
    require(2*width - 1 <= n and width < n, "The circular start-interval proof does not apply")
    work["exact_indicator_expectation_formulas"] += 1
    return {"answer": str(Fraction(2*n, width+1)), "window_width": width, "adjacent_union_width": width+1}


def rank_at(i, n):
    return n-1 if i == 0 else n if i == 1 else i-1


def windows_local(work):
    # Rank i -> rank/(n+1) gives a legal original distinct-value realization.
    n, radius, surviving, larger = 2025, 100, 0, 1
    center = -radius % n
    start = (center-radius) % n
    work["cyclic_window_width_and_position_checks"] += 2
    width = 2*radius + 1
    contains = lambda index: (index-start) % n < width
    require(contains(surviving) and not contains(larger), "Chosen window does not isolate the second-ranked value")
    work["fixed_rank_bounds"] += 2
    require(rank_at(surviving, n) == n - 1 and rank_at(larger, n) == n, "Rank construction changed")
    work["strictly_larger_neighbor_checks"] += 1
    require((larger-surviving) % n <= radius and rank_at(larger, n) > rank_at(surviving, n),
            "Surviving index remains the maximum of its own radius window")
    return {"fixed_ring_rank_rule": "second-largest at index 0, largest at 1, index-1 elsewhere",
            "window_center": center, "window_width": width, "premises_true": True, "consequent_false": True}


def windows_validation(work, local):
    n, radius = 2025, 100
    center = local["window_center"]
    for c, expected in ((center, n-1), (0, n)):
        ranks = []
        for offset in range(-radius, radius+1):
            work["direct_window_rank_reads"] += 1
            ranks.append(rank_at((c+offset) % n, n))
        require(max(ranks) == expected, "Exact direct windows disagree with the local rank certificate")
    count, trials = 0, 0
    for ordering in permutations(range(5)):
        trials += 1
        work["small_circular_orderings"] += 1
        maxima = [max(ordering[i], ordering[(i+1)%5], ordering[(i+2)%5]) for i in range(5)]
        work["small_window_maxima"] += 5
        count += len(set(maxima))
    require(Fraction(count, trials) == Fraction(2*5, 3+1), "Exact small analog disagrees with the transition formula")
    return {"direct_windows_verified": 2, "small_analog_expected_distinct": str(Fraction(count, trials))}


CASES = (
    (box_count, box_local, lambda w, full, local: box_validation(w, full["answer"], local),
     "Each box has four balls and no singleton run, so all maximal runs have length two or four. Every run boundary is even. Pair the eight canonical consecutive pairs into four unordered boxes. Conversely any such pairing supplies a same-box neighbor to every ball.",
     "Every valid box must consist of four consecutive labels."),
    (grid_count, grid_local, grid_validation,
     "An Eulerian closed trail leaves even degrees. All 36 original odd vertices need one removed endpoint. Each of the four side groups has odd size and needs an odd removal cut. A cross-cut edge goes to a non-odd vertex because no grid door joins two different odd side groups. Thus at least four more removed endpoints and 20 removed doors are required. The four side matchings and two corner paths achieve 20. The full inner grid and intact inward doors connect all positive-degree vertices.",
     "Any even-degree door subset is the support of one closed trail using every chosen door."),
    (word_count, word_local, lambda w, _full, local: word_validation(w, local),
     "Pair projections are separated triples or alternating. If two disjoint letter intervals overlapped a third one, two copies of the third letter would be before the first boundary and two after the second, which is impossible. Thus alternating overlap forms ordered blocks. Each block repeats its first-occurrence permutation three times. Each global permutation and each subset of its 25 internal cuts yields one word.",
     "Every valid arrangement repeats one permutation of all letters three times."),
    (windows_count, windows_local, lambda w, _full, local: windows_validation(w, local),
     "After 100 synchronous steps each entry is the maximum of one cyclic window of width 201. For a fixed rank, each larger index on its left or right cuts a prefix or suffix from the start interval of windows containing it. Surviving ranks therefore each give one contiguous run of equal maxima, and the runs are counted by changes between adjacent windows. The maximum of their 202-position union is equally likely at every position. The maxima differ precisely when that index is an entering or departing endpoint.",
     "A surviving original value must have been largest in its own radius-100 neighborhood."),
)


def run(problem_pdf, question_freeze):
    freeze = question_freeze.read_bytes()
    require(digest(freeze) == FREEZE_SHA256, "Different frozen question cohort")
    q = json.loads(freeze)
    source_sha = digest(problem_pdf.read_bytes())
    require(source_sha == q["sources"]["2025"]["sha256"] == PDF_SHA256, "Different original question PDF")
    admitted = {cid for cid, selected, _ in q["rows"] if selected}
    require(set(CASE_IDS) <= admitted, "A local case is outside the frozen cohort")
    rows = []
    for cid, (solve, local, validate, proof, tested_claim) in zip(CASE_IDS, CASES, strict=True):
        complete = timed(solve)
        counterexample = timed(local)
        sanity = timed(validate, complete["result"], counterexample["result"])
        rows.append({"case_id": cid, "complete_proof": proof, "ordinary_complete": complete,
                     "representative_local_assertion": tested_claim, "exact_local_counterexample": counterexample,
                     "separate_independent_validation": sanity})
    return {
        "status": "D48_2025_QUESTION_ONLY_ORDINARY_AND_LOCAL_CONTROLS_FROZEN",
        "question_freeze_sha256": FREEZE_SHA256, "problem_pdf_sha256": source_sha,
        "control_source_sha256": digest(Path(__file__).read_bytes()), "rows": rows,
        "scope": "Original problem PDF only. Values are independent derivations. Local claims and witnesses are synthetic arithmetic controls.",
        "cost_boundary": "Each timed call includes its executable work. Manual derivation, initial PDF I/O and final JSON I/O are outside these receipts. Named operations have heterogeneous costs. Separate validation never supplies the ordinary construction's input.",
        "timer_resolution_seconds": {clock: get_clock_info(clock).resolution for clock in ("perf_counter", "thread_time")},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("problem-pdf", "question-freeze", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    data = run(args.problem_pdf, args.question_freeze)
    with args.output.open("xb") as stream:
        stream.write(json_bytes(data))
    print(data["status"], len(data["rows"]), digest(args.output.read_bytes()))
