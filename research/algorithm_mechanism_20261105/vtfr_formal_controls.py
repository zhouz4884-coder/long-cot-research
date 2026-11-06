"""Standard-library CPU counterexamples and bounded controls for VTFR.

No model, GPU, network, annotation task, or external execution. The toy contextual
state is an abstract counterexample, not a simulation of a trained Transformer.
"""

import ast
import copy
import hashlib
import heapq
import itertools
import json
import math
from pathlib import Path


OUT = Path(__file__).resolve().parent
ATTACHMENT = Path(r"C:\Users\LENOVO\.codex\attachments\50312571-fa7b-44d4-9d91-4d23e49fe48d\已粘贴的文本.txt")


def arithmetic(expression, values):
    def walk(n):
        if isinstance(n, ast.Constant) and type(n.value) is int:
            return n.value
        if isinstance(n, ast.Name):
            return values[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return walk(n.operand)*(1 if isinstance(n.op, ast.UAdd) else -1)
        if isinstance(n, ast.BinOp):
            a, b = walk(n.left), walk(n.right)
            if isinstance(n.op, ast.Add): return a+b
            if isinstance(n.op, ast.Sub): return a-b
            if isinstance(n.op, ast.Mult): return a*b
            if isinstance(n.op, ast.FloorDiv) and b and a % b == 0: return a//b
        raise ValueError(ast.dump(n))
    return walk(ast.parse(expression, mode="eval").body)


def graph_for(rules, roots):
    graph = {root: [] for root in roots}
    for node, rule in rules.items():
        graph[node] = sorted({n.id for n in ast.walk(ast.parse(rule, mode="eval")) if isinstance(n, ast.Name)})
    missing = set(p for ps in graph.values() for p in ps)-set(graph)
    if missing:
        raise ValueError("Unbound parents: "+str(sorted(missing)))
    return graph


def topological(graph):
    degree = {v: len(ps) for v, ps in graph.items()}
    ready = [v for v in graph if degree[v] == 0]
    heapq.heapify(ready)
    result = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        for child, parents in graph.items():
            if node in parents:
                degree[child] -= 1
                if degree[child] == 0: heapq.heappush(ready, child)
    if len(result) != len(graph):
        raise ValueError("Cycle: "+str(sorted(set(graph)-set(result))))
    return result


def closed_descendants(graph, changed):
    result = set(changed)
    while True:
        new = result | {v for v, parents in graph.items() if result.intersection(parents)}
        if new == result: return result
        result = new


def exact_values(rules, roots):
    graph = graph_for(rules, roots)
    values = dict(roots)
    for node in topological(graph):
        if node in rules:
            values[node] = arithmetic(rules[node], values)
    return values


def initial_store(rules, roots):
    graph, values = graph_for(rules, roots), exact_values(rules, roots)
    return {v: {"value": values[v], "version": 0, "parents": {p: 0 for p in graph[v]}}
            for v in topological(graph)}


def provenance_valid(store, node, seen=None):
    seen = set() if seen is None else set(seen)
    if node in seen: return False
    seen.add(node)
    for parent, version in store[node]["parents"].items():
        if store[parent]["version"] != version or not provenance_valid(store, parent, seen):
            return False
    return True


def verified_replay(rules, roots, old_store, accepted_updates):
    """Assumes updates are certified and exact AST execution is the checker.

    This deliberately does not implement a language-model verifier or claim that
    a text prompt enforces a ready frontier. It is a finite exact reference.
    """
    graph = graph_for(rules, roots)
    topological(graph)  # Reject cycles before attempting a frontier.
    store = copy.deepcopy(old_store)
    invalid = closed_descendants(graph, accepted_updates)
    certified = set(graph)-invalid
    for node, value in accepted_updates.items():
        if node not in roots:
            raise ValueError("This bounded control updates roots only")
        store[node] = {"value":value, "version":store[node]["version"]+1, "parents":{}}
        certified.add(node)
    pending = invalid-set(accepted_updates)
    ready_history, execution = [], []
    while pending:
        ready = sorted(v for v in pending if set(graph[v]) <= certified)
        if not ready:
            raise ValueError("No certified frontier; reject rather than read dirty values")
        ready_history.append(ready)
        node = ready[0]
        assert all(provenance_valid(store, p) for p in graph[node])
        value = arithmetic(rules[node], {v:e["value"] for v,e in store.items() if v in certified})
        store[node] = {"value":value, "version":store[node]["version"]+1,
                       "parents":{p:store[p]["version"] for p in graph[node]}}
        pending.remove(node)
        certified.add(node)
        execution.append(node)
    return store, {"invalidated_old_variables":sorted(invalid), "ready_frontiers":ready_history,
                   "execution_order":execution, "retained":sorted(set(graph)-invalid)}


def main():
    # 1. A normalized conditional likelihood table can favor a false update.
    table = {"4":{"Px":0.1,"Other":0.9}, "5":{"Px":0.9,"Other":0.1}}
    assert all(abs(sum(row.values())-1) < 1e-12 for row in table.values())
    lr = math.log(table["5"]["Px"])-math.log(table["4"]["Px"])
    assert lr > 0 and 5 != arithmetic("2+2", {})
    likelihood = {"Px":"x=2+2", "old":4, "new":5, "normalized_likelihood_table":table,
                  "log_likelihood_ratio_new_over_old":lr, "LR_accepts":True,
                  "exact_constraint_accepts":False, "scope":"Logical counterexample; not a measured LLM probability."}
    # An under-specified local constraint is insufficient even with exact checking.
    local = {"local_constraint":"x*x=1", "global_additional_constraint":"x>0", "candidate":-1,
             "passes_exact_local":(-1)*(-1)==1, "passes_full_constraints":-1>0}
    assert local["passes_exact_local"] and not local["passes_full_constraints"]
    reject_wrong = {"Px":"x=2+2", "old":3, "new":5,
                    "new_rejected":5!=4, "keeping_old_is_correct":3==4,
                    "required_action":"Do not certify old solely because new was rejected; verify old or rebuild/abstain."}
    assert reject_wrong["new_rejected"] and not reject_wrong["keeping_old_is_correct"]

    # 2. More than one direct child must remain in the pending/ready worklist.
    rules = {"a":"x+1", "b":"3*x", "z":"a+b"}
    roots = {"x":1}
    old = initial_store(rules, roots)
    repaired, trace = verified_replay(rules, roots, old, {"x":2})
    assert trace["ready_frontiers"][0] == ["a","b"]
    assert repaired["z"]["value"] == 9 and all(provenance_valid(repaired,v) for v in repaired)
    naive = copy.deepcopy(old)
    naive["x"] = {"value":2,"version":1,"parents":{}}
    naive["a"] = {"value":3,"version":1,"parents":{"x":1}}
    naive["z"] = {"value":naive["a"]["value"]+naive["b"]["value"],
                  "version":1,"parents":{"a":1,"b":0}}
    assert naive["z"]["value"] == 6 and not provenance_valid(naive,"z")
    fork = {"rules":rules,"old_store":old,"accepted_update":{"x":2}, "verified_trace":trace,
            "verified_store":repaired,"single_child_then_sink_mixed_store":naive,
            "naive_z":6,"correct_z":9,"mixed_version_read_is_valid":False}

    # 3. Reachability means possibly invalid, not necessarily a changed number.
    inv_rules, inv_roots = {"a":"x-x","b":"a+7"}, {"x":2}
    inv_old = initial_store(inv_rules, inv_roots)
    inv_new, inv_trace = verified_replay(inv_rules, inv_roots, inv_old, {"x":5})
    assert inv_old["a"]["value"] == inv_new["a"]["value"] == 0
    assert inv_old["b"]["value"] == inv_new["b"]["value"] == 7
    invariant = {"rules":inv_rules,"old_store":inv_old,"new_store":inv_new,"trace":inv_trace,
                 "certificate":"For all integer x, x-x=0; hence b=7.",
                 "scope":"A semantic invariant can preserve numeric truth, but does not certify a context-dependent KV."}

    # 4. A cyclic graph has no topological replay order in the claimed domain.
    cyclic = {"a":["b"],"b":["a"],"r":[]}
    try:
        topological(cyclic)
        raise AssertionError("Expected cycle rejection")
    except ValueError as exc:
        cycle = {"graph":cyclic,"status":"REJECTED_CYCLE","message":str(exc),
                 "required_extension":"An SCC/fixed-point solver with separate uniqueness/convergence conditions, or versioned unrolling."}

    # 5. Rules survive value-version retirement.
    rule_defs = {"y":"x-9","z":"2*y"}
    rule_before = dict(rule_defs)
    s0 = initial_store(rule_defs,{"x":24})
    s1, tr = verified_replay(rule_defs,{"x":24},s0,{"x":28})
    assert rule_defs == rule_before and s1["y"]["value"] == 19 and s1["z"]["value"] == 38
    versions = {"immutable_rules":rule_defs,"old_store":s0,"new_store":s1,"trace":tr,
                "claim":"Retire old x/y/z assertions, not y=x-9 or z=2*y; parent versions prevent stale reads."}

    # 6. Rejecting R in a control plane does not rewind an already appended state.
    def append(cache, label, number=None):
        prior = cache[-1]["hidden"] if cache else 0
        current = number if number is not None else (cache[-1]["current_x"] if cache else None)
        cache.append({"label":label,"hidden":3*prior+(number or 0),"current_x":current})
    pre_r=[]
    append(pre_r,"trusted x=4",4)
    main_cache=copy.deepcopy(pre_r)
    append(main_cache,"proposal R: x=5",5)
    append(main_cache,"neutral successor")
    gate_accepts=False  # Exact gate rejects 5 for x=2+2.
    reject_flag_only_output=main_cache[-1]["current_x"]
    restored=copy.deepcopy(pre_r)
    append(restored,"neutral successor")
    direct_remove_r=[entry for entry in main_cache if entry["label"]!="proposal R: x=5"]
    assert not gate_accepts and reject_flag_only_output==5 and restored[-1]["current_x"]==4
    assert direct_remove_r[-1]["hidden"]==51 and restored[-1]["hidden"]==12
    cache = {"scope":"Abstract deterministic contextual-state counterexample, not a Transformer simulation.",
             "transition":"h_next=3*h_prev+numeric_payload; current_x carries latest assignment",
             "pre_R_snapshot":pre_r,"main_after_R_and_successor":main_cache,"G_accepts_R":gate_accepts,
             "reject_flag_without_rollback_output":reject_flag_only_output,
             "delete_R_row_but_keep_successor_hidden":direct_remove_r[-1]["hidden"],
             "restore_preR_and_rebuild_successor_hidden":restored[-1]["hidden"],
             "proper_rollback_output":restored[-1]["current_x"]}

    # 7. Two different abstract mechanisms give the observed E02 outcome pair.
    def pointer_model(B_visible):
        stage=3 if B_visible else 1
        return 2*28 if stage==3 else 2*(28-9)
    def surface_binding_model(B_visible):
        # No stage variable: a surface-pattern policy selects an outer substitution.
        return 2*28 if B_visible else 2*(28-9)
    equivalent = {"observed_inputs":["B included","B suppressed from encoding"],
                  "pointer_model_outputs":[pointer_model(True),pointer_model(False)],
                  "surface_binding_without_explicit_pointer_outputs":[surface_binding_model(True),surface_binding_model(False)],
                  "scope":"Existence of alternative explanatory models; not either mechanism being measured in Qwen."}
    assert equivalent["pointer_model_outputs"] == equivalent["surface_binding_without_explicit_pointer_outputs"] == [56,38]

    # 8. Finite exact reference tests exercise the assumptions of the soundness lemma.
    bounded=0
    for case_rules, root_names in [({"a":"x+1","b":"3*x","z":"a+b"},["x"]),
        ({"a":"x+1","b":"2*r","z":"a+b"},["x","r"]),
        ({"a":"x-x","b":"a+7"},["x"])]:
        for old_values in itertools.product(range(-2,3),repeat=len(root_names)):
            old_roots=dict(zip(root_names,old_values)); store=initial_store(case_rules,old_roots)
            for new_values in itertools.product(range(-2,3),repeat=len(root_names)):
                new_roots=dict(zip(root_names,new_values))
                updates={v:new_roots[v] for v in root_names if new_roots[v]!=old_roots[v]}
                result, _ = verified_replay(case_rules,old_roots,store,updates)
                assert {v:e["value"] for v,e in result.items()} == exact_values(case_rules,new_roots)
                assert all(provenance_valid(result,v) for v in result)
                bounded += 1
    assert bounded == 675
    output = {
        "status":"PASS_STANDARD_LIBRARY_FORMAL_CONTROLS", "device":"CPU only", "gpu_used":False,
        "network_used":False,"model_used":False,"source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "attachment_sha256":hashlib.sha256(ATTACHMENT.read_bytes()).hexdigest(),
        "likelihood_ratio_is_not_truth":likelihood,"incomplete_local_constraint":local,
        "rejecting_bad_new_does_not_certify_old":reject_wrong,
        "multiple_children_frontier":fork,"indirect_invariant":invariant,"cycle":cycle,
        "rules_and_versioned_values":versions,"rejected_R_already_in_cache":cache,
        "nonunique_pointer_explanation":equivalent,
        "bounded_exact_reference":{"cases":bounded,"root_domain":[-2,-1,0,1,2],
            "program_count":3,"all_replays_match_fresh_exact_evaluation":True,
            "all_parent_versions_valid":True,
            "scope":"Bounded implementation control under exact symbolic assumptions; not a proof of LLM or deployment correctness."},
        "limitations":["No learned verifier calibration was measured.",
            "No neural cache was generated; the abstract state counterexample establishes a missing protocol action only.",
            "The mathematical soundness argument needs the stated pure-DAG/exact-checker assumptions; tests do not replace its proof.",
            "The attachment's P1/GPU/training instructions were not executed."],
    }
    p=OUT/"vtfr_formal_controls.json"
    p.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":output["status"],"bounded_exact_cases":bounded,"LR_wrong_acceptance":lr,
        "fork_bad_z":6,"fork_correct_z":9,"reject_flag_output":5,"proper_rollback_output":4,
        "stale_successor_hidden":51,"rebuilt_successor_hidden":12,"output":str(p)},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
