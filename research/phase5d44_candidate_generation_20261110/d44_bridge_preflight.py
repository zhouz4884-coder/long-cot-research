"""CPU check of the exact frozen cues against the pinned Qwen tokenizer."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from d44_native_runner import MAX_NEUTRAL_PADDING, matched_bridges, sha, validate_cases, write
from obligation_trigger import approved_obligation, check, detect


MODEL = "37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511"
SYNTHETIC_SCOPES = {
    "2016-I-9": "Consider the greatest area of the rectangle.",
    "2012-I-10": "Consider the tenth remainder modulo 1000.",
    "2018-I-11": "Consider the least exponent with suffix 143.",
    "2012-II-8": "Consider the smallest modulus.",
    "2019-I-5": "Consider m+n at the origin.",
    "2017-I-9": "Consider the least integer satisfying divisibility by 99.",
    "2009-II-8": "Consider m+n for the stopping rule.",
}


def run(packet, tokenizer_dir):
    from transformers import AutoTokenizer

    started = perf_counter()
    raw = packet.read_bytes()
    cases = validate_cases(json.loads(raw))
    manifest_bytes = (tokenizer_dir / "TOKENIZER_FETCH_MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["model_manifest"] != MODEL:
        raise ValueError("Tokenizer receipt is for a different model")
    for record in manifest["files"]:
        path = tokenizer_dir / record["path"]
        data = path.read_bytes()
        if len(data) != record["bytes"] or sha(data) != record["sha256"]:
            raise ValueError("A tokenizer asset differs from its frozen bytes")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir, local_files_only=True, trust_remote_code=False)
    engine = SimpleNamespace(tokenizer=tokenizer, eos={151643, 151645},
                             open_ids=tokenizer.encode("<think>", add_special_tokens=False),
                             close_ids=tokenizer.encode("</think>", add_special_tokens=False))
    rows = []
    for case in cases:
        item = approved_obligation(case)
        if case["obligation"] is None:
            assert detect(case, r"Final answer: \boxed{0}.") is None
            rows.append({"case_id": case["case_id"], "status": "CONTROL_WITHOUT_OBLIGATION"})
            continue
        if item is None:
            raise ValueError("An active frozen cue failed detector admission")
        wrong = next(value for value in range(1000) if check(value, item)[0])
        good = next(value for value in range(1000) if not check(value, item)[0])
        claim = "\nFinal answer: " + r"\boxed{"
        prefix = SYNTHETIC_SCOPES[case["case_id"]] + claim
        wrong_tail = str(wrong) + "}."
        evidence = detect(case, prefix + wrong_tail)
        if (evidence is None or evidence["cue"] != item["cue"]
                or detect(case, prefix + str(good) + "}.") is not None
                or detect(case, "Compute an intermediate quantity." + claim + wrong_tail) is not None):
            raise ValueError("Synthetic explicit-claim detector control differs from the frozen cue")
        bridges = matched_bridges(engine, evidence["cue"])
        generic, typed = bridges["GenericReminder"], bridges["TypedObligation"]
        if generic["forced_tokens"] != typed["forced_tokens"] or generic["padding_tokens"] > MAX_NEUTRAL_PADDING:
            raise ValueError("Fluent generic bridge did not match the actual typed token budget")
        rows.append({"case_id": case["case_id"], "status": "EXACT_TOKEN_MATCH", "typed_cue_sha256": sha(item["cue"].encode()),
                     "forced_tokens_per_arm": typed["forced_tokens"], "generic_unpadded_tokens": generic["unpadded_tokens"],
                     "typed_unpadded_tokens": typed["unpadded_tokens"], "generic_padding_tokens": generic["padding_tokens"],
                     "typed_padding_tokens": typed["padding_tokens"], "chosen_generic": generic["fluent_variant"]})
    here = Path(__file__).parent
    return {"status": "PASS_CPU_EXACT_TOKENIZER_BRIDGES", "scope": "Synthetic scoped triggering of the actual frozen cue text. No response, score or model weights opened.",
            "packet_sha256": sha(raw), "tokenizer_manifest_sha256": sha(manifest_bytes), "model_manifest_sha256": MODEL,
            "runtime_runner_sha256": sha((here / "d44_native_runner.py").read_bytes()),
            "trigger_source_sha256": sha((here / "obligation_trigger.py").read_bytes()),
            "active_cues": sum(row["status"] == "EXACT_TOKEN_MATCH" for row in rows), "rows": rows,
            "elapsed_seconds": perf_counter() - started}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for flag in ("packet", "tokenizer-dir", "output"):
        cli.add_argument("--" + flag, type=Path, required=True)
    args = cli.parse_args()
    result = run(args.packet, args.tokenizer_dir)
    write(args.output, result)
    print(json.dumps({"status": result["status"], "active_cues": result["active_cues"],
                      "budgets": [[r["case_id"], r.get("forced_tokens_per_arm"), r.get("generic_padding_tokens")]
                                  for r in result["rows"]]}))
