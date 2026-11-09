"""Bind eight independently reviewed question-only proposals to the live packet."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from obligation_trigger import SCOPE_PATTERNS, approved_obligation, digest

HERE = Path(__file__).resolve().parent
REVIEWED = {
    "2016-I-9": "The placement determinant is nonnegative. The extra product is bounded by half the square of the fixed side length.",
    "2012-I-10": "Square residues modulo 16 force the truncation parity, which survives remainder modulo 1000.",
    "2018-I-11": "The orders modulo the two primes are 5 and 3. The prime-square lift and leastness remain open.",
    "2012-II-10": "The interval is sound for the count. The extremal phrase defines floor, so the frozen row becomes an inactive scope control.",
    "2012-II-8": "Both roots of the product quadratic are attainable. Their product and triangle inequality give the two bounds.",
    "2019-I-5": "Only longest successful paths contribute modulo 3. They finish with the diagonal from (1,1).",
    "2017-I-9": "The triangular residue has period 99. The CRT existence proof bounds the least positive qualifying index.",
    "2009-II-8": "Both initial failures regenerate the event. Symmetry makes the absorbing contribution numerator even.",
}
SCOPE_CONTROL = "2012-II-10"


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def canonical(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def write(path, value):
    content = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(content)
    return sha256(content).hexdigest()


def checked_anchors(proposal, question):
    checked = []
    for anchor in proposal.get("premise_anchors", proposal.get("premise_spans", [])):
        if "start" in anchor:
            a, b, expected = anchor["start"], anchor["end"], anchor["sha256"]
        else:
            a, b = anchor["char_span_0_based_half_open"]
            expected = anchor["sha256_utf8"]
        if not 0 <= a < b <= len(question) or digest(question[a:b]) != expected:
            raise ValueError("Unverified original-question anchor")
        checked.append({"char_span_0_based_half_open": [a, b], "sha256_utf8": expected})
    if len(checked) != 2:
        raise ValueError("Expected two premise anchors per question")
    return checked


def typed(spec):
    kind = spec["kind"].lower()
    if kind == "closed_interval":
        lo, hi = spec["args"] if "args" in spec else (spec["lo"], spec["hi"])
        return kind, [lo, hi], f"the requested integer must lie in [{lo}, {hi}]"
    if kind == "congruence":
        modulus, residue = spec["args"] if "args" in spec else (spec["modulus"], spec["residue"])
        return kind, [modulus, residue], f"the requested integer must be congruent to {residue} modulo {modulus}"
    raise ValueError(f"Unexpected predicate kind {kind}")


def compile_packet(visible, author_paths, archive_gate):
    cohort, cohort_sha = load(HERE / "D44_LIVE_COHORT_FREEZE.json")
    questions, visible_sha = load(visible)
    gate, gate_sha = load(archive_gate)
    rules, rules_sha = load(HERE / "D44_LIVE_RULE_FREEZE.json")
    trigger_sha = sha256((HERE / "obligation_trigger.py").read_bytes()).hexdigest()
    if gate["independent_development_problems_triggered"] < 2 or gate["sources"]["trigger_sha256"] != trigger_sha:
        raise ValueError("Exact trigger has not passed the two-problem archive gate")
    if visible_sha != cohort["visible_sha256"]:
        raise ValueError("Question-only projection differs from the cohort freeze")
    proposals, author_shas = [], []
    for path in author_paths:
        authored, author_sha = load(path)
        if authored["visible_sha256"] != visible_sha:
            raise ValueError("Authoring used different question-only bytes")
        author_shas.append(author_sha)
        proposals.extend(authored["rows"])
    if len(proposals) != rules["independent_questions"] or set(REVIEWED) != {r["case_id"] for r in proposals}:
        raise ValueError("Independent review is incomplete")
    cases, public = [], []
    for i, (row, frozen, proposal) in enumerate(zip(questions["rows"], cohort["rows"], proposals, strict=True)):
        pid, question = row["case_id"], row["question"]
        if (
            proposal.get("position", proposal.get("index")) != i or proposal["case_id"] != pid
            or digest(question) != row["question_sha256"] or proposal["question_sha256"] != row["question_sha256"]
            or {k: v for k, v in row.items() if k != "question"} != frozen
        ):
            raise ValueError("Authored proposal is for a different frozen problem")
        kind, args, premise = typed(proposal["predicate"])
        decision = "SCOPE_CONTROL" if pid == SCOPE_CONTROL else "APPROVE"
        review = {
            "case_id": pid, "question_sha256": row["question_sha256"],
            "authored_proposal_sha256": canonical(proposal), "decision": decision,
            "review_note": REVIEWED[pid], "anchors": checked_anchors(proposal, question),
            "proof_sha256": digest(proposal["proof"]),
        }
        review_sha = canonical(review)
        action = proposal.get("cue", proposal.get("remaining_obligation_cue"))
        cue = f"The boxed candidate violates a necessary condition: {premise}. {action}"
        effective = row["problem_kind"] if decision == "APPROVE" else "SCOPE_CONTROL"
        obligation = {"kind": kind, "args": args, "cue": cue, "question_sha256": row["question_sha256"],
                      "proof_sha256": review["proof_sha256"], "review_sha256": review_sha,
                      "scope_patterns": SCOPE_PATTERNS.get(pid)}
        case = {k: row[k] for k in ("case_id", "question", "question_sha256", "seed", "restart_seed")}
        case.update(problem_kind=effective, obligation=obligation if decision == "APPROVE" else None)
        if decision == "APPROVE" and approved_obligation(case) is None:
            raise ValueError(f"Reviewed condition is not usable for {pid}")
        cases.append(case)
        public.append({**review, "review_sha256": review_sha, "seed": row["seed"],
                       "restart_seed": row["restart_seed"], "effective_problem_kind": effective,
                       "obligation": case["obligation"]})
    return cases, {
        "status": "EXACT_LIVE_INPUT_FROZEN_BEFORE_NATIVE_GENERATION",
        "cohort_freeze_sha256": cohort_sha, "question_only_sha256": visible_sha,
        "author_sha256": author_shas, "archive_trigger_replay_sha256": gate_sha,
        "trigger_sha256": trigger_sha, "rules_sha256": rules_sha,
        "reviewed_active_scope": sum(row["decision"] == "APPROVE" for row in public), "rows": public,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--question-only", type=Path, required=True)
    cli.add_argument("--authors", type=Path, nargs=2, required=True)
    cli.add_argument("--archive-gate", type=Path, required=True)
    cli.add_argument("--local-packet", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists() or args.local_packet.exists():
        cli.error("Refuse to overwrite the frozen packet or receipt")
    if not args.local_packet.resolve().is_relative_to(HERE.parents[1] / "outputs"):
        cli.error("Raw question text must stay under local outputs")
    cases, report = compile_packet(args.question_only, args.authors, args.archive_gate)
    report["live_packet_sha256"] = write(args.local_packet, {"cases": cases})
    report["preparation_code_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    write(args.output, report)
    print(report["status"], len(cases), report["reviewed_active_scope"], report["live_packet_sha256"])


if __name__ == "__main__":
    main()
