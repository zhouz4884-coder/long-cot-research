"""Reviewed objective and constraint identities for the direct integer pilot."""

PROBLEMS = {
    "2009-I-14": {
        "direction": "MIN", "objective_id": "minimum-s2",
        "description": "Minimum sum of squared entries over the original length and two moments.",
        "fields": ["counts"], "constraints": ["four_count_domain", "length", "first_moment", "fourth_moment"],
        "role_patterns": [r"\bS\s*[_\\{ ]*\s*2\b|sum of (?:the )?squares|second moment"],
    },
    "2009-II-4": {
        "direction": "MIN", "objective_id": "minimum-winner-grapes",
        "description": "Minimum count of grapes eaten by the winner over the feasible contest sizes.",
        "fields": ["winner", "children"], "constraints": ["winner_positive", "plural_children", "last_nonnegative", "total_grapes"],
        "role_patterns": [r"\bgrapes?\b|\bwinner\b|\bn\s*(?:=|is)\b"],
    },
    "2010-I-14": {
        "direction": "MAX", "objective_id": "maximum-floor-log-index",
        "description": "Largest positive integer input n to the prescribed floor-log sum.",
        "fields": ["n"], "constraints": ["positive_n", "complete_floor_log_sum"],
        "role_patterns": [r"\bn\b|f\s*\(\s*n\s*\)|\bvalue of the input\b"],
    },
    "2010-II-6": {
        "direction": "MIN", "objective_id": "minimum-polynomial-n",
        "description": "Smallest positive n in the specified integer-factorizable polynomial.",
        "fields": ["n", "left", "right"], "constraints": ["positive_n", "integer_nonconstant_factors", "exact_factor_product"],
        "role_patterns": [r"\bn\b|\bcoefficient magnitude\b"],
    },
    "2015-I-8": {
        "direction": "MIN", "objective_id": "minimum-dual-digit-sum-n",
        "description": "Smallest positive n with both prescribed decimal digit sums.",
        "fields": ["n"], "constraints": ["positive_n", "original_digit_sum", "shifted_digit_sum"],
        "role_patterns": [r"\bn\b|\bdigit sums?\b|864"],
    },
    "2016-I-12": {
        "direction": "MIN", "objective_id": "minimum-four-prime-index",
        "description": "Least positive m such that the prescribed polynomial has at least four prime factors counting multiplicity.",
        "fields": ["m", "primes"], "constraints": ["positive_m", "at_least_four_factors", "prime_factors", "exact_factor_product"],
        "role_patterns": [r"\bm\b|\bindex\b"],
    },
    "2020-I-3": {
        "direction": "MIN", "objective_id": "minimum-mixed-radix-n",
        "description": "Least positive value N, expressed in decimal, with the two original digit patterns.",
        "fields": ["a", "b", "c"], "constraints": ["base_eight_digit_domain", "nonzero_base_eleven_leading", "same_represented_integer"],
        "role_patterns": [r"\bN\b|\bbase[- ](?:ten|10)\b|\bdecimal value\b"],
    },
    "2020-I-10": {
        "direction": "MIN", "objective_id": "minimum-power-divisibility-sum",
        "description": "Least possible m+n over the original positive integer pair and all three divisibility constraints.",
        "fields": ["m", "n"], "constraints": ["positive_pair", "sum_coprime_210", "power_divisibility", "ordinary_nondivisibility"],
        "role_patterns": [r"\bm[\s$\\]*\+[\s$\\]*n\b|\bsum\b"],
    },
    "2021-II-13": {
        "direction": "MIN", "objective_id": "minimum-modular-sequence-index",
        "description": "Least positive index n where the exact expression is divisible by 1000.",
        "fields": ["n"], "constraints": ["positive_n", "residue_zero"],
        "role_patterns": [r"\bn\b|\bindex\b"],
    },
    "2022-II-1": {
        "direction": "MIN", "objective_id": "minimum-final-adult-count",
        "description": "Minimum number of adults after the bus arrives, with the original crowd and bus constraints.",
        "fields": ["initial_crowd", "bus_adults"], "constraints": ["positive_initial_crowd", "integral_initial_adults", "bus_occupancy", "exact_final_adult_ratio"],
        "role_patterns": [r"\b(?:adult|adults)\b", r"\b(?:final|after|total|following)\b"],
    },
    "2023-I-15": {
        "direction": "MAX", "objective_id": "maximum-complex-triangle-prime",
        "description": "Largest prime p below 1000 admitting the original integer complex number and a nondegenerate triangle.",
        "fields": ["p", "a", "b"], "constraints": ["prime_below_1000", "complex_norm", "positive_cubic_components", "triangle_inequalities"],
        "role_patterns": [r"\b(?:prime|p)\b"],
    },
}
