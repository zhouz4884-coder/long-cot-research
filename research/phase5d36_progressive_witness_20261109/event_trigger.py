"""Bounded feedback cadence, separate from candidate admission and terminal veto."""

EVENT_ACTIONS = frozenset({"UPDATE_BOUND", "REPAIR_INFEASIBLE", "BLOCK_REGRESSION"})


class EventTrigger:
    def __init__(self, mode, budget):
        if mode not in {"event", "every_step"} or type(budget) is not int or budget < 0:
            raise ValueError("unsupported feedback mode or budget")
        self.mode = mode
        self.budget = budget
        self.emitted = 0
        self._seen = set()

    def permits(self, action, receipt, incumbent, *, terminal, enabled):
        if not enabled or self.emitted >= self.budget:
            return False
        if action in {"NATIVE_CONTINUE", "CERTIFY_EXACT"} or terminal and action == "UPDATE_BOUND":
            return False
        if terminal and action not in {"REPAIR_INFEASIBLE", "BLOCK_REGRESSION"}:
            return False
        if self.mode == "event" and action not in EVENT_ACTIONS:
            return False
        if self.mode == "event" and action == "BLOCK_REGRESSION" and not terminal:
            return False
        discriminator = receipt.candidate_id if self.mode == "every_step" else receipt.objective
        key = (action, discriminator, incumbent, terminal)
        if key in self._seen:
            return False
        self._seen.add(key)
        self.emitted += 1
        return True
