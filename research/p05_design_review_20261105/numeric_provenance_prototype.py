"""Read-only CPU audit of a lexical numeric-provenance heuristic.

Candidate edges are UNKNOWN lexical reappearances, never gold dependencies,
correction events, causal evidence, or automatic model-intervention triggers.
Existing P1 selection and all original sources remain unchanged.
"""

import collections
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(r"D:\ACL")
BASE = Path(__file__).parent
MANIFEST = ROOT / "research/next_design_20261105/P1_sampling_manifest.json"
EXPECTED_MANIFEST_SHA = "6ee72c687db428cf341ec0f65ce1c3d51de94aa57eb8033e899baeccd0ce30eb"

# Atomic literal parsing only. No symbolic execution, entity resolution, unit
# conversion, coreference, expression equivalence, or proof of reference/use.
NUMBER = re.compile(
    r"(?<![\w.])(?:"
    r"(?P<latex>[+-]?\\(?:d?frac)\s*\{\s*[+-]?\d+\s*\}\s*\{\s*[+-]?\d+\s*\})"
    r"|(?P<fraction>[+-]?\d+\s*/\s*\d+)"
    r"|(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?%?)"
    r")(?!\d|\.\d)"
)
RISK_PATTERNS = {
    "negation_or_rejection_cue": re.compile(r"\b(?:not|wrong|incorrect|mistake|reject|cannot|rather than|instead of)\b|不对|错误|否定|而非", re.I),
    "conditional_or_branch_cue": re.compile(r"\b(?:if|suppose|assuming|assume|case|else|otherwise|unless|alternative)\b|假设|如果|情况|分支", re.I),
    "unit_or_percent_cue": re.compile(r"(?<!\w)(?:cm|mm|km|kg|grams?|kilograms?|lbs?|meters?|metres?|hours?|hrs?|minutes?|mins?|seconds?|secs?|dollars?|cents?|percent)(?!\w)|[%°$]|厘米|分钟|千克|小时", re.I),
    "approximation_cue": re.compile(r"\b(?:approx|approximately|roughly|about|rounded|rounding)\b|≈|\\approx|大约|近似", re.I),
    "temporal_or_update_cue": re.compile(r"\b(?:initially|at first|later|remaining|currently|now|before|after)\b|现在|后来|原来|剩余", re.I),
    "non_atomic_expression_cue": re.compile(r"\\(?:sqrt|log|sin|cos)|\bsqrt\b|\^|\*\*|√", re.I),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalize(raw):
    if "frac" in raw:
        numbers = re.findall(r"[+-]?\d+", raw)
        result = Fraction(int(numbers[0]), int(numbers[1]))
        if raw.startswith("-"):
            result = -result
    else:
        cleaned = re.sub(r"\s+", "", raw).replace(",", "")
        percent = cleaned.endswith("%")
        result = Fraction(cleaned[:-1] if percent else cleaned)
        if percent:
            result /= 100
    return str(result)


def mentions(text, offset=0):
    output = []
    for match in NUMBER.finditer(text):
        try:
            value = normalize(match.group())
        except (ValueError, ZeroDivisionError):
            value = None
        output.append({"raw": match.group(), "value_rational": value,
                       "parse_status": "PARSED_ATOMIC_LITERAL" if value is not None else "UNRESOLVED_LITERAL",
                       "start": offset+match.start(), "end": offset+match.end()})
    return output


def segments(text, mode="paragraph"):
    cuts = []
    if mode == "paragraph":
        start = 0
        for match in re.finditer(r"\n[ \t]*\n", text):
            cuts.append((start, match.start()))
            start = match.end()
        cuts.append((start, len(text)))
    else:
        start = 0
        for line in text.splitlines(keepends=True):
            cuts.append((start, start+len(line)))
            start += len(line)
    result = []
    for start, end in cuts:
        body = text[start:end]
        left = len(body)-len(body.lstrip())
        right = len(body.rstrip())
        if right > left:
            begin, finish = start+left, start+right
            result.append({"unit_id": len(result), "start": begin, "end": finish,
                           "text": text[begin:finish]})
    return result


def candidate_graph(question, text, mode="paragraph"):
    question_mentions = mentions(question)
    question_values = {m["value_rational"] for m in question_mentions if m["value_rational"] is not None}
    units = segments(text, mode)
    first = {}
    prior_units = collections.defaultdict(set)
    edges = []
    edge_keys = set()
    question_value_mentions = new_value_mentions = unparseable_mentions = 0
    for unit in units:
        numbers = mentions(unit["text"], unit["start"])
        unit["numeric_mentions"] = numbers
        local_counts = collections.Counter(m["value_rational"] for m in numbers)
        unit["snippet"] = unit["text"][:180]
        for mention in numbers:
            value = mention["value_rational"]
            if value is None:
                unparseable_mentions += 1
                continue
            if value in question_values:
                question_value_mentions += 1
                continue
            new_value_mentions += 1
            if value not in first:
                first[value] = {"unit_id": unit["unit_id"], "mention": mention}
            origin = first[value]
            if origin["unit_id"] < unit["unit_id"]:
                key = (origin["unit_id"], unit["unit_id"], value)
                if key not in edge_keys:
                    edge_keys.add(key)
                    source_unit = units[origin["unit_id"]]
                    source_mention = origin["mention"]
                    left_context = text[max(source_unit["start"], source_mention["start"]-75):min(source_unit["end"], source_mention["end"]+75)]
                    right_context = text[max(unit["start"], mention["start"]-75):min(unit["end"], mention["end"]+75)]
                    flags = [name for name, pattern in RISK_PATTERNS.items()
                             if pattern.search(left_context) or pattern.search(right_context)]
                    previous = sorted(i for i in prior_units[value] if i < unit["unit_id"])
                    if len(previous) > 1:
                        flags.append("multiple_prior_numeric_source_units")
                    if local_counts[value] > 1:
                        flags.append("multiple_same_value_mentions_in_target_unit")
                    edges.append({"from_unit": origin["unit_id"], "to_unit": unit["unit_id"],
                                  "value_rational": value,
                                  "source_mention": source_mention, "target_mention": mention,
                                  "prior_same_value_units": previous,
                                  "source_context": left_context, "target_context": right_context,
                                  "risk_flags_heuristic_only": flags,
                                  "semantic_status": "UNKNOWN_UNREVIEWED",
                                  "edge_type": "first_trace_only_numeric_value_reappearance"})
            prior_units[value].add(unit["unit_id"])
    for unit in units:
        del unit["text"]
    return {"segmentation": mode, "question_values_rational": sorted(question_values),
            "units": units, "candidate_edges": edges,
            "metadata": {"unit_count": len(units), "numeric_mentions": sum(len(u["numeric_mentions"]) for u in units),
                         "unparseable_numeric_literal_mentions": unparseable_mentions,
                         "unparseable_question_literal_mentions": sum(m["value_rational"] is None for m in question_mentions),
                         "question_value_mentions_excluded": question_value_mentions,
                         "trace_only_value_mentions": new_value_mentions,
                         "distinct_trace_only_values": len(first), "candidate_edge_count": len(edges)}}


# These are human-authored logical counterexamples, not natural-data gold.
COUNTEREXAMPLES = [
    {"id":"positive_explicit_use", "question":"Find a total and then double it.", "trace":"The intermediate total is 7.\n\nTwice this total is 7*2=14.", "expected_support_edges":[[0,1]], "must_find":[0,1], "reason":"Positive control: an explicit same-quantity use."},
    {"id":"same_value_collision", "question":"Compare two unrelated quantities.", "trace":"The bus fare is 6 dollars.\n\nIndependently, the box contains 6 coins.", "expected_support_edges":[], "must_spuriously_find":[0,1], "reason":"Equal value does not establish a reference or derivation."},
    {"id":"negated_old_claim", "question":"Multiply the given factors.", "trace":"The product is 15.\n\n15 is wrong; the valid multiplication gives 12.", "expected_support_edges":[], "must_spuriously_find":[0,1], "other_reference_type":"rejected_claim", "reason":"A rejection is a mention/contrast edge, not active numeric support."},
    {"id":"units_collide", "question":"Track a length and a mass.", "trace":"The rod length is 8 cm.\n\nIndependently the parcel mass is 8 kg.", "expected_support_edges":[], "must_spuriously_find":[0,1], "reason":"Dimensioned quantities with the same number differ."},
    {"id":"branch_scope_collision", "question":"Consider separate alternatives.", "trace":"Assuming the door is open, the count is 9.\n\nIn the other independent case the count is also 9.", "expected_support_edges":[], "must_spuriously_find":[0,1], "reason":"Different conditional scopes are not one binding."},
    {"id":"first_occurrence_not_actual_source", "question":"Track two unrelated branches.", "trace":"The left-branch length is 6.\n\nIndependently the right-branch price is 6.\n\nDouble the right-branch price: 6*2=12.", "expected_support_edges":[[1,2]], "must_spuriously_find":[0,2], "must_miss":[1,2], "reason":"The actual referent is a later independent occurrence, not the first global number."},
    {"id":"question_number_used_as_new_quantity", "question":"There are 3 red beads; separately find a quotient and multiply it by 7.", "trace":"The independently computed quotient is 3.\n\nUse this quotient: 3*7=21.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"Being in the question as a different quantity must not suppress a derived binding."},
    {"id":"implicit_pronoun", "question":"Find a count and then double the result.", "trace":"The computed count is 7.\n\nDouble that result to obtain 14.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"Coreference need not repeat the numeric literal."},
    {"id":"equivalent_expression", "question":"Evaluate an intermediate power, then add a unit.", "trace":"The intermediate value is 2^3.\n\nAdding a unit to that value gives 8+1=9.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"Atomic numeric tokens do not evaluate symbolic equivalence."},
    {"id":"number_word", "question":"Compute a share and use it.", "trace":"The computed share is one half.\n\nUsing that share gives 0.5*10=5.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"Number words and aliases can carry the dependency."},
    {"id":"unit_conversion", "question":"Compute a duration and express it in another unit.", "trace":"The calculated duration is 30 minutes.\n\nIn hours, that duration is 0.5.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"Semantic equality may require unit conversion, not equal raw magnitudes."},
    {"id":"approximation_not_identity", "question":"Keep exact and approximate cases separate.", "trace":"The exact benchmark is 3.\n\nAn unrelated estimate is about 3 after rounding.", "expected_support_edges":[], "must_spuriously_find":[0,1], "reason":"Rounded coincidence is not a unique provenance key."},
    {"id":"conditional_question_value", "question":"If open the width is 3; otherwise it is 5. Use the closed case.", "trace":"The door is closed, so the applicable width is 5.\n\nUse this applicable width: 5*2=10.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"A question value needs its condition; resolving that condition is an intermediate step."},
    {"id":"dynamic_initial_question_fact", "question":"Initially there are 10 apples; later some are removed.", "trace":"After removing some apples there are 7 left.\n\nAfter returning some, there are 9 now.", "expected_support_edges":[[0,1]], "must_miss":[0,1], "reason":"Initial stock=10 remains a historical fact, not current stock=10 at every later time."},
    {"id":"list_marker_collision", "question":"Compare unrelated steps.", "trace":"1. Compute the left branch separately.\n\n1. Start a new unrelated list for the right branch.", "expected_support_edges":[], "must_spuriously_find":[0,1], "reason":"Enumeration numerals are not derived quantities."},
    {"id":"rational_normalization_positive", "question":"Compute a ratio and use it.", "trace":"The ratio is 1/2.\n\nUse the same ratio: 0.5*6=3.", "expected_support_edges":[[0,1]], "must_find":[0,1], "reason":"Exact rational normalization handles this limited notation change only."},
]


def run_counterexamples():
    results = []
    for case in COUNTEREXAMPLES:
        graph = candidate_graph(case["question"], case["trace"])
        pairs = {(e["from_unit"],e["to_unit"]) for e in graph["candidate_edges"]}
        checks = {}
        for field in ["must_find", "must_spuriously_find"]:
            if field in case:
                checks[field] = tuple(case[field]) in pairs
        if "must_miss" in case:
            checks["must_miss"] = tuple(case["must_miss"]) not in pairs
        if not all(checks.values()):
            raise AssertionError((case["id"], pairs, checks))
        results.append({"id":case["id"], "expected_support_edges_hand_authored":case["expected_support_edges"],
                        "heuristic_pairs":[list(p) for p in sorted(pairs)], "checks":checks,
                        "status":"CONSTRUCTED_CONTROL_NOT_NATURAL_LABEL", "reason":case["reason"]})
    (BASE/"numeric_provenance_counterexamples.json").write_text(json.dumps(COUNTEREXAMPLES,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (BASE/"numeric_provenance_counterexample_results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return results


def main():
    manifest_before = sha(MANIFEST.read_bytes())
    if manifest_before != EXPECTED_MANIFEST_SHA:
        raise ValueError("Frozen P1 manifest identity mismatch")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = {case["problem_id"]:case for case in manifest["cases"]}
    source_rows = {}
    for path_string, expected_sha in manifest["eligible_pool"]["source_file_sha256"].items():
        path = Path(path_string)
        if sha(path.read_bytes()) != expected_sha:
            raise ValueError("Original trajectory source SHA mismatch")
        with path.open("rb") as stream:
            for line_number, raw in enumerate(stream,1):
                if not raw.strip():continue
                row = json.loads(raw)
                if row.get("method") == "full" and row["problem_id"] in selected:
                    case = selected[row["problem_id"]]
                    assert line_number == case["source_line_number_1based"]
                    assert sha(raw) == case["source_line_sha256_including_line_ending"]
                    assert sha(row["trace"]["text"].encode()) == case["trace_text_sha256_utf8"]
                    source_rows[row["problem_id"]] = row
    qpath = Path(manifest["eligible_pool"]["question_source_path"])
    assert sha(qpath.read_bytes()) == manifest["eligible_pool"]["question_source_sha256"]
    questions = {}
    for raw in qpath.read_bytes().splitlines(keepends=True):
        if raw.strip():
            row = json.loads(raw)
            if row["problem_id"] in selected:
                assert sha(raw) == selected[row["problem_id"]]["question_origin"]["source_line_sha256_including_line_ending"]
                questions[row["problem_id"]] = row["question"]
    controls = run_counterexamples()
    totals = collections.Counter()
    risks = collections.Counter()
    case_stats = []
    graph_path = BASE/"P1_heuristic_numeric_candidate_graphs.jsonl"
    with graph_path.open("w",encoding="utf-8",newline="\n") as output:
        for case in manifest["cases"]:
            pid = case["problem_id"]
            row = source_rows[pid]
            primary = candidate_graph(questions[pid], row["trace"]["text"], "paragraph")
            sensitivity = candidate_graph(questions[pid], row["trace"]["text"], "line")
            edges = primary["candidate_edges"]
            flags_per_case = collections.Counter(flag for edge in edges for flag in edge["risk_flags_heuristic_only"])
            flagged = sum(bool(edge["risk_flags_heuristic_only"]) for edge in edges)
            details = {"problem_id":pid,"sample_rank_1based":case["sample_rank_1based"],
                       "generation_policy":case["generation_policy"],"uninterrupted_native_episode":False,
                       "source_path":case["source_path"],"source_line_number_1based":case["source_line_number_1based"],
                       "source_file_sha256":case["source_file_sha256"],"source_line_sha256":case["source_line_sha256_including_line_ending"],
                       "trace_text_sha256_utf8":case["trace_text_sha256_utf8"],
                       "trace_length_censored":case["trace_length_censored"],
                       "graph_status":"HEURISTIC_NUMERIC_REAPPEARANCE_ONLY; ALL_EDGES_UNKNOWN_UNREVIEWED",
                       "automatic_trigger_allowed":False,"primary_graph":primary,
                       "line_segmentation_sensitivity_metadata":sensitivity["metadata"]}
            output.write(json.dumps(details,ensure_ascii=False,separators=(",",":"))+"\n")
            stats={"problem_id":pid,**primary["metadata"],"candidate_edges_with_risk_flag":flagged,
                   "candidate_edges_without_surface_risk_flag":len(edges)-flagged,
                   "risk_flag_counts":dict(flags_per_case),
                   "line_unit_count":sensitivity["metadata"]["unit_count"],
                   "line_candidate_edge_count":sensitivity["metadata"]["candidate_edge_count"],
                   "cap":case["trace_length_censored"]}
            case_stats.append(stats)
            for key,value in primary["metadata"].items():totals[key]+=value
            totals["line_unit_count"]+=stats["line_unit_count"]
            totals["line_candidate_edge_count"]+=stats["line_candidate_edge_count"]
            totals["candidate_edges_with_any_surface_risk"]+=flagged
            totals["candidate_edges_without_surface_risk"]+=len(edges)-flagged
            risks.update(flags_per_case)
    assert len(case_stats)==100 and sha(MANIFEST.read_bytes())==manifest_before
    summary={"scope":"CPU-only heuristic numeric provenance feasibility audit; not gold dependency/event/causal rates",
             "source_sha256":sha(Path(__file__).read_bytes()),"frozen_P1_manifest_sha256":manifest_before,
             "frozen_P1_manifest_unchanged":True,"case_count":100,
             "cap_count_retained":sum(c["trace_length_censored"] for c in manifest["cases"]),
             "question_and_trace_source_hashes_verified":True,
             "excluded_input_fields":["gold","correct","grade","answer","policy decisions","extra probes"],
             "counterexamples_checked":len(controls),"counterexample_checks_pass":True,
             "primary_segmentation":"nonempty blank-line-delimited paragraphs; not certified semantic steps",
             "sensitivity_segmentation":"nonempty lines; count sensitivity only",
             "numeric_normalization":"Exact rational form of atomic integers/decimals/simple fractions/scientific notation/percent; no units/entities/expression evaluation",
             "totals_heuristic_only":dict(totals),"surface_risk_flag_counts_not_semantic_labels":dict(risks),
             "all_candidate_semantic_edges_currently_unknown_unreviewed":totals["candidate_edge_count"],
             "no_candidate_is_not_evidence_of_no_dependency":True,
             "automatic_graph_trigger_forbidden":True,"natural_event_rate":"NOT_AUDITED",
             "candidate_graph_jsonl_sha256":sha(graph_path.read_bytes()),"per_case_heuristic_counts":case_stats}
    (BASE/"P1_heuristic_numeric_candidate_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in ["per_case_heuristic_counts","excluded_input_fields"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
