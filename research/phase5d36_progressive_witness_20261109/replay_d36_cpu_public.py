"""Reproduce the D3.6 CPU reports in a new directory from public inputs."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen

import audit_d3_cross_phase as cross_phase
import audit_numeric_context as numeric_review


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "D36_CPU_TOKENIZER_ASSETS.json"
OBSERVATION_NAME = cross_phase.OBSERVATIONS.name
SCORE_NAME = cross_phase.SCORES.name
REVIEW_NAME = numeric_review.DESTINATION.name


def load(path):
    return json.loads(path.read_bytes())


def tokenizer_assets(destination, *, download):
    manifest = load(ASSETS)
    runtime = cross_phase.D35 / "gpu_results/e15/manifest.json"
    inherited = json.loads(cross_phase.verify_published(runtime))["model_files"]
    expected = {item["name"]: (item["size_bytes"], item["sha256"]) for item in inherited["files"]}
    if manifest["model_manifest"] != inherited["manifest_sha256"]:
        raise ValueError("Tokenizer asset manifest does not identify the published D3.5 runtime")
    names = {item["path"] for item in manifest["files"]}
    if names != {"tokenizer.json", "tokenizer_config.json", "merges.txt", "vocab.json", "config.json",
                 "generation_config.json"} or len(manifest["files"]) != len(names):
        raise ValueError("Unexpected tokenizer asset membership")
    if download:
        destination.mkdir(exist_ok=False)
    for item in manifest["files"]:
        name, size, digest = item["path"], item["bytes"], item["sha256"]
        path = destination / name
        if expected.get(name) != (size, digest):
            raise ValueError(f"Tokenizer asset differs from the published runtime manifest: {name}")
        if download:
            request = Request(manifest["download_root"] + name, headers={"User-Agent": "D36-CPU-replay/1.0"})
            with urlopen(request, timeout=60) as response:
                raw = response.read(size + 1)
        else:
            raw = path.read_bytes()
        if len(raw) != size or sha256(raw).hexdigest() != digest:
            raise ValueError(f"Tokenizer asset size or SHA-256 differs: {name}")
        if download:
            with path.open("xb") as stream:
                stream.write(raw)
    return manifest


def stable_report(path):
    report = load(path)
    if path.name == OBSERVATION_NAME:
        report.pop("frozen_utc")
        for row in report["trajectories"]:
            row["gate"].pop("verification_wall_seconds", None)
    else:
        report.pop("first_reference_read_utc", None)
        report.pop("frozen_observation_sha256")
    return report


def report_digests(directory):
    def canonical(path):
        return json.dumps(stable_report(path), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    results = {}
    for name in (OBSERVATION_NAME, SCORE_NAME, REVIEW_NAME):
        original, replayed = canonical(ROOT / name), canonical(directory / name)
        if original != replayed:
            raise ValueError(f"Replayed evidence differs after removing timestamps and linked digests: {name}")
        results[name] = sha256(replayed).hexdigest()
    return results


def reverse_feasible_only_control(tokenizer, tokenizer_sha):
    """A typed, synthetic E15 reverse case with a trusted partial certificate."""
    visible = cross_phase.D3 / "prepared_data/bank/visible.jsonl"
    case, = (r for r in map(json.loads, cross_phase.verify_published(visible).splitlines())
             if r["case_id"] == "D3_E15")
    target = cross_phase.target_metadata(case)
    thought = "\nThe seven-digit number is 1011235. 1011235 is valid.\n\nFinal Answer\n\\boxed{1011235}\n"
    final = "\nFinal Answer\n\\boxed{10112369}\n"
    text = "<think>" + thought + "</think>" + final + "<|im_end|>"
    raw = {"generated_ids": tokenizer.encode(text, add_special_tokens=False),
           "prompt_ids": tokenizer.encode(case["question"], add_special_tokens=False), "seed": 0}
    prior = cross_phase.thinking_readout(thought, target)
    _, delivery = cross_phase.final_observation(final, target)
    comparison = cross_phase.numeric_same(prior["selection"], delivery["selection"])
    contract = cross_phase.compile_contract(case["question"])
    prefix = cross_phase.ObservedPrefix.from_tokens(
        raw["generated_ids"], lambda ids: tokenizer.decode(list(ids), skip_special_tokens=False),
        prompt_ids=raw["prompt_ids"], tokenizer_sha256=tokenizer_sha,
        trajectory_id=case["case_id"] + "_0", question_sha256=cross_phase.sha(case["question"].encode()),
    )
    gate = cross_phase.WitnessGate(contract, prefix)
    incumbent, = (r for r in gate.records if r.goal_claim_type == "FEASIBLE_CANDIDATE"
                  and r.value == 1011235 and r.segment == "thinking")
    partial = gate.verify(incumbent.candidate_id)
    decision = cross_phase.certificate_for_change(case, raw, prior, prior["selection"], comparison,
                                                  tokenizer, tokenizer_sha)
    if (comparison != "DIFFERENT_VALUE" or partial["status"] != "FEASIBLE_ONLY"
            or partial["mathematical"]["proof_scope"] != "FULL_ORIGINAL_CONSTRAINTS"
            or partial["released_value"] is not None or decision["action"] != "RETAIN_NATIVE"):
        raise ValueError("A feasible point must not veto a different final objective")
    return {"scope": "Synthetic, already-completed source only. The correct fixture value is not an online cue.",
            "case_id": case["case_id"], "thinking_objective": prior["selection"]["components"],
            "final_objective": delivery["selection"]["components"], "comparison": comparison,
            "thinking_candidate_certificate": partial, "gate_action": decision["action"],
            "gate_reason": decision["reason"]}


def replay(output, supplied_tokenizer):
    from transformers import AutoTokenizer

    output.mkdir(parents=True, exist_ok=False)
    local_tokenizer = supplied_tokenizer if supplied_tokenizer is not None else output / "tokenizer"
    manifest = tokenizer_assets(local_tokenizer, download=supplied_tokenizer is None)
    tokenizer = AutoTokenizer.from_pretrained(local_tokenizer, local_files_only=True, trust_remote_code=False)
    cross_phase.TOKENIZER = local_tokenizer
    cross_phase.make_tokenizer = lambda: tokenizer
    cross_phase.OBSERVATIONS = output / OBSERVATION_NAME
    cross_phase.SCORES = output / SCORE_NAME
    numeric_review.OBSERVATIONS = output / OBSERVATION_NAME
    numeric_review.DESTINATION = output / REVIEW_NAME
    cross_phase.observe()
    cross_phase.score(sha256(cross_phase.OBSERVATIONS.read_bytes()).hexdigest())
    numeric_review.main()
    digests = report_digests(output)
    control = reverse_feasible_only_control(tokenizer, sha256((local_tokenizer / "tokenizer.json").read_bytes()).hexdigest())
    receipt = {"status": "PASS", "tokenizer_source": manifest["source"], "tokenizer_revision": manifest["revision"],
               "tokenizer_files_verified": len(manifest["files"]),
               "tokenizer_asset_mode": "downloaded_and_verified" if supplied_tokenizer is None else "local_and_verified",
               "stable_report_sha256": digests, "synthetic_reverse_feasibility_control": control,
               "additional_gpu_seconds": 0}
    cross_phase.persist(output / "D36_CPU_REPLAY_RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "reports_matched": len(digests), "reverse_gate": control["gate_action"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="A new directory for all replay results")
    parser.add_argument("--tokenizer-dir", type=Path, help="Optional existing tokenizer asset directory for offline use")
    args = parser.parse_args()
    replay(args.output_dir.resolve(), None if args.tokenizer_dir is None else args.tokenizer_dir.resolve())


if __name__ == "__main__":
    main()
