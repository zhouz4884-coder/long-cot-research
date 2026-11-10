"""Reviewed exact units and original-object grammar for the eight D4.7 questions."""

PROBLEMS = {
    "2009-I-13": {
        "direction": "MIN", "unit": "integer-sum-of-initial-terms", "objective_id": "least-integral-sequence-start-sum",
        "description": "Least a1+a2 over the original infinite positive integer recurrence.",
        "subject_patterns": [r"a_?\s*\{?1\}?\s*\+\s*a_?\s*\{?2\}?", r"sum of (?:the )?(?:first two|initial) terms"],
        "constraints": ["positive_integer_sum", "positive_integer_factors", "infinite_recurrence"],
    },
    "2010-I-12": {
        "direction": "MIN", "unit": "integer-set-endpoint", "objective_id": "least-monochromatic-product-endpoint",
        "description": "Smallest endpoint m for the original universal two-part monochromatic product property.",
        "subject_patterns": [r"m", r"(?:set )?endpoint(?: m)?", r"integer m"],
        "constraints": ["integer_endpoint_at_least_three", "every_partition_forces_product"],
    },
    "2016-II-4": {
        "direction": "MIN", "unit": "unit-cubes", "objective_id": "least-coloured-box-volume",
        "description": "Smallest original box volume abc satisfying all prescribed layer counts.",
        "subject_patterns": [r"v", r"(?:box )?volume", r"volume of (?:the )?box", r"a\s*b\s*c"],
        "constraints": ["integer_box_dimensions", "first_direction_layer_colours", "second_direction_layer_colours"],
    },
    "2018-I-13": {
        "direction": "MIN", "unit": "squared-length", "objective_id": "least-two-incenter-triangle-area",
        "description": "Least area of AI1I2 with X in the strict interior of the original side.",
        "subject_patterns": [r"(?:triangle )?area", r"area of (?:triangle )?a\s*i_?\s*\{?1\}?\s*i_?\s*\{?2\}?", r"area of (?:the )?incenter triangle"],
        "constraints": ["interior_side_position", "original_incenter_area"],
    },
    "2018-I-8": {
        "direction": "MAX", "unit": "squared-diameter", "objective_id": "maximum-inscribed-diameter-squared",
        "description": "Squared diameter of the largest circle inside the original equiangular hexagon. Square preserves order for positive diameters.",
        "subject_patterns": [r"d\s*\^\s*\{?2\}?", r"squared diameter", r"diameter squared", r"square of (?:the )?diameter"],
        "constraints": ["positive_squared_diameter", "six_original_halfspaces"],
    },
    "2019-I-11": {
        "direction": "MIN", "unit": "perimeter-length", "objective_id": "least-isosceles-excircle-perimeter",
        "description": "Least integer-sided isosceles perimeter permitting an incenter-centered circle with all three original tangencies.",
        "subject_patterns": [r"p", r"perimeter(?: p)?", r"perimeter of (?:the )?triangle(?: abc)?"],
        "constraints": ["positive_integer_isosceles_sides", "strict_triangle", "internal_base_tangency", "external_side_tangencies"],
    },
    "2020-II-8": {
        "direction": "MIN", "unit": "integer-sequence-index", "objective_id": "least-recursive-zero-sum-index",
        "description": "Least positive index n whose original function has zero sum strictly greater than 500000.",
        "subject_patterns": [r"n", r"(?:positive )?(?:integer )?index(?: n)?", r"function index(?: n)?"],
        "constraints": ["positive_integer_index", "strict_sum_of_all_distinct_zeros"],
    },
    "2022-II-12": {
        "direction": "MIN", "unit": "sum-of-semiaxis-lengths", "objective_id": "least-confocal-ellipse-semiaxis-sum",
        "description": "Least a+b over the real variables satisfying both original ellipse equalities and strict semiaxis constraints.",
        "subject_patterns": [r"a\s*\+\s*b", r"sum of a and b", r"sum of (?:the )?semiaxes"],
        "constraints": ["strict_original_semiaxes", "common_point_of_both_ellipses"],
    },
}
