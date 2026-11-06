"""Frozen gold-blind answer extractor for future P0.5; extracted without logic changes.
Source: analyze_real_p0.py from prior P0 posthoc analysis. This is predeclared only
for future runs; it does not retroactively preregister the original P0 scores.
"""
import ast
import math
import re
INT = r"[+-]?[0-9]+"

def trim_one_period(text):
    text = text.strip()
    return text[:-1].rstrip() if text.endswith((".", "。")) else text

def normalize_math(text):
    text = text.replace("−", "-").replace("×", "*").replace("·", "*").replace("÷", "/")
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+", lambda m: "**" + m[0].translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")), text)
    return text.replace("^", "**")

def is_arithmetic_expression(text):
    if len(text) > 2048 or not text.strip():
        return False
    try:
        tree = ast.parse(normalize_math(text.strip()), mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return False
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.UAdd, ast.USub)
    nodes = list(ast.walk(tree))
    if len(nodes) > 256:
        return False
    for node in nodes:
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Name) and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id):
            return False
        if isinstance(node, ast.Constant) and (type(node.value) not in (int, float) or not math.isfinite(node.value)):
            return False
    return True

def extract_answer(text):
    """Pure extraction: its only argument is the output string, never evaluator data."""
    text = str(text)
    whole = trim_one_period(text)
    if re.fullmatch(INT, whole):
        return {"value": int(whole), "method": "single_integer_optional_terminal_period", "matched_text": whole}
    terminal = trim_one_period(text)
    # A marker must be terminal; explanatory text following the integer is not silently discarded.
    marker = re.search(r"(?:最终\s*(?:答案|结果)|答案|final\s+answer|answer)\s*"
                       r"(?:是|为|is|equals)?\s*[:：=]?\s*(" + INT + r")\s*$", terminal, re.I)
    if marker:
        return {"value": int(marker[1]), "method": "explicit_final_marker_terminal_integer", "matched_text": marker[0]}
    boxed = re.search(r"(?:\$\s*)?\\(?:boxed|fbox)\{\s*(" + INT + r")\s*\}(?:\s*\$)?\s*$", terminal)
    if boxed:
        return {"value": int(boxed[1]), "method": "explicit_boxed_terminal_integer", "matched_text": boxed[0]}
    nonempty = [line.strip() for line in text.splitlines() if line.strip()]
    last = trim_one_period(nonempty[-1]) if nonempty else ""
    sides = last.split("=")
    if len(sides) >= 2 and re.fullmatch(INT, sides[-1].strip()) and all(is_arithmetic_expression(s) for s in sides):
        return {"value": int(sides[-1].strip()), "method": "last_line_complete_equation_chain_terminal_integer",
                "matched_text": last, "normalized_math_for_grammar_only": normalize_math(last),
                "equation_truth_evaluated": False}
    return {"value": None, "method": "unresolved", "matched_text": None}
