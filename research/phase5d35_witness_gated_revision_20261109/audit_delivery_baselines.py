"""Re-read a paid terminal thought and test no harm on a correct historical draft."""

import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

from audit_dev_checkpoints import D3, make_tokenizer

sys.path.append(str(D3))
from complete_answer import _rational
from complete_answer_v2 import extract_final_answer
from development_worker import typed_gate
from witness_verifier import OBSERVED, Witness


ROOT = Path(__file__).resolve().parent
TERMINAL_BOX = re.compile(r"\\boxed\s*\{\s*([+-]?[0-9]{1,18})\s*\}\s*\Z")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    tokenizer = make_tokenizer()
    close, = tokenizer.encode("</think>", add_special_tokens=False)
    native_path = ROOT / "gpu_results/e12/NativeContinue.json"
    source = native_path.read_bytes()
    row = json.loads(source)
    if not row["EOS"] or not row["think_closed"]:
        raise ValueError("The native E12 thought is not complete")
    last = max(i for i, token in enumerate(row["generated_ids"]) if token == close)
    started = time.perf_counter()
    thought = tokenizer.decode(row["generated_ids"][:last], skip_special_tokens=True)
    box = TERMINAL_BOX.search(thought)
    selection = None if box is None else int(box[1])
    lexical_seconds = time.perf_counter() - started
    main_score = json.loads((ROOT / "E12_GPU_AUDIT.json").read_bytes())
    prior = json.loads((ROOT / "gpu_results/e12/LastThoughtAnswer.json").read_bytes())
    chosen = {"method": "LastThoughtAnswerTerminalBox", "scope": "Gold-blind lexical readout of the last complete integer box at native think-close",
              "native_source_sha256": sha(source), "thought_sha256": sha(thought.encode()), "think_close_token_index": last,
              "source_text": None if box is None else box[0], "value": selection,
              "correct": selection == _rational(main_score["historical_gold_after_close"]),
              "standalone_source_work_through_think_close": prior["source_cost_through_think_close"],
              "readout_CPU_seconds": lexical_seconds, "initial_whole_thought_extractor_status": prior["selection"]["status"],
              "initial_whole_thought_extractor_reason": prior["selection"].get("reason")}

    path, = (D3 / "bank/native_results").glob("worker_*/D3_E12_20261109/result.json")
    raw = path.read_bytes()
    retrieved = {x["path"]: x["sha256"] for x in json.loads((D3 / "BANK_RETRIEVAL.json").read_bytes())["files"]}
    if sha(raw) != retrieved[path.relative_to(D3).as_posix()]:
        raise ValueError("Correct historical control changed")
    peer = json.loads(raw)
    packet = json.loads((ROOT / "prepared/e12_checkpoint.json").read_bytes())
    packet.update(seed=peer["seed"], prompt_ids=peer["prompt_ids"])
    identity = SimpleNamespace(tokenizer_sha256=sha((ROOT.parents[1] / "outputs/d2_tokenizer_20261107/tokenizer.json").read_bytes()))
    gate = typed_gate(packet, SimpleNamespace(tokenizer=tokenizer), identity, peer["generated_ids"])
    revision = next((item for item in reversed(gate.records) if item.goal_claim_type == "FINAL_ANSWER_REVISION"), None)
    tested = []
    if revision is not None:
        for item in reversed(gate.records):
            if item.segment == "thinking" and item.goal_claim_type in ("EXACT_ANSWER", "FEASIBLE_CANDIDATE"):
                tested.append(gate.verify(revision.candidate_id, Witness(OBSERVED, item.candidate_id)))
    selection_peer = extract_final_answer(peer["final_response"], "scalar")
    delivered_peer = _rational(selection_peer["components"][0]) if selection_peer["status"] == "ok" else None
    intact = delivered_peer == _rational(main_score["historical_gold_after_close"]) and not any(
        verdict["action"] == "VETO_DRAFT_AND_DELIVER_CERTIFIED" for verdict in tested)
    control = {"seed": peer["seed"], "source_sha256": sha(raw), "scope": "Already generated correct development trajectory, CPU replay only",
               "explicit_revision_trigger": revision is not None, "unchanged_correct_native_delivery": intact,
               "delivered_value": None if delivered_peer is None else str(delivered_peer), "tested_gate_receipts": tested}
    result = {"status": "PASS" if chosen["correct"] and intact else "FAIL", "actual_paid_thought_terminal_readout": chosen,
              "historical_correct_peer_control": control, "additional_GPU_seconds": 0}
    out = ROOT / "E12_DELIVERY_BASELINES.json"
    out.write_bytes((json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
