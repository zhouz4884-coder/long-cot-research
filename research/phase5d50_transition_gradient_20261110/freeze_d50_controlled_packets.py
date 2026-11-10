"""Build disjoint, exactly checked E/W/C calibration packets for a pinned tokenizer."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ROLES = ("E", "W", "C")
EXPECTED_TOKENIZER = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"
EXPECTED_TEMPLATE = "d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101"


def sha(data):
    return sha256(data).hexdigest()


def wire(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def save(path, data):
    raw = wire(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def expression(mode, x, u, v, w):
    if mode == 0:
        return f"(x + {u}) * (x + {v}) - {w}", (x + u) * (x + v) - w
    if mode == 1:
        return f"(x + {u})^2 + {v} * (x + 1) - {w}", (x + u)**2 + v * (x + 1) - w
    return f"(x + {u}) * (x + {v}) + {u} - {v}", (x + u) * (x + v) + u - v


def next_record(rng, role, mode):
    while True:
        x, multiplier, offset = rng.randint(6, 14), rng.randint(4, 9), rng.randint(17, 83)
        u, v, w = rng.randint(5, 11), rng.randint(4, 9), rng.randint(18, 65)
        p, q = rng.randint(2, 3), rng.randint(13, 37)
        wrong = x + 1 if role == "W" else x - 1
        expr, y = expression(mode, x, u, v, w)
        _, y_bad = expression(mode, wrong, u, v, w)
        z, z_bad = p * y + q, p * y_bad + q
        if not all(100 <= value <= 999 for value in (y, y_bad, z, z_bad)):
            continue
        checksum = multiplier * x + offset
        question = (f"A ledger has an unknown integer x. The original checksum is {multiplier} * x + {offset} = "
                    f"{checksum}. Let y = {expr} and z = {p} * y + {q}. Determine z using the original checksum.")
        if role == "E":
            notes = (f"My initial ledger used x = {wrong}. Checking it against the original checksum rules it out. "
                     f"The corrected root is x = {x}, and it satisfies the original checksum.")
        elif role == "W":
            notes = (f"The ledger currently has x = {x}; it satisfies the original checksum. "
                     f"A tentative re-evaluation suggests changing x to {wrong}. The original equation still governs.")
        else:
            notes = (f"The accepted ledger has x = {x}, which satisfies the original checksum. "
                     "Reordering how I compute the dependent quantities does not modify the equation or the root.")
        prefix = notes + "\n\nNext compute the dependent entries.\n"
        if set(map(str, (y, y_bad, z, z_bad))) & set(re.findall(r"\d+", question + prefix)):
            continue
        if multiplier * x + offset != checksum or multiplier * wrong + offset == checksum or z == z_bad:
            raise AssertionError("Malformed original equation or paired counterexample")
        positive = f"Then y = {y}, and z = {z}."
        alternative = f"Then y = {y_bad}, and z = {z_bad}."
        if role == "E":
            transition = f"I must propagate the verified revision x = {x} to the dependent entries."
        elif role == "W":
            transition = f"I reject the tentative revision x = {wrong} and keep the verified value x = {x}."
        else:
            transition = f"I keep the existing value x = {x} and preserve the dependency."
        response = (transition + "\n\n" + positive
                    + "\n\nFor a separate check, reverse the final affine calculation and compare the result "
                      "with the dependent entry obtained from the original root. The two calculations agree. "
                      "The equation fixes a unique root, so no alternative root yields a second valid result."
                    + "\n</think>\n\n" + r"\boxed{" + str(z) + "}<|im_end|>\n")
        return {"question": question, "notes": prefix, "response": response,
                "positive": positive, "alternative": alternative, "role": role,
                "proof": {"formula_family": mode, "equation_coefficient": multiplier,
                          "equation_offset": offset, "equation_checksum": checksum, "root": x,
                          "alternative_root": wrong, "correct_dependent": [y, z],
                          "alternative_dependent": [y_bad, z_bad], "final_affine": [p, q]}}


def encode(tokenizer, text, *, offsets=False):
    return tokenizer(text, add_special_tokens=False, return_offsets_mapping=offsets)


def materialize(tokenizer, row, partition):
    prompt = tokenizer.apply_chat_template([{"role": "user", "content": row["question"]}],
                                           tokenize=False, add_generation_prompt=True, enable_thinking=True)
    prefix = prompt + row["notes"]
    prefix_ids = encode(tokenizer, prefix).input_ids
    pair = {"prefix_ids": prefix_ids}
    for target, field in (("positive", "correct_ids"), ("alternative", "alternative_ids")):
        ids = encode(tokenizer, prefix + row[target]).input_ids
        if ids[:len(prefix_ids)] != prefix_ids:
            return None
        pair[field] = ids[len(prefix_ids):]
    if not pair["correct_ids"] or len(pair["correct_ids"]) != len(pair["alternative_ids"]):
        return None
    result = {"role": row["role"]}
    if partition in ("Bprime", "H"):
        result["pair"] = pair
    if partition in ("B", "Bprime"):
        answer = str(row["proof"]["correct_dependent"][1])
        answer_start = len(prefix) + row["response"].rindex(r"\boxed{" + answer + "}") + len(r"\boxed{")
        answer_end = answer_start + len(answer)
        encoded = encode(tokenizer, prefix + row["response"], offsets=True)
        if encoded.input_ids[:len(prefix_ids)] != prefix_ids:
            return None
        answer_positions = [i for i, (start, stop) in enumerate(encoded.offset_mapping)
                            if start < answer_end and stop > answer_start]
        if (not answer_positions or encoded.offset_mapping[answer_positions[0]][0] != answer_start
                or encoded.offset_mapping[answer_positions[-1]][1] != answer_end):
            return None
        result.update({"input_ids": encoded.input_ids, "target_start": len(prefix_ids),
                       "answer_positions": answer_positions})
    return result


def packet(tokenizer, *, name, seed, counts, used):
    rng = Random(seed)
    samples, proof, rejects = {}, {}, Counter()
    for partition, per_role in counts.items():
        samples[partition], proof[partition] = [], []
        for role in ROLES:
            for index in range(per_role):
                mode = (index + ROLES.index(role)) % 3
                while True:
                    record = next_record(rng, role, mode)
                    question_sha = sha(record["question"].encode())
                    if question_sha in used:
                        rejects["duplicate_question"] += 1
                        continue
                    row = materialize(tokenizer, record, partition)
                    if row is None:
                        rejects["tokenization_boundary_or_pair_length"] += 1
                        continue
                    used.add(question_sha)
                    break
                problem_id = f"{name}-{partition}-{role}-{index + 1:02d}"
                row.update({"case_id": problem_id, "problem_id": problem_id})
                samples[partition].append(row)
                proof[partition].append({**record, "problem_id": problem_id, "question_sha256": question_sha})
    return samples, proof, dict(rejects)


def main():
    from transformers import AutoTokenizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "outputs/d2_tokenizer_20261107")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/d50_controlled_packets_20261110")
    parser.add_argument("--receipt", type=Path, default=HERE / "D50_CONTROLLED_PACKET_FREEZE.json")
    args = parser.parse_args()
    assets = {}
    for name, expected in (("tokenizer.json", EXPECTED_TOKENIZER), ("tokenizer_config.json", EXPECTED_TEMPLATE)):
        assets[name] = sha((args.tokenizer / name).read_bytes())
        if assets[name] != expected:
            raise ValueError("Tokenizer differs from the pinned Qwen3-4B input")
    if not args.output_dir.resolve().is_relative_to((ROOT / "outputs").resolve()):
        raise ValueError("Token packets remain local")
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True, trust_remote_code=False)
    if not tokenizer.is_fast:
        raise ValueError("Exact answer offsets require a fast tokenizer")
    used = set()
    summary = []
    for name, seed, counts in (("DEV", 8161, {"B": 1, "Bprime": 1, "H": 1}),
                               ("CONTROL", 17911, {"B": 3, "Bprime": 3, "H": 4})):
        samples, proof, rejects = packet(tokenizer, name=name, seed=seed, counts=counts, used=used)
        files = {"packet": args.output_dir / f"d50_{name.lower()}_ids.json",
                 "proof": args.output_dir / f"d50_{name.lower()}_proof.json"}
        ids_sha = save(files["packet"], samples)
        proof_sha = save(files["proof"], proof)
        summary.append({"packet": name, "seed": seed, "token_packet_sha256": ids_sha, "private_proof_sha256": proof_sha,
                        "counts": {k: len(v) for k, v in samples.items()}, "rejected": rejects,
                        "source_scope": "Fully synthetic arithmetic and paired prefix control, no natural trajectory",
                        "rows": [{k: row[k] for k in ("case_id", "problem_id", "role")} |
                                 {"partition": partition, "teacher_tokens": len(row.get("input_ids", ())),
                                  "pair_prefix_tokens": len(row.get("pair", {}).get("prefix_ids", ())),
                                  "pair_candidate_tokens": len(row.get("pair", {}).get("correct_ids", ()))}
                                 for partition, rows in samples.items() for row in rows]})
    result = {"status": "D50_SYNTHETIC_CALIBRATION_AND_CONTROL_FROZEN_NO_MODEL_CALL",
              "tokenizer_hashes": assets, "generator_sha256": sha(Path(__file__).read_bytes()),
              "distinct_questions": len(used), "packets": summary}
    print(save(args.receipt, result))


if __name__ == "__main__":
    main()
