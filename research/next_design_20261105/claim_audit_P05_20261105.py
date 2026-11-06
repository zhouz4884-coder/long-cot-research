"""Read-only CPU audit of P0.5 mechanism claims against the completed P0.

Uses only the Python standard library. Never imports torch, accesses a GPU or
network, or writes into the source/result directory. Outputs stay beside this file.
"""

import ast
import hashlib
import json
import re
from pathlib import Path


OUT = Path(__file__).resolve().parent
OLD = OUT.parent / "direction_selection_20261105"
RUN = OLD / "p0_qwen3_4b_fp16_01"
ARMS = ["full", "target_late", "target_early_reprefill", "random_late", "random_early_reprefill"]


def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def names(expression):
    return sorted({n.id for n in ast.walk(ast.parse(expression, mode="eval")) if isinstance(n, ast.Name)})


def evaluate(expression, values):
    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and type(n.value) is int:
            return n.value
        if isinstance(n, ast.Name) and n.id in values:
            return values[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return walk(n.operand) * (1 if isinstance(n.op, ast.UAdd) else -1)
        if isinstance(n, ast.BinOp):
            a, b = walk(n.left), walk(n.right)
            if isinstance(n.op, ast.Add):
                return a+b
            if isinstance(n.op, ast.Sub):
                return a-b
            if isinstance(n.op, ast.Mult):
                return a*b
            if isinstance(n.op, ast.FloorDiv) and b and a % b == 0:
                return a//b
        raise ValueError(ast.dump(n))
    return walk(ast.parse(expression, mode="eval"))


def evaluate_dag(definitions, root_override=None):
    vals = {}
    for d in definitions:
        name = d["variable"]
        vals[name] = root_override if name == "x" and root_override is not None else evaluate(d["expression"], vals)
    return vals


def closure(graph, roots):
    result = set(roots)
    changed = True
    while changed:
        changed = False
        for node, parents in graph.items():
            if node not in result and result.intersection(parents):
                result.add(node)
                changed = True
    return sorted(result)


def bare_integer(text):
    # Presentation audit only: remove at most one terminal full stop, then demand
    # a whole integer. No equation solver, answer search, or gold-dependent rule.
    value = text.strip()
    if value.endswith(("。", ".")):
        value = value[:-1].strip()
    return int(value) if re.fullmatch(r"[+-]?\d+", value) else None


def ints(text):
    return [int(x) for x in re.findall(r"(?<![A-Za-z\d])[+-]?\d+", text)]


def main():
    payload, manifest = read(OLD/"proposed_p0_cases.json"), read(RUN/"manifest.json")
    by_id = {c["case_id"]: c for c in payload["cases"]}
    order = manifest["executed_order"]
    frozen_files = [OLD/"proposed_p0_cases.json", OLD/"real_model_p0.py", RUN/"manifest.json", RUN/"summary.json", RUN/"RESULT.md"]
    frozen_files += [RUN/(cid+suffix) for cid in order for suffix in (".json", "_readout_logits.npz")]
    before = {str(p): sha(p) for p in frozen_files}
    facts, all_texts = [], []
    full_e_old, full_e_correct, full_e_other, full_e_equation = [], [], [], []
    target_w_revision_final_matches = []
    for cid in order:
        case, record = by_id[cid], read(RUN/(cid+".json"))
        definitions, rendering = case["definitions"], record["rendering"]
        graph = {d["variable"]: names(d["expression"]) for d in definitions}
        assert graph == {"x": [], "y": ["x"], "z": ["y"]}
        exact = evaluate_dag(definitions)
        old = evaluate_dag(definitions, case["old_root_value"])
        revised = evaluate_dag(definitions, case["revision_root_value"])
        assert exact == case["oracle_values"] and exact["z"] == case["required_final_value"]
        assertions = {m.group(1): int(m.group(2)) for m in re.finditer(r"([xyz])=([+-]?\d+)", case["old_branch"])}
        assert assertions == old
        fault_closure = closure(graph, ["x"])
        retained_shared = sorted(set(assertions)-set(fault_closure))
        direct_only = sorted({"x"} | {n for n, ps in graph.items() if "x" in ps})
        direct_still_dependent = sorted(set(fault_closure)-set(direct_only))
        pieces, segments = rendering["rendered_pieces"], rendering["segments"]
        assert pieces["B"] == case["old_branch"] and pieces["R"] == "\n"+case["revision"]
        assert pieces["U"] == "\n继续依据题目给定定义进行核算。\n"*4
        assert case["question"] in pieces["P"]
        all_defs_visible = all(d["variable"]+"="+d["expression"] in pieces["P"] for d in definitions)
        pcols = set(range(*segments["P"]))
        assert not pcols.intersection(rendering["target_columns"])
        assert not pcols.intersection(rendering["random_columns"])
        assert all_defs_visible and not ints(pieces["U"])
        outputs = {}
        for arm in ARMS:
            out = record["arms"][arm]["greedy"]
            outputs[arm] = out["text"]
            all_texts.append({"case_id": cid, "arm": arm, "text": out["text"],
                "new_tokens": out["new_tokens"], "additional_forward_tokens": out["additional_forward_tokens"],
                "stop_reason": out["stop_reason"], "original_strict_integer": out["strict_integer"],
                "presentation_bare_integer": bare_integer(out["text"])})
            if cid.startswith("W") and arm in ("target_late", "target_early_reprefill"):
                # Equality is checked only where presentation is a bare integer.
                # The explicit W02 late equation is separately verified below.
                if bare_integer(out["text"]) == revised["z"]:
                    target_w_revision_final_matches.append({"case_id": cid, "arm": arm})
        if cid.startswith("E"):
            value = bare_integer(outputs["full"])
            assert value is not None
            if value == old["z"]:
                full_e_old.append(cid)
            elif value == exact["z"]:
                full_e_correct.append(cid)
            else:
                full_e_other.append(cid)
            full_e_equation.append({"case_id": cid, "bare_final_integer": value,
                "new_tokens": record["arms"]["full"]["greedy"]["new_tokens"],
                "additional_forward_tokens": record["arms"]["full"]["greedy"]["additional_forward_tokens"]})
        facts.append({"case_id": cid, "group": case["group"], "P": pieces["P"], "B": pieces["B"],
            "U": pieces["U"], "R": pieces["R"], "S": pieces["S"], "definitions": definitions,
            "dependency_parents": graph, "exact_values": exact, "old_values": old, "revision_implied_values": revised,
            "dispute_x_transitive_closure": fault_closure, "old_B_assertions_outside_closure_B_shared": retained_shared,
            "root_plus_direct_children_only": direct_only, "invalid_descendants_left_by_direct_only": direct_still_dependent,
            "actually_wrong_old_assertions": sorted(n for n in old if old[n] != exact[n]),
            "U_numeric_literals": ints(pieces["U"]), "U_variable_names": re.findall(r"\b[xyz]\b", pieces["U"]),
            "P_preserves_all_definition_strings": all_defs_visible, "P_columns_never_masked": True,
            "target_equals_entire_B_segment": rendering["target_columns"] == list(range(*segments["B"])),
            "outputs": outputs})
    e02 = next(x for x in facts if x["case_id"] == "E02")
    assert e02["old_values"] == {"x":24,"y":15,"z":30}
    assert e02["revision_implied_values"] == {"x":28,"y":19,"z":38}
    assert e02["outputs"]["target_late"] == "28*2=56。"
    assert 28 not in ints(e02["B"]) and 28 in ints(e02["R"]) and not ints(e02["U"])
    w02 = next(x for x in facts if x["case_id"] == "W02")
    assert w02["outputs"]["target_late"] == "2*8+3=19。" and w02["revision_implied_values"]["z"] == 19
    target_w_revision_final_matches.append({"case_id":"W02","arm":"target_late",
        "manual_unambiguous_equation_check":"2*8+3=19; exact revised DAG output is 19"})
    assert len(target_w_revision_final_matches) == 1
    assert len(all_texts) == 80 and all(not x["old_B_assertions_outside_closure_B_shared"] for x in facts)
    after = {str(p):sha(p) for p in frozen_files}
    assert before == after
    source_text = (OLD/"real_model_p0.py").read_text(encoding="utf-8")
    assert 'VISIBLE_FIELDS = ("question", "old_branch", "revision")' in source_text
    report = {
        "schema_version":1,
        "status":"PASS_READ_ONLY_CPU_CLAIM_AUDIT",
        "scope":"Actual 16 cases, P/B/U/R/S renders, runner source and all 80 saved outputs; no GPU/network/new generation.",
        "claims_input":"Paraphrased new-user-claim summary supplied by parent agent; not a verbatim user quotation.",
        "input_json_sha256":sha(OLD/"proposed_p0_cases.json"),
        "runner_source_sha256":sha(OLD/"real_model_p0.py"),
        "runner_hash_matches_actual_manifest":sha(OLD/"real_model_p0.py")==manifest["source_sha256"],
        "audit_script_sha256":sha(Path(__file__)),
        "original_files_unchanged":before==after,"original_frozen_file_hashes":before,
        "facts_summary":{
            "cases":len(facts),"outputs_read":len(all_texts),"U_contains_numeric_literals_cases":sum(bool(x["U_numeric_literals"]) for x in facts),
            "all_dependency_graphs_x_to_y_to_z":True,
            "cases_with_nonempty_old_B_shared_after_x_closure":sum(bool(x["old_B_assertions_outside_closure_B_shared"]) for x in facts),
            "P_all_definitions_visible_cases":sum(x["P_preserves_all_definition_strings"] for x in facts),
            "target_already_masks_entire_B_cases":sum(x["target_equals_entire_B_segment"] for x in facts),
            "full_E_bare_integer_style_cases":len(full_e_equation),
            "full_E_equal_old_final_cases":full_e_old,"full_E_equal_correct_final_cases":full_e_correct,
            "full_E_neither_old_nor_correct_cases":full_e_other,
            "full_E_decode_steps":full_e_equation,
            "W_target_outputs_equal_complete_wrong_revision_DAG":target_w_revision_final_matches,
            "W_target_output_denominator":8,
        },
        "claim_audits":[
            {"claim":"Full emits one integer because one token forward cannot compute multi-step arithmetic and therefore copies old answer",
             "verdict":"FORMAT_OBSERVED__COMPUTATIONAL_AND_COPY_CAUSE_UNSUPPORTED",
             "evidence":"All eight E Full outputs are bare integers plus punctuation, but only E01/E03/E06/E07 equal the old terminal value; E05 is correct. Decode uses multiple token forwards, and output length is not hidden arithmetic depth."},
            {"claim":"E02 late's 28 in 28*2=56 is an old intermediate value left in U",
             "verdict":"CONTRADICTED_BY_ACTUAL_RENDER",
             "evidence":"U has no numbers; B has x24,y15,z30. R newly states x28. Equation matches applying outer z=2*y to the revised x as if it were y, skipping y=x-9; this is a compatible variable-binding/omitted-composition description, not established KV-source causality."},
            {"claim":"Early rescues E02/E03/E05/E07 because lack of copyable result forces explicit re-derivation",
             "verdict":"SUCCESS_AND_EQUATIONS_OBSERVED__FORCING_CAUSE_UNTESTED",
             "evidence":"Those early outputs contain correct substitutions, but the four are not four gains over Full: E05 Full is already correct (28), Late harms it (34), Early restores it (28). E07 Late and Early already give the identical correct equation (37). Only E02/E03 are Early repairs of both Full and Late. Output format was not randomized; fresh state, attention and generated form change together."},
            {"claim":"E01/C04 failures prove whole-B deletion removed independent y/z evidence",
             "verdict":"INDEPENDENCE_FALSE__CAUSAL_PROOF_UNSUPPORTED",
             "evidence":"All cases have x->y->z. E01 old y38/z33 descend from wrong x12; C04 values are valid descendants of correct x17. In both, P retains every definition. 11-5/17-9 omit the y transformation, but do not identify removal of independent y/z."},
            {"claim":"After deleting B in W, R is the only evidence left; trusting latest revision must fail by theorem",
             "verdict":"ONLY_EVIDENCE_FALSE__GENERAL_THEOREM_NOT_ESTABLISHED",
             "evidence":"P and all definitions remain readable in all arms. Only one of eight target W outputs equals the full result implied by the wrong revision; several instead omit a transformation. A conditional statement assuming wrong revision and unquestioning use is not a new explanation of these outputs."},
            {"claim":"Same 16 cases can compare whole-B against closed FaultOnly retaining independent y/z and strictly prove half of failures are deletion of independent support",
             "verdict":"DESIGN_NOT_IDENTIFIABLE_ON_CURRENT_DAG",
             "evidence":"Closure of disputed x is x,y,z and leaves no B_shared in 16/16. Root+direct child deletes x,y but retains stale descendant z. Closed FaultOnly and whole-B have the same asserted content; differences from delimiter/operator tokens would be a different hypothesis. No predeclared result can strictly prove a fixed half attribution."},
        ],
        "suggested_minimal_new_graph":{
            "question_definitions":[{"variable":"r","expression":"4+5"},{"variable":"x","expression":"7*4"},
                                    {"variable":"y","expression":"x-9"},{"variable":"u","expression":"2*y"},
                                    {"variable":"z","expression":"u+r"}],
            "old_assertions":{"r":9,"x":24,"y":15,"u":30,"z":39},
            "shared_visible_revision":"Wait, x should be 28; recompute its consequences from the original definitions.",
            "correct_values":{"x":28,"y":19,"u":38,"r":9,"z":47},
            "fault_closure":["x","y","u","z"],"genuinely_independent_old_B_shared":["r"],
            "recommended_serialization":"P | B_shared(r=9) | B_bad(x=24,y=15,u=30,z=39) | U | R | S",
            "reason":"Retaining r is actually independent of the disputed x. Place shared r before the bad branch to prevent its cached state from already reading that branch. Its original definition remains visible in P for every arm; this tests reuse of valid work, not withholding the task specification.",
            "if_shared_is_after_bad_branch":"Semantic independence alone does not make its KV independent. Recompute retained downstream r from the clean visible prefix before calling its state clean.",
        },
        "rescue_reference_audit":[{"case_id":cid,
            "full_already_correct_bare_integer":bare_integer(next(x for x in facts if x['case_id']==cid)['outputs']['full']) == next(x for x in facts if x['case_id']==cid)['exact_values']['z'],
            "late_and_early_identical_text":next(x for x in facts if x['case_id']==cid)['outputs']['target_late'] == next(x for x in facts if x['case_id']==cid)['outputs']['target_early_reprefill'],
            "outputs":next(x for x in facts if x['case_id']==cid)['outputs']}
            for cid in ['E02','E03','E05','E07']],
        "design_recommendations":[
            "Do not GPU-run WholeB vs purported closed FaultOnly on the current 16-case x->y->z set; the proposed independent-support contrast is empty.",
            "If testing output format, use a separate frozen 2x2 context(full vs whole-B early) x format(integer vs one-line substitution); no new correct y/z in instructions, record actual tokens, and do not call format-mediated gains proof of latent single-forward incapacity.",
            "For an actual shared-support experiment add an independent root r and a final merge z=u+r; compute closure from known structural provenance, including the final z descendant.",
            "Distinguish semantic dependency closure from dense-Transformer cache dependency: an r statement serialized after a faulty span may have a context-dependent cache despite arithmetic independence.",
            "Hold visible revision/summary token IDs and original positions equal for late-vs-fresh comparisons. A correct new y or z summary is new privileged computation, not preservation of old independent work.",
            "Separate closure-preservation, cache recomputation and output format rather than adding all factors and attributing one combined effect to independent evidence.",
            "Use equal-count, age/contiguity-aware retention controls where possible; keeping r means retaining more valid tokens than deleting all, so mask budget alone does not resolve semantic specificity.",
            "Keep no-error and false-Wait controls, and explicitly mark any oracle-triggered arm as an offline upper bound rather than an online detector.",
        ],
        "per_case_facts":facts,"all_80_outputs":all_texts,
    }
    example = report["suggested_minimal_new_graph"]
    assert evaluate_dag(example["question_definitions"]) == example["correct_values"]
    assert evaluate_dag(example["question_definitions"],24) == example["old_assertions"]
    example_graph = {d["variable"]:names(d["expression"]) for d in example["question_definitions"]}
    assert set(closure(example_graph,["x"])) == set(example["fault_closure"])
    assert set(example["old_assertions"])-set(example["fault_closure"]) == {"r"}
    target = OUT/"claim_audit_P05_20261105.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"output":str(target),"original_files_unchanged":True,
                      "facts_summary":report["facts_summary"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
