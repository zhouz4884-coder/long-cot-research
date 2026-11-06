"""Restricted integer DAG controller and a new, predeclared answer interface.

No LM, hidden group/gold or old-run rescoring is used here. Rules are explicit
synthetic program definitions; this is not a natural-language graph extractor.
"""
import ast
import hashlib
import json
import re

METHODS = ("SharedGFull", "BoundaryProjection", "RawFull")
STYLE = "用必要的简短算式说明，避免复述题干；最后以‘最终答案：整数’结束。"
SYSTEM = "按原题定义求目标。旧记录和修订均可能有错，不能因其位置较晚就默认正确。" + STYLE


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse(expr):
    tree = ast.parse(expr, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
               ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.USub, ast.UAdd)
    if any(not isinstance(n, allowed) for n in ast.walk(tree)):
        raise ValueError("Unsupported rule")
    if any(isinstance(n, ast.Constant) and (type(n.value) is not int or abs(n.value) > 100000) for n in ast.walk(tree)):
        raise ValueError("Integer constants only")
    return tree


def parents(expr):
    return sorted({n.id for n in ast.walk(parse(expr)) if isinstance(n, ast.Name)})


def evaluate(expr, values):
    def visit(n):
        if isinstance(n, ast.Constant): return n.value
        if isinstance(n, ast.Name): return values[n.id]
        if isinstance(n, ast.UnaryOp): return -visit(n.operand) if isinstance(n.op, ast.USub) else visit(n.operand)
        a, b = visit(n.left), visit(n.right)
        if isinstance(n.op, ast.Add): return a + b
        if isinstance(n.op, ast.Sub): return a - b
        if isinstance(n.op, ast.Mult): return a * b
        if isinstance(n.op, ast.FloorDiv): return a // b
        raise ValueError("Unsupported operation")
    result = visit(parse(expr).body)
    if abs(result) > 10**12: raise ValueError("Arithmetic bound")
    return result


def ancestors(rules, node):
    seen, active = set(), set()
    def walk(v):
        if v in active: raise ValueError("Cycle")
        if v in seen: return
        if v not in rules: raise ValueError("Missing rule: " + v)
        active.add(v)
        for parent in parents(rules[v]): walk(parent)
        active.remove(v); seen.add(v)
    walk(node)
    return seen


def ordered(rules, needed):
    left, result = set(needed), []
    while left:
        ready = [v for v in rules if v in left and not (set(parents(rules[v])) & left)]
        if not ready: raise ValueError("Cycle")
        result.extend(ready); left.difference_update(ready)
    return result


def cold(rules):
    values = {}
    for v in ordered(rules, set(rules)): values[v] = evaluate(rules[v], values)
    return values


def project(rules, certificates, goal):
    """Stop the backwards slice at checked nodes; no target arithmetic here."""
    ancestors(rules, goal)  # Full structural closure must be declared, even at cuts.
    pending, boundary = set(), set()
    def visit(v):
        if v in certificates:
            boundary.add(v); return
        if v in pending: return
        pending.add(v)
        for parent in parents(rules[v]): visit(parent)
    visit(goal)
    return {"pending": ordered(rules, pending), "boundary": sorted(boundary),
            "rules": {v: rules[v] for v in ordered(rules, pending)},
            "boundary_values": {v: certificates[v]["value"] for v in sorted(boundary)}, "goal": goal}


def controller(visible):
    rules = visible["rules"]
    old = visible["old_values"]
    proposal = visible["revision"]
    # Scoped checker: x root and every old support of the independent branch r.
    # It NEVER evaluates the x-dependent new target branch.
    support = ancestors(rules, "r")
    if "x" in support or parents(rules["x"]): raise ValueError("Not an independent constant-root control")
    checked, operations = {}, []
    for v in ordered(rules, support | {"x"}):
        val = evaluate(rules[v], checked); checked[v] = val
        operations.append({"node": v, "expression": rules[v], "value": val,
                           "old_literal_matches": old.get(v) == val})
        if v != "x" and old.get(v) != val: raise ValueError("Independent support certificate rejected")
    truth = checked["x"]
    if proposal.get("variable") != "x" or type(proposal.get("value")) is not int:
        verdict = "unknown"
    elif proposal["value"] != truth: verdict = "rejected"
    elif old["x"] == truth: verdict = "nochange"
    else: verdict = "accepted"
    certs = {}
    for v in ("x", "r"):
        closure = ancestors(rules, v)
        certs[v] = {"value": checked[v], "scope": v, "rule_closure_hash": digest({k: rules[k] for k in sorted(closure)}),
                    "version": 1 if v == "x" and old[v] != checked[v] else 0}
    view = project(rules, certs, visible["goal"])
    dirty = []
    if old["x"] != truth:
        dirty = [v for v in rules if "x" in ancestors(rules, v)]
    return {"G": verdict, "certificates": certs, "projection": view, "dirty_old_slots": dirty,
            "checked_operations": operations, "target_branch_evaluations": 0,
            "rule_set_hash": digest(rules), "full_controller_not_shown_to_LM": True}


def verify_certificate_rules(rules, certificates):
    for v, cert in certificates.items():
        if cert["scope"] != v: raise ValueError("Scope mismatch")
        closure = ancestors(rules, v)
        if cert["rule_closure_hash"] != digest({k: rules[k] for k in sorted(closure)}):
            raise ValueError("Rule version mismatch")


