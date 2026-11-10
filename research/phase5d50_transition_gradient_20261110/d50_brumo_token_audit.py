"""Report context occupancy for whole archive thinking under the pinned student tokenizer."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

import transformers
from transformers import AutoTokenizer

from d50_brumo_archive import write_new


SOURCE_SHA = "7261f1a1d2ec4873256f48238515d19ad9069f286ca857655438b6d5df99af70"
RULE_SHA = "fb3c2872152bdaa2316e6dc9e467fc93d886082a643cc0338a2e2283ac070741"
TOKENIZER_ASSETS = {
    "tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
    "tokenizer_config.json": "d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101",
}
CHECKPOINT_LIMIT = 40960
CUE = re.compile(r"\b(?:wait|actually|mistake|error|incorrect|wrong|correction|contradiction|recalculate|double-check)\b", re.I)


def digest(contents):
    return sha256(contents).hexdigest()


def audit(source, tokenizer_dir, output):
    raw = source.read_bytes()
    rules = Path(__file__).with_name("D50_BRUMO_SCOPE_RULES.json").read_bytes()
    if digest(raw) != SOURCE_SHA or digest(rules) != RULE_SHA or any(
        digest((tokenizer_dir / name).read_bytes()) != expected for name, expected in TOKENIZER_ASSETS.items()
    ):
        raise ValueError("input source, inspection rules, or tokenizer identity differs")
    limit = json.loads(rules)["prefix_unicode_characters"]
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir, trust_remote_code=False, local_files_only=True)
    rows = []
    for row in json.loads(raw)["rows"]:
        thought = row["thinking"]
        receipt = {k: row[k] for k in ("case_id", "sample_uid", "split", "reasoning_sha256", "reasoning_kind")}
        if thought is None:
            rows.append(receipt | {"status": "UNKNOWN_THINKING_UNAVAILABLE"})
            continue
        if digest(thought.encode()) != row["reasoning_sha256"] or digest(row["user_message"].encode()) != row["user_message_sha256"]:
            raise ValueError("question prompt or thinking identity differs")
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": row["user_message"]}], tokenize=False,
            add_generation_prompt=True, enable_thinking=True,
        )
        if not prompt.endswith("<|im_start|>assistant\n"):
            raise ValueError("unexpected pinned student chat template")
        prefix = prompt if thought.startswith("<think>") else prompt + "<think>\n"
        ids = tokenizer.encode(prefix + thought, add_special_tokens=False, truncation=False, verbose=False)
        thinking_ids = tokenizer.encode(thought, add_special_tokens=False, truncation=False, verbose=False)
        status = "THINKING_PREFIX_FITS" if len(ids) <= CHECKPOINT_LIMIT else "WHOLE_THINKING_PREFIX_EXCEEDS_CONTEXT"
        hits = list(CUE.finditer(thought[:limit]))
        rows.append(receipt | {
            "status": status,
            "thinking_characters": len(thought),
            "standalone_thinking_tokens": len(thinking_ids),
            "student_serialized_prompt_and_thinking_tokens": len(ids),
            "student_context_remaining_without_final_or_pair": CHECKPOINT_LIMIT - len(ids),
            "publisher_cot_ends_with_think_tag": thought.rstrip().endswith("</think>"),
            "inspection_window_characters": min(len(thought), limit),
            "early_lexical_cue_count": len(hits),
            "early_first_cue_position": hits[0].start() if hits else None,
        })
    write_new(output, {
        "status": "D50_WHOLE_ARCHIVED_THINKING_REENCODED_WITHOUT_TRUNCATION",
        "source_sha256": SOURCE_SHA, "scope_rules_sha256": RULE_SHA,
        "tokenizer_sha256": TOKENIZER_ASSETS, "student_checkpoint_context_limit": CHECKPOINT_LIMIT,
        "transformers_version": transformers.__version__,
        "whole_source_counts": dict(Counter(row["status"] for row in rows)),
        "serialization": "Pinned Qwen student chat template on exact publisher user message followed by separate cot unchanged. Insert one '<think>\\n' when cot has no opening tag. Counts use add_special_tokens=False and no truncation. Neither later pair nor final tokens included.",
        "scope": "Retokenization of publisher text, not publisher's generated token sequence or an EOS receipt. A closing </think> in published cot does not certify native final or stop. The 12000-character window is lexical screening only.",
        "rows": rows,
    })


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--thinking", required=True, type=Path)
    cli.add_argument("--tokenizer", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    audit(args.thinking, args.tokenizer, args.output)
