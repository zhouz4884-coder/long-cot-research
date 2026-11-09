"""Post-hoc diagnostic for complete integer boxes that frozen F2 declined."""

import json
import re

from prepare_d36_checkpoints import ROOT, sha, write_once


HEADING = re.compile(r"(?im)^\s*#{1,6}\s+(?:final\s+(?:answer|result|conclusion)|conclusion)\s*[:.]?\s*$")
INTEGER_BOX = re.compile(r"\\boxed\{\s*(\d{1,16})\s*\}")
BOX_OPEN = re.compile(r"\\(?:boxed|fbox)\s*\{")
TERMINAL = re.compile(r"\s*(?:\$\$|\$|\\\]|\\\))?\s*(?:is the \*\*greatest positive integer that is fibbish\*\*\.)?\s*", re.I)


def terminal_integer(text):
    headings = list(HEADING.finditer(text))
    start = headings[-1].end() if headings else 0
    region = text[start:]
    boxes = list(INTEGER_BOX.finditer(region))
    if len(boxes) != 1 or len(BOX_OPEN.findall(region)) != 1:
        return None
    box, = boxes
    if not TERMINAL.fullmatch(region[box.end():]):
        return None
    return int(box[1]), [start + box.start(), start + box.end()]


def run():
    checkpoints = {name: json.loads((ROOT / f"{name.upper()}_GPU_AUDIT.json").read_bytes())
                   for name in ("early", "late")}
    observations = []
    for name, audit in checkpoints.items():
        if audit["status"] != "PASS":
            raise ValueError("Run the frozen scoring and receipt audit first")
        for row in audit["model_arms"]:
            if row["readout"]["status"] == "ok" or not row["eos"]:
                continue
            path = ROOT / "gpu_results" / name / row["replicate"] / (row["arm"] + ".json")
            raw = path.read_bytes()
            trace = json.loads(raw)
            text = trace["delivered_final_response"]
            found = terminal_integer(text) if trace["think_closed"] and isinstance(text, str) else None
            observations.append({"checkpoint": name, "replicate": row["replicate"], "arm": row["arm"],
                                 "raw_file": path.relative_to(ROOT).as_posix(), "raw_sha256": sha(raw),
                                 "frozen_f2_reason": row["readout"].get("reason"),
                                 "terminal_integer": found[0] if found else None,
                                 "terminal_box_char_span": found[1] if found else None})
    for record in observations:
        reference = checkpoints[record["checkpoint"]]["historical_reference_after_close"]
        record["integer_matches_reference"] = record["terminal_integer"] == reference
    report = {"scope": "Exploratory E15 endpoint only. Rule written after seeing late F2 refusals; integer extraction ignores the answer key. No change to F2, live gate, raw outputs or capacity failures. It tests final scalar rendering, not proof correctness.",
              "rows": observations}
    write_once(ROOT / "D36_TERMINAL_SCALAR_DIAGNOSTIC.json", report)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
