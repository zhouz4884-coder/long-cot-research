"""Small synthetic generation banks for the pure, pre-Gold validation helpers.

The temporary fixture has no evaluation-answer file. The tests do not call the
scoring main entry point or a mathematical grader.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import freeze_generation
import score_d2


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SyntheticBank:
    def __init__(self, root):
        self.root = root
        self.seeds = [101, 102]
        self.cases = [{"case_id": f"D2_{index:03}", "problem_id": f"synthetic-{index}",
                       "question": f"Synthetic gate fixture {index}"} for index in range(1, 25)]
        root.mkdir(parents=True)
        (root / "d2_visible.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.cases), encoding="utf-8")
        put(root / "COVERAGE_PROTOCOL.json", {"questions": 24, "seeds": self.seeds})
        put(root / "PAIRING_PROTOCOL.json", {"status": "FROZEN", "fixture": True})
        self.policy_sha256 = sha(root / "PAIRING_PROTOCOL.json")
        put(root / "DATA_MANIFEST.json", {"eval_sha256": "f" * 64, "visible_sha256": sha(root / "d2_visible.jsonl")})
        self.trajectories = []
        for index, case in enumerate(self.cases):
            for seed in self.seeds:
                path = root / "native_results" / f"worker_{index % 2}" / f"{case['case_id']}_{seed}" / "result.json"
                put(path, self.result(case["case_id"], seed))
                self.trajectories.append({"task_key": [case["case_id"], seed], "case_id": case["case_id"], "seed": seed,
                    "source_result": path.relative_to(root).as_posix(), "source_result_sha256": sha(path)})
        put(root / "COVERAGE_AUDIT.json", {"status": "COMPLETE", "integrity_status": "PASS", "trajectories": self.trajectories,
            "policy_sha256": self.policy_sha256,
            "missing_task_keys": [], "counts": {"planned_problems": 24, "planned_seeded_trajectories": 48,
                                                "completed_trajectories": 48}})
        put(root / "PAIR_SELECTION.json", {"status": "FROZEN", "selected": [], "policy_sha256": self.policy_sha256})
        self.refresh_role_binding([])

    @staticmethod
    def result(case_id, seed, arm=None):
        row = {"status": "COMPLETE", "case_id": case_id, "seed": seed, "EOS": True,
               "think_closed": True, "stop_reason": "EOS", "final_response": r"\boxed{1}",
               "new_tokens": 3, "prompt_ids": [1, 8, 9], "generated_ids": [3, 4, 2]}
        if arm is not None:
            row["arm"] = arm
        return row

    def native(self, index=0):
        return self.root / self.trajectories[index]["source_result"]

    def refresh_role_binding(self, selected):
        reviews = [{"case_id": row["case_id"], "seed": row["seed"], "event_step": row["step"]} for row in selected]
        put(self.root / "ROLE_REVIEWS.json", {"status": "FROZEN", "selection_sha256": sha(self.root / "PAIR_SELECTION.json"), "reviews": reviews})

    def one_pair(self):
        trajectory = self.trajectories[0]
        selected = {"case_id": trajectory["case_id"], "seed": trajectory["seed"], "step": 1,
                    "source_result": trajectory["source_result"], "source_result_sha256": trajectory["source_result_sha256"]}
        put(self.root / "PAIR_SELECTION.json", {"status": "FROZEN", "selected": [selected], "policy_sha256": self.policy_sha256})
        self.refresh_role_binding([selected])
        folder = self.root / "paired_results" / "worker_0" / f"{selected['case_id']}_{selected['seed']}"
        for arm in ("NativeContinue", "UnknownIdentity", "InContextCheck", "UnscopedIsolatedCheck", "ScopedIsolatedCheck"):
            put(folder / (arm + ".json"), self.result(selected["case_id"], selected["seed"], arm))
        put(folder / "summary.json", {"case_id": selected["case_id"], "seed": selected["seed"], "arms": []})
        put(folder / "repair" / "REPAIR_STATUS.json", {"status": "NOT_ELIGIBLE", "case_id": selected["case_id"], "seed": selected["seed"], "arms": []})
        return selected, folder

    def freeze(self):
        manifest, loaded = freeze_generation.collect_generation(self.root)
        put(self.root / "GENERATION_FREEZE.json", manifest)
        return manifest, loaded


@contextmanager
def forbid_answers():
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def bytes_guard(path, *args, **kwargs):
        if path.name == "d2_eval_only.jsonl":
            raise AssertionError("A pre-Gold helper accessed evaluation answers")
        return read_bytes(path, *args, **kwargs)

    def text_guard(path, *args, **kwargs):
        if path.name == "d2_eval_only.jsonl":
            raise AssertionError("A pre-Gold helper accessed evaluation answers")
        return read_text(path, *args, **kwargs)

    with patch.object(Path, "read_bytes", bytes_guard), patch.object(Path, "read_text", text_guard):
        yield


class GenerationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bank = SyntheticBank(Path(self.temp.name) / "owned-bank")

    def test_complete_bank_collects_and_prevalidates_without_answer_file(self):
        with forbid_answers():
            manifest, loaded = self.bank.freeze()
            checked, cached = score_d2.pre_gold_validate(self.bank.root)
        self.assertEqual(manifest["native_trajectories"], 48)
        self.assertEqual(len(loaded), 48)
        self.assertEqual(checked["records"], manifest["records"])
        self.assertEqual(cached, loaded)
        self.assertFalse((self.bank.root / "d2_eval_only.jsonl").exists())

    def test_duplicate_visible_id_and_seed_are_rejected(self):
        cases = self.bank.cases[:-1] + [self.bank.cases[0]]
        (self.bank.root / "d2_visible.jsonl").write_text("".join(json.dumps(row) + "\n" for row in cases), encoding="utf-8")
        with forbid_answers(), self.assertRaises(ValueError):
            freeze_generation.collect_generation(self.bank.root)
        (self.bank.root / "d2_visible.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.bank.cases), encoding="utf-8")
        put(self.bank.root / "COVERAGE_PROTOCOL.json", {"questions": 24, "seeds": [101, 101]})
        with forbid_answers(), self.assertRaises(ValueError):
            freeze_generation.collect_generation(self.bank.root)

    def test_missing_or_duplicate_native_is_rejected(self):
        path = self.bank.native()
        duplicate = self.bank.root / "native_results" / "worker_duplicate" / path.parent.name / "result.json"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes(path.read_bytes())
        with forbid_answers(), self.assertRaises(ValueError):
            freeze_generation.collect_generation(self.bank.root)

    def test_missing_native_identity_and_delivery_fields_are_rejected(self):
        path = self.bank.native()
        original = json.loads(path.read_text())
        for field in ("case_id", "seed", "final_response", "EOS", "think_closed", "new_tokens"):
            changed = {key: value for key, value in original.items() if key != field}
            put(path, changed)
            with self.subTest(field=field), forbid_answers(), self.assertRaises((ValueError, KeyError)):
                freeze_generation.collect_generation(self.bank.root)
        put(path, original)

    def test_duplicate_and_outside_selected_members_are_rejected(self):
        selected, _ = self.bank.one_pair()
        for rows in ([selected, selected], [{**selected, "case_id": "D2_unknown"}]):
            put(self.bank.root / "PAIR_SELECTION.json", {"status": "FROZEN", "selected": rows, "policy_sha256": self.bank.policy_sha256})
            self.bank.refresh_role_binding(rows)
            with forbid_answers(), self.assertRaises(ValueError):
                freeze_generation.collect_generation(self.bank.root)

    def test_wrong_paired_arm_and_identity_are_rejected(self):
        selected, folder = self.bank.one_pair()
        path = folder / "ScopedIsolatedCheck.json"
        for changed in (self.bank.result(selected["case_id"], selected["seed"], "UnknownIdentity"),
                        self.bank.result("D2_other", selected["seed"], "ScopedIsolatedCheck")):
            put(path, changed)
            with forbid_answers(), self.assertRaises(ValueError):
                freeze_generation.collect_generation(self.bank.root)

    def test_safe_path_rejects_traversal_absolute_and_noncanonical_paths(self):
        for path in ("../outside.json", "/outside.json", "x/../../outside.json", "./COVERAGE_AUDIT.json",
                     "x//file.json", "x\\file.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                freeze_generation.safe_path(self.bank.root, path)

    def test_repair_path_cannot_escape_the_owned_bank(self):
        selected, folder = self.bank.one_pair()
        outside = Path(self.temp.name) / "outside.json"
        put(outside, self.bank.result(selected["case_id"], selected["seed"], "GenericRewind"))
        arms = []
        for arm in ("GenericRewind", "RebaseNoCarry", "RebaseCarry", "FullRestart", "SameEvidenceCompactBridge", "Resampling"):
            path = folder / "repair" / (arm + ".json")
            put(path, self.bank.result(selected["case_id"], selected["seed"], arm))
            arms.append({"arm": arm, "path": "repair/" + arm + ".json"})
        arms[0]["path"] = "../../../../outside.json"
        put(folder / "repair" / "REPAIR_STATUS.json", {"status": "COMPLETE", "case_id": selected["case_id"], "seed": selected["seed"], "arms": arms})
        with forbid_answers(), self.assertRaises(ValueError):
            freeze_generation.collect_generation(self.bank.root)

    def test_frozen_empty_duplicate_and_wrong_identity_banks_fail_pre_gold(self):
        original, _ = self.bank.freeze()
        mutations = [[], original["records"] + [original["records"][0]],
                     [{**original["records"][0], "case_id": "wrong"}, *original["records"][1:]]]
        for rows in mutations:
            put(self.bank.root / "GENERATION_FREEZE.json", {**original, "records": rows})
            with self.subTest(size=len(rows)), forbid_answers(), self.assertRaises(ValueError):
                score_d2.pre_gold_validate(self.bank.root)

    def test_frozen_coverage_role_protocol_and_raw_mutation_fail_pre_gold(self):
        original, _ = self.bank.freeze()
        for relative in ("COVERAGE_AUDIT.json", "ROLE_REVIEWS.json", "PAIRING_PROTOCOL.json", self.bank.trajectories[0]["source_result"]):
            path = self.bank.root / relative
            before = path.read_bytes()
            changed = json.loads(before)
            changed["synthetic_mutation"] = True
            put(path, changed)
            with self.subTest(relative=relative), forbid_answers(), self.assertRaises(ValueError):
                score_d2.pre_gold_validate(self.bank.root)
            path.write_bytes(before)
        put(self.bank.root / "GENERATION_FREEZE.json", original)


if __name__ == "__main__":
    unittest.main()
