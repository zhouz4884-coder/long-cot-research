"""Generate and exactly verify 16 handwritten teacher-forced P0 interface cases.

No model, remote platform, training, or sampling is involved. The resulting JSON
is a synthetic mechanism interface set, not a natural long-CoT benchmark.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List


# Handwritten specifications: id, group, x definition, y definition, z definition,
# asserted old x, asserted revision x. Expected outputs are computed independently
# from the original definitions, never selected from a model generation.
SPECS = [
    ("E01", "falsified_old_correct_revision", "18-7", "3*x+2", "y-5", 12, 11),
    ("E02", "falsified_old_correct_revision", "7*4", "x-9", "2*y", 24, 28),
    ("E03", "falsified_old_correct_revision", "45//5", "x*x", "y+6", 8, 9),
    ("E04", "falsified_old_correct_revision", "13+8", "2*x-3", "y+4", 20, 21),
    ("E05", "falsified_old_correct_revision", "6*6", "x//6", "5*y-2", 30, 36),
    ("E06", "falsified_old_correct_revision", "50-17", "x+7", "3*y-1", 32, 33),
    ("E07", "falsified_old_correct_revision", "(9+3)*2", "2*x", "y-11", 22, 24),
    ("E08", "falsified_old_correct_revision", "64//8+5", "x-4", "y*y+1", 12, 13),
    ("C01", "correct_old_no_error_control", "16-9", "4*x", "y+3", 7, 7),
    ("C02", "correct_old_no_error_control", "8*3", "x//4", "3*y-2", 24, 24),
    ("C03", "correct_old_no_error_control", "35//5", "x+8", "2*y", 7, 7),
    ("C04", "correct_old_no_error_control", "11+6", "2*x-5", "y-9", 17, 17),
    ("W01", "wait_wrong_revision_control", "15-6", "3*x", "y+1", 9, 10),
    ("W02", "wait_wrong_revision_control", "9*4", "x//4", "2*y+3", 36, 32),
    ("W03", "wait_wrong_revision_control", "42//7", "x+5", "y*y", 6, 7),
    ("W04", "wait_wrong_revision_control", "(8+5)*2", "x-6", "4*y-1", 26, 24),
]


def exact_integer(expression: str, values: Dict[str, int]) -> int:
    """Evaluate a tiny integer AST; division is accepted only when exact."""
    def visit(node: ast.AST) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp):
            operand = visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.FloorDiv):
                if right == 0 or left % right != 0:
                    raise ValueError("Division must have a nonzero divisor and zero remainder")
                return left // right
        raise ValueError("Unsupported or undefined arithmetic node: " + ast.dump(node))

    return visit(ast.parse(expression, mode="eval").body)


def evaluate_definitions(definitions: List[dict], override_x=None) -> Dict[str, int]:
    values: Dict[str, int] = {}
    for definition in definitions:
        variable = definition["variable"]
        if variable == "x" and override_x is not None:
            value = override_x
        else:
            value = exact_integer(definition["expression"], values)
        if type(value) is not int or variable in values:
            raise ValueError("Definitions must contain distinct integer-valued variables")
        values[variable] = value
    return values


def build_cases() -> dict:
    cases = []
    for case_id, group, x_expr, y_expr, z_expr, old_x, revision_x in SPECS:
        definitions = [
            {"variable": "x", "expression": x_expr},
            {"variable": "y", "expression": y_expr},
            {"variable": "z", "expression": z_expr},
        ]
        oracle = evaluate_definitions(definitions)
        old = evaluate_definitions(definitions, override_x=old_x)
        revised = evaluate_definitions(definitions, override_x=revision_x)
        old_is_wrong = old_x != oracle["x"]
        if group == "correct_old_no_error_control":
            revision = f"复核后 x={revision_x} 保持不变。后续计算采用这个值。"
        elif group == "wait_wrong_revision_control":
            revision = f"Wait，前面的 x={old_x} 要改成 x={revision_x}。后续计算采用这个值。"
        else:
            revision = f"Wait，重新计算应为 x={revision_x}。后续计算采用这个值。"
        cases.append({
            "case_id": case_id,
            "group": group,
            "question": (
                f"按整数算术，依次定义 x={x_expr}，y={y_expr}，z={z_expr}。"
                "其中 // 表示整除，本例所有除法均恰好整除。求 z，只输出一个整数。"
            ),
            "old_branch": f"x={old['x']}；因此 y={old['y']}，z={old['z']}。",
            "independent_conclusion": f"独立核验题目中的原始定义：x={x_expr}={oracle['x']}。",
            "revision": revision,
            "required_final_value": oracle["z"],
            "old_error_value": old_x if old_is_wrong else None,
            "old_wrong_final_value": old["z"] if old_is_wrong else None,
            "old_branch_final_value": old["z"],
            "old_root_value": old_x,
            "revision_root_value": revision_x,
            "revision_implied_final_value": revised["z"],
            "oracle_trigger_label": int(old_is_wrong),
            "revision_is_correct": revision_x == oracle["x"],
            "definitions": definitions,
            "final_variable": "z",
            "dependency_path": ["x", "y", "z"],
            "oracle_values": oracle,
        })
    result = {
        "schema_version": "p0_synthetic_interface_v1",
        "date": "2026-11-05",
        "scope": "Teacher-forced synthetic mechanism interface set; not a natural long-CoT benchmark.",
        "construction": "16 handwritten integer-arithmetic variable-dependency states; zero model generations.",
        "oracle_trigger_definition": (
            "1 iff the old branch's x assertion contradicts the exact original x definition; "
            "0 iff that assertion is correct. The word Wait is not an oracle trigger."
        ),
        "old_error_value_definition": "Wrong asserted x value; null when the old branch is correct.",
        "evaluator_only_fields": [
            "required_final_value", "old_error_value", "old_wrong_final_value",
            "old_branch_final_value", "old_root_value", "revision_root_value",
            "revision_implied_final_value", "oracle_trigger_label",
            "revision_is_correct", "oracle_values", "group",
        ],
        "rendering_policy": (
            "question/old_branch/independent_conclusion/revision are separate components. "
            "The main agent controls which components, fillers, order, and model template are used. "
            "Do not automatically expose evaluator-only fields or treat all components as one prompt. "
            "The independent conclusion is a privileged exact verifier message, not a model-generated diagnosis."
        ),
        "selection_policy": "No gold-based selection of model outputs and no empirical model-performance claim.",
        "cases": cases,
    }
    validate(result)
    return result


def validate(dataset: dict) -> dict:
    cases = dataset["cases"]
    if len(cases) != 16 or len({case["case_id"] for case in cases}) != 16:
        raise ValueError("Exactly 16 distinct cases are required")
    counts = Counter(case["group"] for case in cases)
    expected = {
        "falsified_old_correct_revision": 8,
        "correct_old_no_error_control": 4,
        "wait_wrong_revision_control": 4,
    }
    if dict(counts) != expected:
        raise ValueError("Unexpected group counts: " + str(counts))
    for case in cases:
        oracle = evaluate_definitions(case["definitions"])
        old = evaluate_definitions(case["definitions"], case["old_root_value"])
        revised = evaluate_definitions(case["definitions"], case["revision_root_value"])
        target = case["final_variable"]
        trigger = int(old["x"] != oracle["x"])
        revision_is_correct = revised["x"] == oracle["x"]
        checks = [
            case["oracle_values"] == oracle,
            case["required_final_value"] == oracle[target],
            case["old_branch_final_value"] == old[target],
            case["revision_implied_final_value"] == revised[target],
            case["oracle_trigger_label"] == trigger,
            case["revision_is_correct"] == revision_is_correct,
            case["old_error_value"] == (old["x"] if trigger else None),
            case["old_wrong_final_value"] == (old[target] if trigger else None),
        ]
        if not all(checks):
            raise ValueError("Oracle field mismatch: " + case["case_id"])
        group = case["group"]
        if group == "falsified_old_correct_revision":
            valid = trigger == 1 and revision_is_correct and old[target] != oracle[target]
        elif group == "correct_old_no_error_control":
            valid = trigger == 0 and revision_is_correct and old[target] == oracle[target]
        else:
            valid = (trigger == 0 and not revision_is_correct
                     and "Wait" in case["revision"] and revised[target] != oracle[target])
        if not valid:
            raise ValueError("Control group condition failed: " + case["case_id"])
    return {"case_count": len(cases), "group_counts": dict(counts), "exact_integer_oracle": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("proposed_p0_cases.json"))
    parser.add_argument("--check-only", action="store_true",
                        help="Verify an existing JSON file without modifying it")
    args = parser.parse_args()
    if args.check_only:
        dataset = json.loads(args.output.read_text(encoding="utf-8"))
    else:
        dataset = build_cases()
        args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate(dataset)
    report["json_sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    report["model_inference_performed"] = False
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
