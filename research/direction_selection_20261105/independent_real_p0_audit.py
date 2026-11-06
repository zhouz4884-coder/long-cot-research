"""Independent CPU/NumPy audit of saved P0 logits and recorded provenance.

Does not import the experimental runner, use GPU/network, or rescore mathematical
accuracy with a new parser. The original strict parser and all 80 texts are kept.
"""
import hashlib
import json
import math
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "p0_qwen3_4b_fp16_01"
ARMS = ["full", "target_late", "target_early_reprefill", "random_late", "random_early_reprefill"]
CONTROLS = {"E01", "C01", "W01"}
EXPECTED_INPUT = "6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27"
EXPECTED_SOURCE = "246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    assert np.isfinite(a).all() and np.isfinite(b).all()
    la = a - (np.max(a) + np.log(np.exp(a - np.max(a)).sum(dtype=np.float64)))
    lb = b - (np.max(b) + np.log(np.exp(b - np.max(b)).sum(dtype=np.float64)))
    p, q = np.exp(la), np.exp(lb)
    lm = np.log(np.maximum((p + q) * 0.5, 1e-300))
    return {"logit_max_abs": float(np.max(np.abs(a-b))),
            "logit_relative_l2": float(np.linalg.norm(a-b) / max(np.linalg.norm(a), 1e-30)),
            "TV": float(np.abs(p-q).sum(dtype=np.float64) / 2),
            "JS_nats": max(0.0, float(np.sum(p*(la-lm), dtype=np.float64)/2 + np.sum(q*(lb-lm), dtype=np.float64)/2)),
            "argmax_equal": bool(np.argmax(a) == np.argmax(b)),
            "exact_equal": bool(np.array_equal(a, b))}


def aggregate(rows, key):
    x = np.array([r[key] for r in rows], dtype=np.float64)
    return {"min": float(x.min()), "mean": float(x.mean()), "median": float(np.median(x)), "max": float(x.max())}