def projected_text(view):
    return ("已核验且当前有效：" + "，".join(f"{v}={view['boundary_values'][v]}" for v in view["boundary"]) + "。\n"
            + "目标：" + view["goal"] + "。仅需按当前规则计算：\n"
            + "\n".join(v + "=" + expr for v, expr in view["rules"].items()) + "\n" + STYLE)


def render(visible, method, state=None):
    """Only whitelisted visible fields, never a complete evaluator record."""
    if method in ("SharedGFull", "BoundaryProjection"):
        if state is None or state["rule_set_hash"] != digest(visible["rules"]):
            raise ValueError("Controller rule version mismatch")
        verify_certificate_rules(visible["rules"], state["certificates"])
        if state["projection"] != project(visible["rules"], state["certificates"], visible["goal"]):
            raise ValueError("Controller goal/boundary projection mismatch")
    question = "按整数算术，//表示向下取整。依次定义：\n" + "\n".join(k+"="+v for k,v in visible["rules"].items()) + "\n求" + visible["goal"] + "。"
    if method == "RestartP": content = question + "\n" + STYLE
    elif method == "BoundaryProjection":
        if state is None or state["G"] == "unknown": raise ValueError("No uncertified projection fallback")
        content = projected_text(state["projection"])
    else:
        content = question + "\n旧计算记录（候选）：\n" + "；".join(f"{k}={v}" for k,v in visible["old_values"].items())
        content += "\n修订记录：" + visible["revision"]["variable"] + "=" + str(visible["revision"]["value"]) + "。"
        if method == "SharedGFull":
            if state is None: raise ValueError("Missing G")
            content += "\n外部核验：修订判定=" + state["G"] + "；当前x=" + str(state["certificates"]["x"]["value"])
            content += "，独立分支r=" + str(state["certificates"]["r"]["value"]) + "。仅这两项及r的支持算式已核验；可直接复用，不要求从头重算。"
        elif method != "RawFull": raise ValueError(method)
        content += "\n" + STYLE
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def extract_integer(text):
    """New pilot interface only; no posthoc regrade of Phase5-A or historical MATH."""
    text = text.strip().replace("−", "-")
    if re.fullmatch(r"[+-]?\d+[。.!！]?", text):
        return {"value": int(text.rstrip("。.!！")), "method": "whole_integer"}
    candidate = text
    if candidate.startswith("```json\n") and candidate.endswith("\n```"):
        candidate = candidate[8:-4].strip()
    if candidate.startswith("{"):
        try:
            def no_duplicates(pairs):
                d = {}
                for k,v in pairs:
                    if k in d: raise ValueError("Duplicate JSON key")
                    d[k]=v
                return d
            obj = json.loads(candidate, object_pairs_hook=no_duplicates)
            if isinstance(obj, dict) and type(obj.get("final_answer")) is int:
                return {"value": obj["final_answer"], "method": "complete_JSON_final_answer"}
        except (ValueError, TypeError): pass
        return {"value": None, "method": "invalid_or_ambiguous_JSON"}
    pattern = r"(?:最终答案\s*[:：]\s*([+-]?\d+)|\\boxed\{\s*([+-]?\d+)\s*\})"
    matches = list(re.finditer(pattern, text))
    if matches:
        values = [int(m[1] if m[1] is not None else m[2]) for m in matches]
        tail = text[matches[-1].end():].strip()
        # Transparent closing Markdown/math delimiters do not change the answer.
        for delimiter in ("**", "`", "$", r"\]", r"\)"):
            tail = tail.replace(delimiter, "")
        tail = tail.strip()
        if len(set(values)) == 1 and tail in ("", "。", ".", "!", "！"):
            return {"value": values[0], "method": "terminal_marker_or_boxed"}
    return {"value": None, "method": "unresolved"}


def build_dataset():
    rules = {"s0": "19", "s1": "s0+7", "s2": "s1*3", "s3": "s2-11", "s4": "s3+29", "s5": "s4//4",
             "s6": "s5*5", "s7": "s6-17", "s8": "s7+13", "s9": "s8//2", "s10": "s9*3", "r": "s10-21",
             "x": "37-14", "a": "x+11", "b": "3*a-7", "c": "b*2", "d": "c+17", "e": "d//3", "f": "e*4-9", "z": "f+r"}
    actual = cold(rules)
    cases = []
    for group in ("E", "C", "W"):
        old = dict(actual)
        if group == "E":
            old["x"] = actual["x"] + 1
            for v in ("a", "b", "c", "d", "e", "f", "z"): old[v] = evaluate(rules[v], old)
        visible = {"rules": rules, "old_values": old, "revision": {"variable": "x", "value": actual["x"] + (group == "W")}, "goal": "z"}
        cases.append({"case_id": "LongR_" + group, "visible": visible, "evaluation_only": {"group": group, "gold": actual["z"], "old_z": old["z"]}})
    return {"scope": "One explicit20-definition arithmetic program:12-step independent support plusroot and7target definitions; 3 related states, not3 independent tasks.",
            "cases": cases, "independent_programs": 1, "new_to_model": True, "natural_graph_extraction": False}
