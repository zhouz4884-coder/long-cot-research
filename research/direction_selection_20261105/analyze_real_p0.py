#!/usr/bin/env python3
"""Gold-blind posthoc text extraction and offline audit of one frozen 16-state P0.

No model import, execution, GPU access, prompt changes, rescoring, or result filtering.
Stage 1 calls extract_answer(text) using ONLY the output string and saves all 80
extractions before Stage 2 reads evaluation metadata. The original strict metric
is copied unchanged. This parser is explicitly posthoc, not a preregistered metric.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


ARMS = ("full", "target_late", "target_early_reprefill", "random_late", "random_early_reprefill")
ORDER = ("E01", "C01", "W01", "E02", "E03", "C02", "W02", "E04",
         "E05", "C03", "W03", "E06", "E07", "C04", "W04", "E08")
GROUPS = ("falsified_old_correct_revision", "correct_old_no_error_control", "wait_wrong_revision_control")
SHORT = {"full": "Full", "target_late": "Target-Late", "target_early_reprefill": "Target-Early",
         "random_late": "Random-Late", "random_early_reprefill": "Random-Early"}
GROUP_ZH = {GROUPS[0]: "E：旧错、修订正确", GROUPS[1]: "C：旧对、修订不变", GROUPS[2]: "W：旧对、修订错误"}
INT = r"[+-]?[0-9]+"
POLICY = {
    "status": "POSTHOC_EXPLORATORY_GOLD_BLIND_TEXT_EXTRACTION",
    "input": "Only greedy.text. No question, gold, case group, candidate scores or agreement across arms.",
    "precedence": [
        "Whole output is one integer after whitespace and at most one terminal ASCII/Chinese full stop.",
        "Terminal explicit final-answer marker followed by an integer, or terminal boxed integer.",
        "Last nonempty line is an entire arithmetic equality chain ending in an integer, with no trailing prose.",
        "Otherwise unresolved. Never take an arbitrary last number or evaluate a missing arithmetic answer.",
    ],
    "math_grammar": "AST arithmetic only; ASCII variable names allowed; no calls, indexing, attributes, evaluation or equation-truth check.",
    "math_normalization": "Unicode minus/multiplication/division, superscript digit exponent, ^ to **; original text retained.",
    "denominator": "All 16 fixed states per arm; unresolved separate and not dropped.",
    "strict_metric": "Frozen original strict_integer and strict_correct copied unchanged.",
}


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


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


def stats(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return {"n": 0, "min": None, "max": None, "mean": None, "median": None}
    return {"n": len(values), "min": min(values), "max": max(values),
            "mean": statistics.mean(values), "median": statistics.median(values)}


def kv_max(rows, group=None, only_layer=None, metric="max_abs"):
    values = []
    for row in rows:
        if only_layer is not None and row["layer"] != only_layer:
            continue
        for name, tensors in row["groups"].items():
            if group is not None and name != group:
                continue
            values.extend(x[metric] for x in tensors.values() if x is not None)
    return max(values, default=0.0)


def paired(rows, left, right, group=None):
    selected = [r for r in rows if group is None or r["group"] == group]
    n_left = n_right = both = left_only = right_only = 0
    changes, gains, losses = [], [], []
    for row in selected:
        a, b = row["arms"][left], row["arms"][right]
        ac, bc = a["posthoc_correct"], b["posthoc_correct"]
        n_left += ac
        n_right += bc
        both += ac and bc
        left_only += ac and not bc
        right_only += bc and not ac
        if a["posthoc"]["value"] != b["posthoc"]["value"]:
            changes.append(row["case_id"])
        if bc and not ac:
            gains.append(row["case_id"])
        if ac and not bc:
            losses.append(row["case_id"])
    return {"left": left, "right": right, "n": len(selected), "left_correct": n_left, "right_correct": n_right,
            "both_correct": both, "left_only_correct": left_only, "right_only_correct": right_only,
            "net_right_minus_left": right_only - left_only, "changed_answer_cases": changes,
            "right_gain_cases": gains, "right_loss_cases": losses}


def md_escape(text):
    return str(text).replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


def fnum(value, digits=4):
    return "NA" if value is None else f"{value:.{digits}f}"


def analyze(input_dir, output_dir):
    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    original_summary = json.loads((input_dir / "summary.json").read_text(encoding="utf-8"))
    records = {cid: json.loads((input_dir / f"{cid}.json").read_text(encoding="utf-8")) for cid in ORDER}
    if original_summary["completed_cases"] != 16 or any(set(r["arms"]) != set(ARMS) for r in records.values()):
        raise ValueError("This analysis requires the complete frozen 16-case, five-arm run.")
    # Stage 1. All outputs, no truth data. Persist and hash before any scoring metadata is read below.
    extractions = {"parser_policy": POLICY, "created_utc": datetime.now(timezone.utc).isoformat(), "outputs": []}
    extracted = {}
    for cid in ORDER:
        for arm in ARMS:
            text = records[cid]["arms"][arm]["greedy"]["text"]
            extraction = extract_answer(text)
            extracted[cid, arm] = extraction
            extractions["outputs"].append({"case_id": cid, "arm": arm, "original_text": text, **extraction})
    extraction_path = output_dir / "POSTHOC_EXTRACTIONS.json"
    if extraction_path.exists():
        prior = json.loads(extraction_path.read_text(encoding="utf-8"))
        if prior["parser_policy"] != POLICY or prior["outputs"] != extractions["outputs"]:
            raise RuntimeError("Existing frozen extraction differs; refusing a silent parser/result revision.")
        extractions = prior
    else:
        write_json(extraction_path, extractions)
    extraction_sha = sha_file(extraction_path)
    # Stage 2. Freeze extraction, then compare with evaluator metadata and original strict outcomes.
    rows, methods = [], Counter()
    for cid in ORDER:
        record, arms = records[cid], {}
        meta = record["evaluation_metadata"]
        for arm in ARMS:
            source, post = record["arms"][arm], extracted[cid, arm]
            methods[post["method"]] += 1
            value = post["value"]
            arms[arm] = {"original_text": source["greedy"]["text"],
                         "strict_integer_frozen": source["greedy"]["strict_integer"],
                         "strict_correct_frozen": source["evaluation"]["strict_correct"],
                         "posthoc": post, "posthoc_correct": value is not None and value == meta["required_final_value"],
                         "matches_old_branch_value": value is not None and value == meta["old_branch_final_value"],
                         "matches_revision_implied_value": value is not None and value == meta["revision_implied_final_value"],
                         "candidate_scores_frozen": source["candidate_scores"],
                         "generation_stop_reason": source["greedy"]["stop_reason"]}
        rows.append({"case_id": cid, "group": meta["group"], "evaluation_metadata": meta, "arms": arms,
                     "pairwise_readout_frozen": record["pairwise_readout"]})
    overview = {}
    for arm in ARMS:
        counts = {}
        for group in ("all",) + GROUPS:
            chosen = [r for r in rows if group == "all" or r["group"] == group]
            vals = [r["arms"][arm] for r in chosen]
            counts[group] = {"n": len(vals), "strict_correct_frozen": sum(v["strict_correct_frozen"] for v in vals),
                             "strict_parseable_frozen": sum(v["strict_integer_frozen"] is not None for v in vals),
                             "posthoc_correct": sum(v["posthoc_correct"] for v in vals),
                             "posthoc_parseable": sum(v["posthoc"]["value"] is not None for v in vals),
                             "posthoc_unresolved": sum(v["posthoc"]["value"] is None for v in vals),
                             "matches_old_branch_value": sum(v["matches_old_branch_value"] for v in vals),
                             "matches_revision_implied_value": sum(v["matches_revision_implied_value"] for v in vals)}
        overview[arm] = counts
    contrasts = [("full", "target_late"), ("full", "target_early_reprefill"), ("full", "random_late"),
                 ("full", "random_early_reprefill"), ("target_late", "target_early_reprefill"),
                 ("random_late", "random_early_reprefill"), ("random_late", "target_late"),
                 ("random_early_reprefill", "target_early_reprefill")]
    paired_counts = {left + "__to__" + right: {group: paired(rows, left, right, None if group == "all" else group)
                                             for group in ("all",) + GROUPS} for left, right in contrasts}
    candidate_stats = {}
    candidate_deltas = {}
    for arm in ARMS:
        candidate_stats[arm] = {group: {role: stats([
            r["arms"][arm]["candidate_scores_frozen"]["correct_log_odds_over"][role]
            for r in rows if r["group"] == group]) for role in ("old_branch", "revision_implied")} for group in GROUPS}
    for left, right in contrasts:
        key = left + "__to__" + right
        candidate_deltas[key] = {}
        for group in GROUPS:
            role = "revision_implied" if group == GROUPS[2] else "old_branch"
            deltas = []
            for row in rows:
                if row["group"] != group:
                    continue
                a = row["arms"][left]["candidate_scores_frozen"]["correct_log_odds_over"][role]
                b = row["arms"][right]["candidate_scores_frozen"]["correct_log_odds_over"][role]
                if a is not None and b is not None:
                    deltas.append({"case_id": row["case_id"], "right_minus_left_log_odds": b - a})
            candidate_deltas[key][group] = {"role": role, "stats": stats([d["right_minus_left_log_odds"] for d in deltas]),
                                            "positive": sum(d["right_minus_left_log_odds"] > 0 for d in deltas), "cases": deltas}
    controls = {cid: r["controls"] for cid, r in records.items() if r.get("controls", {}).get("passed") is not None}
    noise_names = ("same_mask_no_delete", "same_mask_early_rebuild", "masked_value_sentinel_8")
    noise = {name: {metric: stats([c[name][metric] for c in controls.values()])
                    for metric in ("logit_max_abs", "TV", "JS_nats")} for name in noise_names + ("cached_vs_whole_recompute",)}
    no_op_max = max(c[name]["logit_max_abs"] for c in controls.values() for name in noise_names)
    floor = max(1e-3, 10 * no_op_max)
    mechanism = {}
    for key in ("target_late_vs_early", "random_late_vs_early"):
        vals = [r["pairwise_readout"][key] for r in records.values()]
        mechanism[key] = {metric: stats([v[metric] for v in vals]) for metric in ("logit_max_abs", "TV", "JS_nats")}
        mechanism[key].update(logit_engineering_floor=floor,
                              above_logit_engineering_floor=sum(v["logit_max_abs"] > floor for v in vals),
                              argmax_changed=sum(not v["argmax_equal"] for v in vals))
    kv = {}
    for arm in ("target_early_reprefill", "random_early_reprefill"):
        kv[arm] = {group: stats([kv_max(r["arms"][arm]["prefill_KV_vs_full"], group) for r in records.values()])
                   for group in ("before_B", "U", "R", "surviving_all")}
        kv[arm]["first_layer_surviving_max_abs"] = stats([
            kv_max(r["arms"][arm]["prefill_KV_vs_full"], "surviving_all", 0) for r in records.values()])
    peak_values = [t["peak_allocated_bytes"] for r in records.values() for t in r["all_stage_timings"] if t["peak_allocated_bytes"] is not None]
    readout_token_lengths = [len(r["rendering"]["readout_ids"]) for r in records.values()]
    cost = {"runner_elapsed_seconds": original_summary["elapsed_seconds"],
            "model_load_and_hash_seconds": manifest["load_and_hash_seconds"],
            "sum_complete_case_seconds": sum(r["case_seconds"] for r in records.values()),
            "prefix_token_lengths": stats([len(r["rendering"]["prefix_ids"]) for r in records.values()]),
            "readout_token_lengths": stats(readout_token_lengths),
            "free_generated_tokens": sum(r["arms"][a]["greedy"]["new_tokens"] for r in records.values() for a in ARMS),
            "observed_postload_stage_peak_allocated_bytes": max(peak_values),
            "nested_timings_note": "Control bundle includes nested timings; do not sum all timing rows as GPU time."}
    source_hashes = {"manifest.json": sha_file(input_dir / "manifest.json"), "summary.json": sha_file(input_dir / "summary.json")}
    source_hashes.update({cid + ".json": sha_file(input_dir / f"{cid}.json") for cid in ORDER})
    result = {"analysis_status": "POSTHOC_EXPLORATORY_NO_GPU_RERUN", "parser_policy": POLICY,
              "input_directory": str(input_dir), "analysis_source_sha256": sha_file(__file__),
              "frozen_extraction_sha256": extraction_sha, "input_artifact_sha256": source_hashes,
              "real_model_source_sha256": manifest["source_sha256"], "model_manifest_sha256": manifest["model_manifest_sha256"],
              "binding": manifest["binding"], "gpu": manifest["gpu"], "versions": manifest["versions"],
              "parameter_dtype": manifest["parameter_dtype"], "method_counts": dict(methods),
              "overview": overview, "paired_posthoc_counts": paired_counts,
              "candidate_log_odds_stats": candidate_stats, "candidate_log_odds_paired_deltas": candidate_deltas,
              "controls": controls, "no_op_noise": noise, "mechanism_readout": mechanism, "prefill_KV": kv,
              "cost": cost, "all_outputs": rows,
              "posthoc_correct_with_frozen_strict_failure": [
                  {"case_id": r["case_id"], "arm": a, "original_text": r["arms"][a]["original_text"],
                   "extraction": r["arms"][a]["posthoc"]}
                  for r in rows for a in ARMS if r["arms"][a]["posthoc_correct"] and not r["arms"][a]["strict_correct_frozen"]],
              "unresolved": [x for x in extractions["outputs"] if x["value"] is None],
              "mathematically_incorrect_after_posthoc_extraction": [
                  {"case_id": r["case_id"], "group": r["group"], "arm": a,
                   "raw": r["arms"][a]["original_text"], "extracted": r["arms"][a]["posthoc"]["value"],
                   "gold_evaluation_only": r["evaluation_metadata"]["required_final_value"]}
                  for r in rows for a in ARMS if r["arms"][a]["posthoc"]["value"] is not None and not r["arms"][a]["posthoc_correct"]],
              "interpretation_limits": ["strict zero is format failure, not zero mathematical capability",
                  "Posthoc parser is exploratory and cannot replace the frozen primary outcome",
                  "No independent no-op continuation-likelihood repeat: readout noise is not a likelihood-score error bar",
                  "Original likelihood includes newline; many greedy outputs end with a Chinese full stop, so format preference affects scores",
                  "Artificial short injected states; no natural long-CoT/self-correction/semantic-specificity claim",
                  "Random mask matches count but not age or contiguous-span structure; all tensors retain full size"]}
    write_json(output_dir / "REAL_P0_ANALYSIS.json", result)
    render_report(result, output_dir / "REAL_P0_ANALYSIS_ZH.md")
    return result


def render_report(result, destination):
    ov, pairs, mechanisms = result["overview"], result["paired_posthoc_counts"], result["mechanism_readout"]
    controls, cost = result["controls"], result["cost"]
    lines = ["# 真实模型 P0：缓存状态机制与输出格式事后分析", "",
             "**结论：观察到缓存/读出分布差异，但本轮不足以支持扩大或宣称纠错收益。** 冻结严格评分仍为每臂0/16；80条输出均未满足原来的纯整数格式，这个0不能解读为数学能力为0或全部干预答错。下列数学正确计数来自明确标记的事后、金标隔离文本抽取，不能替换主指标。", "",
             "## 1. 方法和证据边界", "",
             "本分析未改模型源、输入、mask、候选评分或原始结果，未重跑GPU。先只把80个输出字符串交给纯函数解析并保存POSTHOC_EXTRACTIONS.json，再读取离线评价字段。提取函数不接收题目、金标、组别、其他臂的答案或candidate likelihood；完整原文与unresolved保留。规则优先级：", "",
             "1. 全文去空白及至多一个终端中/英文句号后为单整数。",
             "2. 终端明确的“最终答案/答案/final answer”或boxed标记后为整数；不忽略其后的解释性文字。",
             "3. 最后非空行整体是完整算术等式链，末端为整数且无尾随文字。用受限AST只检查语法；不求值、不核等式真假，不从未完成算式算答案。支持数学符号和上标指数的语法归一化。",
             "4. 其他记unresolved；不用“全文最后一个数字”兜底。", "",
             f"抽取方式计数：{json.dumps(result['method_counts'], ensure_ascii=False)}。unresolved={len(result['unresolved'])}/80。规则是在观察到格式问题后补充，属于posthoc探索，不是预注册评分。已解析的80条中，{len(result['posthoc_correct_with_frozen_strict_failure'])}条数学答案在此规则下正确但原strict格式不通过，另{len(result['mathematically_incorrect_after_posthoc_extraction'])}条数学答案确实错误；两类不混写。", "",
             "## 2. 原strict与事后抽取分列", "",
             "| 臂 | 冻结strict | 事后数学正确（16例） | E：旧错/正确修订（8） | C：正确旧分支（4） | W：错误修订（4） |", "|---|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        lines.append(f"| {SHORT[arm]} | {ov[arm]['all']['strict_correct_frozen']}/16 | {ov[arm]['all']['posthoc_correct']}/16 | " +
                     " | ".join(f"{ov[arm][g]['posthoc_correct']}/{ov[arm][g]['n']}" for g in GROUPS) + " |")
    lines += ["", "这里的E/C/W是预先构造的人工注入状态，不是自然错误/自然自纠样本；所有臂共享同一人为revision，包括W组错误revision。", "",
              "## 3. 配对变化与失败案例", "",
              "| 左臂 → 右臂 | 左对右错 | 左错右对 | 右减左净正确数 | 右臂修复case | 右臂新增错误case |", "|---|---:|---:|---:|---|---|"]
    for key, by_group in pairs.items():
        p = by_group["all"]
        lines.append(f"| {SHORT[p['left']]} → {SHORT[p['right']]} | {p['left_only_correct']} | {p['right_only_correct']} | {p['net_right_minus_left']:+d} | " +
                     ", ".join(p["right_gain_cases"]) + " | " + ", ".join(p["right_loss_cases"]) + " |")
    target_full = pairs["full__to__target_early_reprefill"]
    target_late = pairs["target_late__to__target_early_reprefill"]
    lines += ["", f"Target-Early相对Full：E组新增修复 {', '.join(target_full[GROUPS[0]]['right_gain_cases']) or '无'}；C组新增错误 {', '.join(target_full[GROUPS[1]]['right_loss_cases']) or '无'}；W组新增错误 {', '.join(target_full[GROUPS[2]]['right_loss_cases']) or '无'}。",
              f"Target-Early相对Target-Late在E组的净变化为{target_late[GROUPS[0]]['net_right_minus_left']:+d}，但C组净变化为{target_late[GROUPS[1]]['net_right_minus_left']:+d}。因此不能只汇报E组阳性而跳过误触发伤害。", "",
              "本轮不满足“C/W无新增错误”的继续条件。先保留负结果，不扩大样本或调填充找阳性。目标mask还删掉了旧分支中已算出的y/z等信息；部分输出把x直接代作z，说明算术承接/信息删除与历史状态效应并存。这个解释是由原文提出的猜想，不是已识别的唯一因果机制。", "",
              "## 4. 机制与数值控制", "",
              f"E01/C01/W01共{sum(len(c['checks']) for c in controls.values())}项接口检查，全部通过={all(c['passed'] for c in controls.values())}。同输入/no-delete、early独立重建、masked V sentinel、目标及随机early prefill禁读、readout禁读与未来causal质量均有原始记录。", "",
              "| 比较 | logit最大差范围 | TV范围 | JS范围（nats） | 超过工程筛查阈值 | argmax改变 |", "|---|---:|---:|---:|---:|---:|"]
    for key, data in mechanisms.items():
        lines.append(f"| {key} | {fnum(data['logit_max_abs']['min'])}–{fnum(data['logit_max_abs']['max'])} | " +
                     f"{fnum(data['TV']['min'])}–{fnum(data['TV']['max'])} | {fnum(data['JS_nats']['min'])}–{fnum(data['JS_nats']['max'])} | " +
                     f"{data['above_logit_engineering_floor']}/16（阈值{data['logit_engineering_floor']:.4g}） | {data['argmax_changed']}/16 |")
    lines += ["", "| 控制路径 | 最大logit差 | 最大TV | 最大JS |", "|---|---:|---:|---:|"]
    for name, noise in result["no_op_noise"].items():
        lines.append(f"| {name} | {fnum(noise['logit_max_abs']['max'], 8)} | {fnum(noise['TV']['max'], 8)} | {fnum(noise['JS_nats']['max'], 8)} |")
    lines += ["", "cached/full重算因forward分块与shape不同，噪声单独列示。工程阈值不是统计显著性或正确性的证明。两类random/target重算都能改变状态，不能把所有状态变化归为证伪语义。", "",
              "| early重算 | B前KV最大差 | 第一层幸存KV最大差 | U高层KV最大差 | R高层KV最大差 |", "|---|---:|---:|---:|---:|"]
    for arm, info in result["prefill_KV"].items():
        lines.append(f"| {SHORT[arm]} | {fnum(info['before_B']['max'], 8)} | {fnum(info['first_layer_surviving_max_abs']['max'], 8)} | " +
                     f"{fnum(info['U']['max'])} | {fnum(info['R']['max'])} |")
    lines += ["", "## 5. 冻结candidate likelihood：不用于挑答案", "",
              "候选为完整整数加固定换行，使用原run保存的logP及去重结果；下表为正确值相对旧分支/错误修订的log-odds均值。C组同值重合，margin记NA。注意很多自由输出实际以中文句号终止，故换行候选含格式偏好；这不等同最终自由答案正确率。未追加no-op候选评分实验，不能把readout噪声直接当candidate margin误差条。", "",
              "| 臂 | E：correct−old均值 | W：correct−wrong-revision均值 |", "|---|---:|---:|"]
    for arm in ARMS:
        candidate = result["candidate_log_odds_stats"][arm]
        lines.append(f"| {SHORT[arm]} | {fnum(candidate[GROUPS[0]]['old_branch']['mean'])} | {fnum(candidate[GROUPS[2]]['revision_implied']['mean'])} |")
    lines += ["", "| 配对变化（右减左） | E组log-odds变化均值 | E正向case数 | W组变化均值 | W正向case数 |", "|---|---:|---:|---:|---:|"]
    for key in ("target_late__to__target_early_reprefill", "random_late__to__random_early_reprefill"):
        by_group = result["candidate_log_odds_paired_deltas"][key]
        e, w = by_group[GROUPS[0]], by_group[GROUPS[2]]
        lines.append(f"| {key} | {fnum(e['stats']['mean'])} | {e['positive']}/{e['stats']['n']} | {fnum(w['stats']['mean'])} | {w['positive']}/{w['stats']['n']} |")
    lines += ["", "Target-Early相对Target-Late的E组净修复为3例，但完整候选margin只在3/8例上升；E05虽从34变为正确的28，正确相对旧错的margin反而下降约3.46 nats。自由输出与限定候选指标未全面同向，不能只用平均logit差或少数成功样本宣布恢复。", "",
              "逐case完整候选文本、token项logP和pair delta均在JSON；没有按候选评分选择自由输出。", "",
              "## 6. 资源、可复核性及决策", "",
              f"本轮为{result['gpu']['name']}、{result['parameter_dtype']} eager，Torch {result['versions']['torch']} / Transformers {result['versions']['transformers']}，显式单卡UUID绑定；启动前和结束后compute进程为空（无调度器排他锁）；不是V100测量。runner总用时{cost['runner_elapsed_seconds']:.3f}s（{cost['runner_elapsed_seconds']/60:.3f}min），其中模型hash/load {cost['model_load_and_hash_seconds']:.3f}s；逐case用时合计{cost['sum_complete_case_seconds']:.3f}s。",
              f"前缀长度范围{cost['prefix_token_lengths']['min']:.0f}–{cost['prefix_token_lengths']['max']:.0f} token，自由生成总计{cost['free_generated_tokens']} token。记录到的加载后阶段最大allocated显存为{cost['observed_postload_stage_peak_allocated_bytes']/1024**3:.3f}GiB，非所有加载瞬态的全程峰值。嵌套timing不能直接求和。所有臂保留完整cache槽位，不能声称节省显存。", "",
              "解释边界：短人工状态可证明给定mask时点下的状态/分布差别；不证明自然长CoT旧错复发、不证明语义证伪触发器、不证明安全恢复。随机pool是B∪U的等预算散点，未匹配token年龄或连续跨度，也不是Random Attention复现。即使某子组优于该控制，也不能据此断言语义特异性。", "",
              "本轮决策：保留为真实模型上的状态一致性证据和负例库；当前数据不支持把五臂诊断升级为纠错算法收益或扩大运行。若之后做一次新的独立短轮，应先修复并预冻输出格式评分，同时分离“丢失已计算结果”“缓存重编码”“错误修订被强化”三种可证伪解释；本轮结束，不追加GPU。", "",
              f"模型manifest SHA256：`{result['model_manifest_sha256']}`。模型runner源SHA256：`{result['real_model_source_sha256']}`。抽取冻结文件SHA256：`{result['frozen_extraction_sha256']}`。", "",
              "## 7. 全部80条原文与事后抽取", "",
              "原strict全部为未解析；下表√/×只表示事后抽取整数与离线金标比较，不替换原评分。", "",
              "| Case | 臂 | 原始输出 | 抽取方法 | 抽取值 | 离线金标 | 事后正确 | E旧错/W错修订margin |", "|---|---|---|---|---:|---:|---|---:|"]
    method_short = {"single_integer_optional_terminal_period": "单整数/终止句号", "explicit_final_marker_terminal_integer": "明确最终答案",
                    "explicit_boxed_terminal_integer": "boxed", "last_line_complete_equation_chain_terminal_integer": "完整末行等式链", "unresolved": "未解析"}
    for row in result["all_outputs"]:
        role = "revision_implied" if row["group"] == GROUPS[2] else "old_branch"
        for arm in ARMS:
            data = row["arms"][arm]
            margin = data["candidate_scores_frozen"]["correct_log_odds_over"][role]
            lines.append(f"| {row['case_id']} | {SHORT[arm]} | {md_escape(data['original_text'])} | {method_short[data['posthoc']['method']]} | " +
                         f"{data['posthoc']['value'] if data['posthoc']['value'] is not None else 'NA'} | {row['evaluation_metadata']['required_final_value']} | " +
                         f"{'√' if data['posthoc_correct'] else '×'} | {fnum(margin)} |")
    Path(destination).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.input, args.output)
    print(json.dumps({"status": result["analysis_status"], "outputs": sum(result["method_counts"].values()),
                      "unresolved": len(result["unresolved"]),
                      "posthoc_correct": {a: result["overview"][a]["all"]["posthoc_correct"] for a in ARMS}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