def main():
    started = time.perf_counter()
    manifest, summary = read(RUN / "manifest.json"), read(RUN / "summary.json")
    inputs = read(ROOT / "proposed_p0_cases.json")
    by_id = {c["case_id"]: c for c in inputs["cases"]}
    order = manifest["executed_order"]
    assert len(order) == 16 and len(set(order)) == 16
    assert order == manifest["frozen_order"]
    files = manifest["model_files"]["files"]
    model_digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    binding = {
        "local_source_matches_recorded_sha": sha(ROOT/"real_model_p0.py") == manifest["source_sha256"] == EXPECTED_SOURCE,
        "local_input_matches_recorded_sha": sha(ROOT/"proposed_p0_cases.json") == manifest["input_sha256"] == EXPECTED_INPUT,
        "model_manifest_list_digest_matches": model_digest == manifest["model_manifest_sha256"] == manifest["model_files"]["manifest_sha256"] == summary["model_manifest_sha256"],
        "model_file_count": len(files),
        "weight_file_count": sum(x["name"].endswith(".safetensors") for x in files),
        "model_weight_bytes": sum(x["size_bytes"] for x in files if x["name"].endswith(".safetensors")),
        "remote_weight_bytes_rehashed_in_this_audit": False,
        "remote_weight_scope": "Only recorded file hash list and binding are independently verified here; this CPU audit does not access remote weight files.",
    }
    assert all(v for k, v in binding.items() if k.endswith("matches_recorded_sha") or k.endswith("digest_matches"))
    numeric_errors, failures, cases, texts = [], [], [], []
    candidate_first_error = 0.0
    numeric_count = 0
    identity_max, dense_noise_max, forbidden_max, invariance_max = 0.0, 0.0, 0.0, 0.0
    strict_counts, parse_counts, token_counts = Counter(), Counter(), Counter()
    artifacts = [{"file": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
                 for p in [RUN/"manifest.json", RUN/"summary.json", RUN/"RESULT.md"]]

    def compare(recomputed, stored, context):
        nonlocal numeric_count
        numeric_count += 1
        for key, value in recomputed.items():
            if isinstance(value, bool):
                if value is not stored[key]:
                    failures.append({"context": context, "metric": key, "expected": value, "recorded": stored[key]})
            else:
                difference = abs(value - stored[key])
                numeric_errors.append({"context": context, "metric": key, "abs_difference": difference})
                if difference > 1e-10:
                    failures.append({"context": context, "metric": key, "abs_difference": difference})

    for cid in order:
        p, n = RUN/(cid+".json"), RUN/(cid+"_readout_logits.npz")
        artifacts += [{"file": z.name, "sha256": sha(z), "bytes": z.stat().st_size} for z in (p, n)]
        c, expected = read(p), by_id[cid]
        assert c["status"] == "COMPLETE"
        assert all(c[k] == manifest[k] for k in ("source_sha256", "input_sha256", "model_manifest_sha256"))
        r, segments = c["rendering"], c["rendering"]["segments"]
        assert set(r["visible_fields"]) == {"question", "old_branch", "revision"}
        assert r["visible_fields"] == {k: expected[k] for k in ("question", "old_branch", "revision")}
        expected_p = "<|im_start|>user\n"+expected["question"]+"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n\n人工提供的计算记录：\n"
        assert r["rendered_pieces"] == {"P": expected_p, "B": expected["old_branch"],
            "U": "\n继续依据题目给定定义进行核算。\n"*4,
            "R": "\n"+expected["revision"], "S": "\n按题目原始定义核算，最终 z="}
        assert expected["independent_conclusion"] not in "".join(r["rendered_pieces"].values())
        prefix_length, readout_length = len(r["prefix_ids"]), len(r["readout_ids"])
        assert r["position_ids"] == list(range(prefix_length+readout_length))
        assert [segments[x][1] for x in ("P", "B", "U", "R")] == [segments[x][0] for x in ("B", "U", "R", "S")]
        assert segments["P"][0] == 0 and segments["R"][1] == prefix_length
        target = list(range(*segments["B"]))
        stable_seed = (manifest["seed"]+int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16)) % (2**32)
        pool = list(range(segments["B"][0], segments["U"][1]))
        random_columns = sorted(random.Random(stable_seed).sample(pool, len(target)))
        assert r["target_columns"] == target and r["random_columns"] == random_columns and r["random_seed"] == stable_seed
        with np.load(n, allow_pickle=False) as loaded:
            assert set(loaded.files) == set(ARMS)
            logits = {a: loaded[a].copy() for a in ARMS}
        assert all(x.shape == (manifest["model_config"]["vocab_size"],) and x.dtype == np.float32 and np.isfinite(x).all() for x in logits.values())
        comparisons = {}
        for name, a, b in (("target_late_vs_early", "target_late", "target_early_reprefill"),
                           ("random_late_vs_early", "random_late", "random_early_reprefill")):
            comparisons[name] = metrics(logits[a], logits[b])
            compare(comparisons[name], c["pairwise_readout"][name], cid+"/"+name)
            ss = next(x for x in summary["per_case_pairs"] if x["case_id"] == cid)
            compare(comparisons[name], ss["comparisons"][name], cid+"/summary/"+name)
        controls = c["controls"]
        if cid in CONTROLS:
            assert controls["passed"] is True and all(controls["checks"].values())
            for key in ("same_mask_no_delete", "same_mask_early_rebuild", "masked_value_sentinel_8"):
                identity_max = max(identity_max, controls[key]["logit_max_abs"])
            dense_noise_max = max(dense_noise_max, controls["cached_vs_whole_recompute"]["logit_max_abs"])
            for key in ("attention_check_early", "attention_check_late", "target_prefill_attention", "random_prefill_attention"):
                info = controls[key]
                assert info["all_finite"] is True
                for mk in ("masked_key_mass_max_per_layer", "future_key_mass_max_per_layer", "surviving_query_masked_key_mass_max_per_layer"):
                    if mk in info:
                        forbidden_max = max(forbidden_max, max(info[mk]))
            invariance_max = max(invariance_max, controls["prefix_invariance_max_abs"], controls["first_layer_invariance_max_abs"])
        else:
            assert controls["passed"] is None
        kv_by_arm = {}
        for arm in ARMS:
            ac = c["arms"][arm]
            columns = [] if arm == "full" else target if arm.startswith("target") else random_columns
            assert ac["masked_columns"] == columns and ac["masked_token_count"] == len(columns)
            assert ac["same_full_tensor_shape"] is True and ac["physical_eviction"] is False
            compare(metrics(logits["full"], logits[arm]), ac["readout_vs_full"], cid+"/"+arm+"/vs_full")
            values, greedy = ac["candidate_scores"], ac["greedy"]
            for value, row in values["unique_candidates"].items():
                assert abs(sum(row["token_logP"]) - row["logP"]) < 1e-12
                assert row["continuation"] == value+"\n" and row["length_normalization"] == "none"
                x = logits[arm].astype(np.float64)
                lp = x - (x.max()+np.log(np.exp(x-x.max()).sum()))
                candidate_first_error = max(candidate_first_error, abs(float(lp[row["token_ids"][0]])-row["token_logP"][0]))
            assert values["used_to_choose_output"] is False
            if "prefill_KV_vs_full" in ac:
                rows = ac["prefill_KV_vs_full"]
                assert len(rows) == manifest["model_config"]["num_hidden_layers"]
                maxdiff = 0.0
                for lr in rows:
                    for group, tensors in lr["groups"].items():
                        for v in tensors.values():
                            if v is not None:
                                assert v["finite"]
                                maxdiff = max(maxdiff, v["max_abs"])
                kv_by_arm[arm] = {"max_reported_KV_abs": maxdiff,
                                  "first_layer_surviving_all_max_abs": max(v["max_abs"] for v in rows[0]["groups"]["surviving_all"].values())}
            strict_counts[arm] += bool(ac["evaluation"]["strict_correct"])
            parse_counts[arm] += greedy["strict_integer"] is not None
            token_counts[arm] += greedy["new_tokens"]
            texts.append({"case_id": cid, "group": expected["group"], "arm": arm, "text": greedy["text"],
                          "original_strict_integer": greedy["strict_integer"],
                          "original_strict_correct": ac["evaluation"]["strict_correct"],
                          "stop_reason": greedy["stop_reason"], "new_tokens": greedy["new_tokens"]})
        cases.append({"case_id": cid, "group": expected["group"], "status": c["status"],
            "interface_controls": "PASS" if controls["passed"] else "NOT_RUN_AS_PREDECLARED",
            "control_checks": controls.get("checks"), "source_input_model_binding": "PASS",
            "renderer_visible_field_audit": "PASS", "prefix_tokens": prefix_length,
            "readout_tokens": readout_length, "target_token_count": len(target),
            "random_hits_B": r["random_hits_B"], "random_hits_U": r["random_hits_U"],
            "pairwise_recomputed": comparisons, "reported_KV_summary_not_raw_tensor_recomputed": kv_by_arm})
    assert len(texts) == 80 and all(x["original_strict_integer"] is None for x in texts)
    assert all(summary["arms"][a]["strict_correct"] == strict_counts[a] and summary["arms"][a]["strict_integer_parseable"] == parse_counts[a] for a in ARMS)
    assert not failures, failures
    families = {}
    for family in ("target_late_vs_early", "random_late_vs_early"):
        rows = [c["pairwise_recomputed"][family] for c in cases]
        families[family] = {"logit_max_abs": aggregate(rows, "logit_max_abs"), "TV": aggregate(rows, "TV"),
                            "JS_nats": aggregate(rows, "JS_nats"),
                            "argmax_changed_cases": sum(not x["argmax_equal"] for x in rows)}
    report = {
        "schema_version": 1, "status": "PASS_INDEPENDENT_ARTIFACT_NUMERIC_AUDIT",
        "method": "Independent NumPy float64 stable softmax/log probabilities; does not import experimental distribution_metrics.",
        "scope": "Saved artifacts only, no GPU/remote calls; no new mathematical-answer parser.",
        "audit_source_sha256": sha(Path(__file__)),
        "provenance_binding": binding,
        "numeric_comparison_count_including_json_summary_duplicates": numeric_count,
        "numeric_json_metric_count": len(numeric_errors),
        "max_abs_numeric_disagreement": max(x["abs_difference"] for x in numeric_errors),
        "numeric_agreement_tolerance": 1e-10, "numeric_failures": failures,
        "candidate_first_token_float64_vs_recorded_float32_max_abs_logP_error": candidate_first_error,
        "candidate_rest_scope": "Recorded token_logP sums checked; additional teacher-forced forward logits were not saved and cannot be independently recomputed without the model.",
        "controls": {"full_control_cases_passed": sorted(CONTROLS), "full_control_case_count": len(CONTROLS),
            "not_run_as_predeclared_cases": [c["case_id"] for c in cases if c["case_id"] not in CONTROLS],
            "same_path_identity_logit_max": identity_max,
            "cached_vs_whole_recompute_shape_logit_max": dense_noise_max,
            "masked_or_future_key_probability_mass_max": forbidden_max,
            "prefix_and_first_layer_invariance_max": invariance_max,
            "raw_attention_and_cache_tensors_scope": "Only recorded reductions are available, so these controls are verified for internal consistency, not independently re-forwarded."},
        "recomputed_pairwise_summary": families,
        "original_strict_parser": {"parseable_by_arm": dict(parse_counts), "strict_correct_by_arm": dict(strict_counts),
            "interpretation": "All outputs include punctuation and/or expressions; strict0 is a formatting/parser result, not 80 mathematical failures."},
        "free_generation_tokens_by_arm": dict(token_counts), "total_free_generation_tokens": sum(token_counts.values()),
        "recorded_run_wall_seconds": summary["elapsed_seconds"], "recorded_load_and_hash_seconds": manifest["load_and_hash_seconds"],
        "model_gpu": {"name": manifest["gpu"]["name"], "dtype": manifest["dtype"], "attention": manifest["attention"],
                      "model_path": manifest["model_files"]["local_model_directory"], "versions": manifest["versions"]},
        "cases": cases, "all_80_original_texts": texts,
        "manually_unambiguous_control_counterexamples": [
            {"case_id": "C01", "correct_z_from_original_definitions": 31, "full_text": "31。", "target_late_text": "43。", "target_early_text": "37。"},
            {"case_id": "C04", "correct_z_from_original_definitions": 20, "full_text": "20。", "target_late_text": "17-9=8。", "target_early_text": "17-9=8。"},
            {"case_id": "W01", "correct_z_from_original_definitions": 28, "full_text": "28。", "target_late_text": "11。", "target_early_text": "11。"},
            {"case_id": "W03", "correct_z_from_original_definitions": 121, "full_text": "121。", "target_late_text": "7*7=49。", "target_early_text": "49。"},
        ],
        "decision": "NO_GO for unconditional Wait/branch-deletion as a safe correction method; cache-state mechanism is supported, positive algorithm/goodput claims are not.",
        "artifact_hashes": artifacts, "elapsed_audit_seconds": time.perf_counter()-started,
    }
    output = ROOT / "independent_real_p0_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["status","numeric_comparison_count_including_json_summary_duplicates",
        "numeric_json_metric_count","max_abs_numeric_disagreement","controls","recomputed_pairwise_summary",
        "original_strict_parser","total_free_generation_tokens","recorded_run_wall_seconds"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
