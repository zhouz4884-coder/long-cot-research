"""Reviewed point objectives, binding subjects and local proof modes."""

PROBLEMS = {
    "2009-I-7": {
        "direction": "MIN", "objective_id": "first-integral-telescoping-index",
        "description": "Least index k greater than one whose sequence term is integral.",
        "subject_patterns": [r"k", r"(?:positive )?(?:integer )?index(?: k)?", r"sequence index(?: k)?"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["index_above_one", "integral_sequence_term"],
    },
    "2010-II-3": {
        "direction": "MAX", "objective_id": "greatest-power-two-exponent",
        "description": "Greatest exponent n of 2 dividing the product of all original differences.",
        "subject_patterns": [r"n", r"(?:integer )?exponent(?: n)?", r"power of (?:2|two) exponent"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["positive_exponent", "divides_original_product"],
    },
    "2010-II-12": {
        "direction": "MIN", "objective_id": "minimum-isosceles-common-perimeter",
        "description": "Minimum common perimeter of the specified noncongruent isosceles triangles.",
        "subject_patterns": [r"p", r"(?:common )?perimeter(?: p)?", r"perimeter of (?:both|the) triangles"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["positive_perimeter", "integer_base_ratio",
                                                        "integer_lateral_sides", "strict_triangles", "equal_areas"],
    },
    "2011-I-12": {
        "direction": "MIN", "objective_id": "minimum-women-conditioned-run-count",
        "description": "Least number of women for the exact conditional run probability threshold.",
        "subject_patterns": [r"w", r"(?:number|count) of women", r"women(?: in (?:the )?line)?"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["positive_women_count", "conditioned_probability_threshold"],
    },
    "2013-II-6": {
        "direction": "MIN", "objective_id": "least-square-free-block-index",
        "description": "Least positive block index N whose 1000 prescribed consecutive integers contain no square.",
        "subject_patterns": [r"n", r"(?:positive )?(?:integer )?(?:block )?index(?: n)?", r"block number(?: n)?"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["positive_index", "complete_block_contains_no_square"],
    },
    "2015-I-11": {
        "direction": "MIN", "objective_id": "minimum-incenter-isosceles-perimeter",
        "description": "Least perimeter among original integer isosceles triangles satisfying BI=8.",
        "subject_patterns": [r"p", r"perimeter(?: p)?", r"perimeter of (?:the )?triangle(?: abc)?"],
        "point_mode": "FIXED_FIBER_EXHAUSTION", "constraints": ["positive_integer_perimeter", "integer_isosceles_sides",
                                                               "strict_triangle", "exact_incenter_distance"],
    },
    "2015-II-3": {
        "direction": "MIN", "objective_id": "least-divisible-number-with-digit-sum",
        "description": "Least positive integer m with both the original divisibility and digit-sum constraints.",
        "subject_patterns": [r"m", r"(?:positive )?(?:integer|number)(?: m)?", r"qualifying multiple(?: m)?"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["positive_integer", "divisible_by_17", "decimal_digit_sum_17"],
    },
    "2015-II-5": {
        "direction": "MIN", "objective_id": "minimum-grid-side-adjacency-probability",
        "description": "Least grid side n at which the exact adjacent-pair probability is below the given threshold.",
        "subject_patterns": [r"n", r"(?:grid )?side(?: length)?(?: n)?", r"dimension(?: n)?", r"grid size(?: n)?"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["two_squares_selectable", "strict_probability_threshold"],
    },
    "2017-II-5": {
        "direction": "MAX", "objective_id": "greatest-missing-edge-sum",
        "description": "Maximum x+y for the two unspecified pair sums of four distinct real numbers.",
        "subject_patterns": [r"x\s*\+\s*y", r"sum of x and y", r"sum of (?:the )?(?:two )?missing(?: pair(?:wise)?)? sums"],
        "point_mode": "FIXED_FIBER_EXHAUSTION", "constraints": ["four_distinct_real_values", "all_given_pair_sums",
                                                               "fixed_missing_pair_sum"],
    },
    "2019-I-14": {
        "direction": "MIN", "objective_id": "least-odd-prime-factor",
        "description": "Least odd prime divisor of the original fixed integer.",
        "subject_patterns": [r"p", r"(?:odd )?prime(?: factor| divisor)?(?: p)?", r"factor p"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["odd_prime", "modular_divisibility"],
    },
    "2021-II-15": {
        "direction": "MIN", "objective_id": "least-index-exact-recursive-ratio",
        "description": "Least positive n where the two original recurrence functions have the exact given ratio.",
        "subject_patterns": [r"n", r"(?:positive )?(?:integer )?index(?: n)?", r"input(?: n)?"],
        "point_mode": "EXACT_PREDICATE", "constraints": ["positive_index", "exact_recursive_ratio"],
    },
}
