"""Close the blinded generation bank before evaluation answers are opened."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root, relative):
    if (type(relative) is not str or "\\" in relative or Path(relative).is_absolute()
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("An artifact needs a contained relative path")
    candidate = root
    for part in relative.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Artifact symlinks are not supported")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Artifact leaves the generation directory")
    return path


def collect_generation(root):
    """Validate all required records without reading evaluation answer bytes."""
    root = Path(root).resolve()
    coverage = read(safe_path(root, "COVERAGE_AUDIT.json"))
    if coverage["status"] != "COMPLETE" or coverage["integrity_status"] != "PASS":
        raise ValueError("Complete, passing natural coverage audit is required")
    selection = read(safe_path(root, "PAIR_SELECTION.json"))
    if selection["status"] != "FROZEN":
        raise ValueError("Natural event selection is not frozen")
    policy_sha = sha(safe_path(root, "PAIRING_PROTOCOL.json"))
    if coverage["policy_sha256"] != policy_sha or selection["policy_sha256"] != policy_sha:
        raise ValueError("Coverage and selection use different pairing policies")
    native = sorted((root / "native_results").glob("worker_*/D2_*/result.json"))
    protocol = read(safe_path(root, "COVERAGE_PROTOCOL.json"))
    data_manifest = read(safe_path(root, "DATA_MANIFEST.json"))
    visible_raw = safe_path(root, "d2_visible.jsonl").read_bytes()
    if hashlib.sha256(visible_raw).hexdigest() != data_manifest["visible_sha256"]:
        raise ValueError("Visible problem bank differs from its source manifest")
    cases = list(map(json.loads, visible_raw.splitlines()))
    case_ids = [case["case_id"] for case in cases]
    seeds = protocol["seeds"]
    if (not 24 <= len(cases) <= 32 or len(cases) != protocol["questions"] or len(set(case_ids)) != len(cases)
            or len(seeds) < 2 or len(set(seeds)) != len(seeds) or any(type(seed) is not int for seed in seeds)):
        raise ValueError("Duplicate or incomplete question/seed protocol")
    expected = {(case["case_id"], seed) for case in cases
                for seed in protocol["seeds"]}
    observed = set()
    records = []
    loaded = {}

    def record(path, case_id, seed, arm, bank):
        relative = path.relative_to(root).as_posix()
        path = safe_path(root, relative)
        raw = path.read_bytes()
        result = json.loads(raw)
        if result.get("status") != "COMPLETE":
            raise ValueError("Generation record is incomplete")
        if result.get("case_id") != case_id or type(result.get("seed")) is not int or result["seed"] != seed:
            raise ValueError("Record identity differs")
        if (bank == "all_natural" and result.get("arm", "NativeContinue") != arm
                or bank != "all_natural" and result.get("arm") != arm):
            raise ValueError("Record arm differs")
        if (type(result.get("final_response")) is not str or type(result.get("EOS")) is not bool
                or type(result.get("think_closed")) is not bool or type(result.get("stop_reason")) is not str
                or type(result.get("new_tokens")) is not int):
            raise ValueError("Missing delivery fields")
        for field in ("prompt_ids", "generated_ids"):
            if type(result.get(field)) is not list or any(type(token) is not int or token < 0 for token in result[field]):
                raise ValueError("Invalid token record")
        if not result["prompt_ids"] or result["new_tokens"] != len(result["generated_ids"]):
            raise ValueError("Invalid token counts")
        if relative in loaded:
            raise ValueError("A generation was registered twice")
        loaded[relative] = result
        records.append({"case_id": case_id, "seed": seed, "arm": arm, "bank": bank,
                        "path": relative, "sha256": hashlib.sha256(raw).hexdigest()})

    for path in native:
        case_id, seed_text = path.parent.name.rsplit("_", 1)
        key = (case_id, int(seed_text))
        if key in observed:
            raise ValueError("Duplicate native trajectory")
        observed.add(key)
        record(path, *key, "NativeContinue", "all_natural")
    if observed != expected:
        raise ValueError("The complete frozen 48-run collection is required")
    audited_sources = {row["source_result"]: row["source_result_sha256"] for row in coverage["trajectories"]}
    actual_sources = {row["path"]: row["sha256"] for row in records}
    if len(audited_sources) != len(coverage["trajectories"]) or audited_sources != actual_sources:
        raise ValueError("Native sources changed after the coverage audit")
    selected_ids = [selected["case_id"] for selected in selection["selected"]]
    if len(selected_ids) != len(set(selected_ids)) or len(selected_ids) > 4:
        raise ValueError("Selected events must be distinct problems")
    role_reviews = read(safe_path(root, "ROLE_REVIEWS.json"))
    if role_reviews.get("selection_sha256") != sha(root / "PAIR_SELECTION.json"):
        raise ValueError("Role reviews do not bind the selected events")
    review_keys = [(review["case_id"], review["seed"], review["event_step"]) for review in role_reviews["reviews"]]
    selected_keys = [(selected["case_id"], selected["seed"], selected["step"]) for selected in selection["selected"]]
    if len(review_keys) != len(set(review_keys)) or set(review_keys) != set(selected_keys):
        raise ValueError("Role review membership differs")
    repair_outcomes = []
    for selected in selection["selected"]:
        if (selected["case_id"], selected["seed"]) not in expected:
            raise ValueError("Selected event is outside the natural bank")
        source = safe_path(root, selected["source_result"])
        if sha(source) != selected["source_result_sha256"] or selected["source_result"] not in loaded:
            raise ValueError("Selected source differs from the frozen natural record")
        matches = list((root / "paired_results").glob(f"worker_*/{selected['case_id']}_{selected['seed']}"))
        if len(matches) != 1:
            raise ValueError("Missing or duplicate paired case")
        folder = matches[0]
        summary = read(safe_path(root, (folder / "summary.json").relative_to(root).as_posix()))
        if (summary.get("case_id"), summary.get("seed")) != (selected["case_id"], selected["seed"]):
            raise ValueError("A paired case did not close")
        for arm in ("NativeContinue", "UnknownIdentity", "InContextCheck", "UnscopedIsolatedCheck", "ScopedIsolatedCheck"):
            record(folder / (arm + ".json"), selected["case_id"], selected["seed"], arm, "selected_events")
        repair = read(safe_path(root, (folder / "repair" / "REPAIR_STATUS.json").relative_to(root).as_posix()))
        if (repair.get("case_id"), repair.get("seed")) != (selected["case_id"], selected["seed"]):
            raise ValueError("Repair diagnostic identity differs")
        if repair["status"] not in ("COMPLETE", "NOT_ELIGIBLE"):
            raise ValueError("Repair diagnostic is unfinished")
        if repair["status"] == "NOT_ELIGIBLE" and repair.get("arms") != []:
            raise ValueError("An ineligible case contains undisclosed repair arms")
        repair_outcomes.append({"case_id": selected["case_id"], "seed": selected["seed"], "status": repair["status"],
                                "path": (folder / "repair" / "REPAIR_STATUS.json").relative_to(root).as_posix(),
                                "sha256": sha(folder / "repair" / "REPAIR_STATUS.json")})
        if repair["status"] == "COMPLETE":
            if {arm["arm"] for arm in repair["arms"]} != {"GenericRewind", "RebaseNoCarry", "RebaseCarry", "FullRestart", "SameEvidenceCompactBridge", "Resampling"} or len(repair["arms"]) != 6:
                raise ValueError("The licensed repair arm bank is incomplete")
            for arm in repair["arms"]:
                relative = folder.relative_to(root).as_posix() + "/" + arm["path"]
                record(safe_path(root, relative), selected["case_id"], selected["seed"], arm["arm"], "licensed_repair")
    output = {"status": "FROZEN", "created_utc": datetime.now(timezone.utc).isoformat(),
              "native_problems": protocol["questions"], "native_trajectories": len(native),
              "paired_distinct_problems": len(selection["selected"]), "records": records,
              "repair_outcomes": repair_outcomes,
              "selection_sha256": sha(root / "PAIR_SELECTION.json"),
              "coverage_audit_sha256": sha(root / "COVERAGE_AUDIT.json"),
              "data_manifest_sha256": sha(root / "DATA_MANIFEST.json"),
              "coverage_protocol_sha256": sha(root / "COVERAGE_PROTOCOL.json"),
              "pairing_protocol_sha256": sha(root / "PAIRING_PROTOCOL.json"),
              "role_reviews_sha256": sha(root / "ROLE_REVIEWS.json"),
              "eval_expected_sha256": data_manifest["eval_sha256"],
              "scope": "No answer file read. Source selection, role review and completed generation bank fixed before evaluation."}
    return output, loaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    destination = root / "GENERATION_FREEZE.json"
    if destination.exists():
        raise ValueError("The evaluation bank is already frozen")
    output, _ = collect_generation(root)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: output[key] for key in ("status", "native_trajectories", "paired_distinct_problems")}, indent=2))


if __name__ == "__main__":
    main()
