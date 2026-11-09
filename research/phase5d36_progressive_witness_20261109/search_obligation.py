"""Construct compact, scope-preserving feedback from deterministic verdicts."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SearchObligation:
    action: str
    target_id: str
    source_receipt_sha256: str
    incumbent_receipt_sha256: str | None
    candidate: int
    incumbent: int | None
    message: str

    def as_dict(self):
        return asdict(self)


def make_obligation(state, action, receipt):
    candidate = receipt.objective
    incumbent = state.incumbent.objective if state.incumbent else None
    comparison = "greater" if state.direction == "MAX" else "smaller"
    bound_kind = "lower" if state.direction == "MAX" else "upper"
    if incumbent is None:
        remaining = "Continue by constructing a feasible candidate under the original constraints."
    else:
        remaining = (f"The feasible {bound_kind} bound is {incumbent}. Find a strictly {comparison} feasible "
                     "candidate or prove optimality.")
    if action == "REPAIR_INFEASIBLE":
        math = receipt.math
        evidence = math.get("evidence") or {}
        where = evidence.get("violated_index")
        if where is None:
            violation = "violates the original feasibility constraints"
        else:
            digits = evidence["digits"]
            a, b, value = digits[where - 2:where + 1]
            violation = f"violates the digit rule at position {where + 1} because {value} < {a} + {b}"
        lead = f"Candidate {candidate} {violation}. Do not submit it."
    elif action == "BLOCK_REGRESSION":
        lead = f"Candidate {candidate} is dominated by the certified feasible candidate {incumbent}."
    elif action == "UPDATE_BOUND":
        lead = f"Candidate {candidate} satisfies the original constraints."
    elif action == "KEEP_BOUND":
        lead = "The checked candidate leaves the certified bound unchanged."
    else:
        raise ValueError("action has no search obligation")
    return SearchObligation(action, state.target_id, receipt.receipt_sha256,
                            state.incumbent.receipt_sha256 if state.incumbent else None,
                            candidate, incumbent, f"{lead} {remaining}")
