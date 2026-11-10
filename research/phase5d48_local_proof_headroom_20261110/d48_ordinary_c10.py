"""Question-only ordinary controls for both frozen Combinatorics item tens."""
from collections import Counter
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import combinations, permutations, product
import json
from pathlib import Path
from time import perf_counter_ns, process_time_ns


def gaps_potential(gaps):
    if len(gaps) < 2 or any(type(gap) is not int or gap <= 0 for gap in gaps):
        raise ValueError("The initial cyclic state must have at least two positive integer gaps")
    # For every active gap E[delta] = E[delta^3] = 0 and E[delta^2] = 1/2.
    # Zero gaps disappear, leaving the same sum of cubes as before deletion.
    mass = sum(gaps)
    start = sum(gap**3 for gap in gaps)
    terminal = mass**3
    drift = Fraction(3 * mass, 2)
    work = {"gap_mass_additions": len(gaps), "gap_cubes": len(gaps) + 1,
            "cube_sum_additions": len(gaps), "drift_products": 1,
            "potential_subtractions": 1, "exact_rational_divisions": 1}
    return (terminal - start) / drift, work


def gap_step(gaps, signs):
    if len(gaps) != len(signs) or len(gaps) < 2 or any(gap <= 0 for gap in gaps):
        raise ValueError("Expected one direction per snake and positive half-gaps")
    if any(sign not in (-1, 1) for sign in signs):
        raise ValueError("Invalid direction")
    result = tuple(gap + (signs[(i + 1) % len(signs)] - signs[i]) // 2 for i, gap in enumerate(gaps))
    return tuple(gap for gap in result if gap)


@lru_cache(maxsize=3)
def column_runs(visits):
    """Each tuple describes the rows at starts and ends of chronological runs."""
    configurations = []
    for order in permutations(range(3)):
        for cuts in combinations((1, 2), visits - 1):
            points = (0, *cuts, 3)
            runs = tuple(order[left:right] for left, right in zip(points, points[1:]))
            if all(abs(a - b) == 1 for run in runs for a, b in zip(run, run[1:])):
                configurations.append((tuple(run[0] for run in runs), tuple(run[-1] for run in runs)))
    return tuple(configurations)


def cylinder_paths(columns):
    if type(columns) is not int or columns < 2:
        raise ValueError("Need at least two distinct columns")
    totals = {}
    work = Counter()
    for horizontal in range(columns - 1, 3 * columns):
        work["horizontal_move_counts"] += 1
        visits = tuple(1 + (horizontal - column) // columns for column in range(columns))
        end_column = horizontal % columns
        total = 0
        # After rotating x_1 to 0, its first run begins in row 2.
        for first_in, first_out in column_runs(visits[0]):
            work["first_run_configuration_attempts"] += 1
            if first_in[0] != 2 or (end_column == 0 and first_out[-1] != 0):
                continue
            states = {first_out: 1}
            for column in range(1, columns):
                next_states = Counter()
                for entries, exits in column_runs(visits[column]):
                    work["column_configuration_attempts"] += 1
                    if column == end_column and exits[-1] != 0:
                        continue
                    # If the prior column contains the path endpoint, its last exit
                    # is not a horizontal move. All other exits match in order.
                    prev_exits = entries if column - 1 != end_column else (*entries, 0)
                    multiplicity = states.get(prev_exits, 0)
                    if multiplicity:
                        next_states[exits] += multiplicity
                        work["transfer_accumulations"] += 1
                states = next_states
            wrap_exits = first_in[1:] if end_column != columns - 1 else (*first_in[1:], 0)
            total += states.get(wrap_exits, 0)
            work["wrap_matches"] += 1
        totals[horizontal] = total * columns
        work["rotations_products"] += 1
    work["horizontal_count_accumulations"] = len(totals)
    return sum(totals.values()), totals, dict(work)


def cylinder_paths_small_dfs(columns):
    """Independent exact enumeration, used only on small control instances."""
    def visit(x, y, visited):
        if len(visited) == columns * 3:
            return int(y == 0)
        neighbors = (((x + 1) % columns, y), (x, y - 1), (x, y + 1))
        return sum(visit(nx, ny, visited | {(nx, ny)})
                   for nx, ny in neighbors if 0 <= ny <= 2 and (nx, ny) not in visited)
    return columns * visit(0, 2, {(0, 2)})


def directed_step(first, second, columns):
    x, y = first
    a, b = second
    return (x == a and abs(y - b) == 1) or (y == b and (x + 1) % columns == a)


def cylinder_even_closed(columns):
    if type(columns) is not int or columns < 2 or columns % 2:
        raise ValueError("Closed form applies to positive even column counts")
    return columns * ((1 << (columns // 2)) - 1)


def audit_controls():
    for columns in range(2, 7):
        exact, _, _ = cylinder_paths(columns)
        if exact != cylinder_paths_small_dfs(columns):
            raise AssertionError(("cylinder differential", columns))
    even_widths = list(range(2, 25, 2))
    for columns in even_widths:
        if cylinder_paths(columns)[0] != cylinder_even_closed(columns):
            raise AssertionError(("cylinder closed-form differential", columns))
    # Check the drift via the original joint direction distribution on small
    # states. Independence between gaps is never used in the proof.
    checked = 0
    for count in (2, 3, 4):
        for gaps in product(range(1, 4), repeat=count):
            before = sum(gap**3 for gap in gaps)
            after = sum(sum(gap**3 for gap in gap_step(gaps, signs))
                        for signs in product((-1, 1), repeat=count))
            if Fraction(after, 2**count) - before != Fraction(3 * sum(gaps), 2):
                raise AssertionError(("drift differential", gaps))
            checked += 1
    return checked, even_widths


def measured(fn):
    wall = perf_counter_ns()
    cpu = process_time_ns()
    result = fn()
    return result, {"wall_ns": perf_counter_ns() - wall, "process_cpu_ns": process_time_ns() - cpu}


def main():
    gap_audits, even_widths = audit_controls()
    (snake_value, snake_work), snake_cost = measured(lambda: gaps_potential((1,) * 15))
    # One representative local move checks only the gap at the pair of snakes.
    snake_local, snake_local_cost = measured(lambda: 1 + (-1 - 1) // 2 == 0)
    column_runs.cache_clear()
    (cylinder_value, by_horizontal, cylinder_work), cylinder_cost = measured(lambda: cylinder_paths(20))
    closed_value, closed_cost = measured(lambda: cylinder_even_closed(20))
    if cylinder_value != closed_value:
        raise AssertionError("Full controls disagree")
    cylinder_local, cylinder_local_cost = measured(lambda: directed_step((19, 1), (0, 1), 20))
    print(json.dumps({
        "status": "INDEPENDENT_ORDINARY_CONTROLS_BEFORE_GOLD_AND_ARCHIVE_RESPONSE",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "question_freeze_sha256": "622e581c19323b1089f3fa1716ee130579edabede1200f20138eea38e82f84cd",
        "audits": {"cylinder_widths_against_DFS": [2, 3, 4, 5, 6],
                   "cylinder_widths_against_closed_form": even_widths,
                   "small_exact_joint_gap_states": gap_audits},
        "2025-P10": {"answer": str(snake_value), "work": snake_work, "time": snake_cost,
                     "local_illustration": {"result": snake_local, "time": snake_local_cost,
                                            "work": {"integer_arithmetic": 3, "integer_compare": 1}}},
        "2026-P10": {"answer": cylinder_value, "by_east_moves": by_horizontal,
                     "work": cylinder_work, "time": cylinder_cost,
                     "closed_form": {"answer": closed_value, "time": closed_cost,
                                     "work": {"integer_division": 1, "integer_shift": 1,
                                              "integer_subtraction": 1, "integer_multiplication": 1}},
                     "local_illustration": {"result": cylinder_local, "time": cylinder_local_cost,
                                            "work": {"integer_arithmetic": 2, "integer_compare": 3}}},
        "cost_scope": "Local examples are not model claims. A single CPU timing is noisy; work categories are not interchangeable. Complete inputs are unbounded beyond the stated problem instance.",
    }, indent=2))


if __name__ == "__main__":
    main()
