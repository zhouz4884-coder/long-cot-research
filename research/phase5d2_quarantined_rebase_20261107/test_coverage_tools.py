"""CPU controls for policy ties, past-only bindings and decoded observations."""

import base64
import copy
from pathlib import Path
import tempfile
import unittest

from audit_coverage import candidate_record, digest_ids, replay_observer, select_pairs
from fetch_coverage import local_destination
from observations import Observer


class Tokenizer:
    pieces = {1: "<think>", 2: "</think>", 3: "<|im_end|>",
              4: "So $1+1=2$", 5: "\n\n", 6: "Wait $2+2=4$", 7: "Final"}

    def decode(self, tokens, **kwargs):
        return "".join(self.pieces[token] for token in tokens)


class BytesState:
    def cpu(self):
        return self

    def tolist(self):
        return [1, 2, 3, 4]


class RNG:
    def get_state(self):
        return BytesState()


def option(case, priority=1, seed=1, step=1, equation=0):
    return {"case_id": case, "priority": priority, "seed": seed,
            "step": step, "equation_index": equation,
            "candidate_id": f"{case}-{priority}-{seed}-{step}-{equation}"}


class CoverageToolsTests(unittest.TestCase):
    def test_priority_precedes_case_identifier(self):
        chosen, _ = select_pairs([option("A", 2), option("Z", 0)], 1)
        self.assertEqual(chosen[0]["case_id"], "Z")

    def test_one_event_per_distinct_problem(self):
        choices = [option("A", 1), option("A", 0), option("B", 1), option("C", 2)]
        chosen, excluded = select_pairs(choices, 2)
        self.assertEqual([(r["case_id"], r["priority"]) for r in chosen], [("A", 0), ("B", 1)])
        self.assertEqual({r["reason"] for r in excluded}, {"same_problem_already_selected", "distinct_problem_limit"})

    def test_all_tie_fields_in_frozen_order(self):
        choices = [option("A", seed=2), option("A", seed=1, step=3),
                   option("A", seed=1, step=2, equation=2), option("A", seed=1, step=2, equation=1)]
        chosen, _ = select_pairs(choices, 4)
        self.assertEqual(chosen, [choices[-1]])

    def test_selection_does_not_mutate_candidates(self):
        choices = [option("B"), option("A")]
        prior = copy.deepcopy(choices)
        select_pairs(choices, 4)
        self.assertEqual(choices, prior)

    def test_record_hash_uses_only_observed_prefix(self):
        row = {"case_id": "A", "seed": 1, "prompt_ids": [9], "generated_ids": [1, 4, 5, 6],
               "source_result_sha256": "x", "source_decode_validation": "NOT_RUN"}
        event = {"step": 0, "end": 3}
        saved = copy.deepcopy(row)
        first = candidate_record(row, "native_results/worker_0/A/result.json", event, None, None, 2)
        row["generated_ids"][3:] = [7, 7, 3]
        second = candidate_record(row, "native_results/worker_0/A/result.json", event, None, None, 2)
        self.assertEqual(first["observed_prefix_sha256"], digest_ids([9, 1, 4, 5]))
        self.assertEqual(first, second)
        self.assertFalse(first["role_certified"])
        self.assertFalse(first["rebase_eligible"])
        self.assertEqual(saved["prompt_ids"], row["prompt_ids"])

    def test_decoded_online_boundaries_and_checkpoints(self):
        generated = [1, 4, 5, 6, 5, 2, 7, 3]
        engine = type("Engine", (), {"tokenizer": Tokenizer()})()
        original = Observer()
        original.open(1)
        original.complete(engine, [9], generated, 3, RNG(), open_thinking=True, boundary="paragraph")
        original.complete(engine, [9], generated, 5, RNG(), open_thinking=True, boundary="paragraph")
        original.complete(engine, [9], generated, 5, RNG(), open_thinking=False, boundary="think_close")
        row = {"prompt_ids": [9], "generated_ids": generated, "context_capacity": 50, "events": original.events}
        replayed = replay_observer(row, Tokenizer(), 1, 2, {3})
        self.assertEqual(replayed.steps, original.steps)
        self.assertEqual(replayed.events, original.events)
        self.assertEqual(replayed.checkpoints, original.checkpoints)
        self.assertEqual(replayed.checkpoints["relation"]["generated_count"], 3)
        self.assertEqual(replayed.checkpoints["reflection_cue"]["generated_count"], 5)

    def test_safe_destination_and_path_escape(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            self.assertEqual(local_destination(root, "native_results/worker_0/result.json"),
                             (root / "native_results/worker_0/result.json").resolve())
            for unsafe in ("../outside", "/outside", "x/../../outside", "x\\outside"):
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    local_destination(root, unsafe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
