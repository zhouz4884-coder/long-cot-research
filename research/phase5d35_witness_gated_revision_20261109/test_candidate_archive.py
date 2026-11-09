"""Source provenance and actual historical trace regressions for the WGR archive."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from candidate_archive import CandidateArchive, ObservedPrefix, digest, observe
from goal_claim_detector import comparison_supports, detect_claims, target_id_for


TOKENIZER = "a" * 64
QUESTION = "b" * 64
PROMPT = list(map(ord, "Question\n<think>\n"))
ROOT = Path(__file__).resolve().parent
D3 = ROOT.parent / "phase5d25_constraint_revision_20261109"
TOK = ROOT.parents[1] / "outputs" / "d2_tokenizer_20261107" / "tokenizer.json"


def decode(ids):
    return "".join(map(chr, ids))


def contract(template="arithmetic_geometric_sequence_v1", goal="EXACT"):
    return SimpleNamespace(template_id=template, goal=goal, question_sha256=QUESTION, contract_id="wc_" + template)


def prefix(text, *, prompt=PROMPT, trajectory="trial"):
    return ObservedPrefix.from_tokens(list(map(ord, text)), decode, prompt_ids=prompt,
                                      tokenizer_sha256=TOKENIZER, trajectory_id=trajectory, question_sha256=QUESTION)


def archive_for(c):
    return CandidateArchive(c.contract_id, target_id_for(c), c.question_sha256)


def admit_all(c, p):
    archive = archive_for(c)
    rows = detect_claims(p, c)
    for row in rows:
        archive.admit(row, p)
    return archive, rows


class SourceBindingTest(unittest.TestCase):
    def test_prefix_hash_binds_prompt_and_generated_ids(self):
        p = prefix("abcdef")
        expected = sha256(json.dumps(PROMPT + list(map(ord, "abcdef")), separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(p.prefix_sha256, expected)
        self.assertNotEqual(prefix("abcdef", prompt=[65] + PROMPT).prefix_sha256, expected)
        self.assertEqual(p.span(1, 4).text, "bcd")
        self.assertEqual(p.span(1, 4).token_span, (1, 4))
        self.assertEqual(p.span(1, 4).token_sha256, digest(list(map(ord, "bcd"))))

    def test_frozen_cutoff_decodes_only_past_ids_and_rejects_forgery(self):
        tokens = list(map(ord, "Seen. Future."))
        raw_record = {"prompt_ids": PROMPT, "generated_ids": tokens,
                      "prompt_sha256": digest(PROMPT), "generated_sha256": digest(tokens),
                      "steps": [{"end": 5}], "case_id": "trial", "seed": 3, "question_hash": QUESTION, "status": "COMPLETE"}
        raw = json.dumps(raw_record).encode()
        calls = []
        def spy(ids):
            calls.append(decode(ids))
            return calls[-1]
        p = ObservedPrefix.from_frozen_record(raw, sha256(raw).hexdigest(), 5, spy, tokenizer_sha256=TOKENIZER)
        self.assertEqual(p.text, "Seen.")
        self.assertTrue(all("Future" not in text for text in calls))
        for trial, digest_expected, cutoff in ((raw+b" ", sha256(raw).hexdigest(), 5),
                                               (raw, sha256(raw).hexdigest(), 6),
                                               (raw, sha256(raw).hexdigest(), len(tokens)+1)):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                ObservedPrefix.from_frozen_record(trial, digest_expected, cutoff, decode, tokenizer_sha256=TOKENIZER)
        with self.assertRaises(ValueError):
            p.span(0, 6)
        with self.assertRaises(ValueError):
            p.at(6)

    def test_thinking_boundary_and_terminator_are_enforced(self):
        p = prefix("proof</think>answer")
        self.assertEqual(p.segment(0, 5), "thinking")
        self.assertEqual(p.segment(13, 19), "final")
        with self.assertRaises(ValueError):
            p.span(4, 14)
        for text in ("a</think><think>b", "a</think>b</think>c", "a</think>b<|im_end|>future"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                prefix(text)

    def test_exact_value_cannot_be_detached_from_observed_field(self):
        c = contract()
        p = prefix("Therefore, the answer is 7.")
        field = (p.text.index("7"), p.text.index("7")+1)
        for false in (8, True, {"op":"rat","num":7,"den":1}):
            with self.subTest(false=false), self.assertRaises(ValueError):
                observe(p, contract_id=c.contract_id, target_id=target_id_for(c), goal_claim_type="EXACT_ANSWER",
                        role="explicit_answer", source=(0,len(p.text)), fields={"value":field}, value=false)

    def test_archive_replays_earlier_candidate_under_later_same_prefix(self):
        c = contract()
        earlier = prefix("Therefore, the answer is 7.")
        later = prefix(earlier.text + "\nFurther verification.")
        archive, rows = admit_all(c, earlier)
        self.assertEqual(archive.validated(rows[0].candidate_id, later), rows[0])
        for altered in (prefix(earlier.text.replace("7", "8")), prefix(earlier.text, trajectory="other"),
                        prefix(earlier.text, prompt=[65]+PROMPT), prefix(earlier.text[:10])):
            with self.subTest(text=altered.text), self.assertRaises(ValueError):
                archive.validated(rows[0].candidate_id, altered)
        with self.assertRaises(ValueError):
            archive.admit(replace(rows[0], source_origin="OFFLINE_ORACLE"), earlier)
        with self.assertRaises(ValueError):
            archive.admit(replace(rows[0], observed_count=earlier.observed_count+1), earlier)


class RoleControls(unittest.TestCase):
    def test_no_mere_mention_malformed_alternatives_or_fenced_candidate(self):
        c = contract()
        for text in (
            "Gold answer: 999.",
            "The earlier guess 999 seems wrong.",
            "Maybe the answer is 999?",
            r"### Final Answer" + "\n" + r"\boxed{999",
            "### Final Answer\n" + r"\boxed{7}\quad\boxed{8}",
            "The answer is 7. Or maybe 8.",
            "```text\n### Final Answer\n" + r"\boxed{7}" + "\n```",
            "The answer is d=7.",
        ):
            with self.subTest(text=text):
                self.assertEqual(detect_claims(prefix(text),c), ())
        with self.assertRaises(ValueError):
            detect_claims(prefix("The answer is 7."), SimpleNamespace(**{**vars(c), "question_sha256":"c"*64}))

    def test_revision_distinguishes_equivalence_and_competing_finals(self):
        c = contract()
        equivalent = prefix(r"The answer is 1/2." + "\n</think>\n### Final Answer\n" + r"\boxed{0.5}")
        self.assertNotIn("FINAL_ANSWER_REVISION", {x.goal_claim_type for x in detect_claims(equivalent,c)})
        competing = prefix(r"The answer is 7." + "\n</think>\n### Final Answer\n" + r"\boxed{8}" +
                           "\n\n### Final Answer\n" + r"\boxed{9}")
        self.assertNotIn("FINAL_ANSWER_REVISION", {x.goal_claim_type for x in detect_claims(competing,c)})
        clean = prefix(r"The answer is 7." + "\n</think>\n### Final Answer\n" + r"\boxed{8}")
        archive, rows = admit_all(c, clean)
        revision = next(x for x in rows if x.goal_claim_type == "FINAL_ANSWER_REVISION")
        self.assertEqual(archive.validated(revision.lineage[0], clean).value, 7)
        self.assertEqual(revision.value, 8)
        self.assertEqual(revision.segment, "final")

    def test_witness_referent_and_global_scope_are_conservative(self):
        c = contract("fibbish_max_v1","MAX")
        t = "In the six-digit branch. Therefore, 303369 is the maximum."
        self.assertEqual(detect_claims(prefix(t),c), ())
        t = "Therefore, the seven-digit number is 1212356. But 1212357 is smaller than 333369."
        self.assertEqual(comparison_supports(prefix(t),c), ())
        t = "Therefore, the seven-digit number is 1212356.\n\nBut that's smaller than 333369."
        self.assertEqual(comparison_supports(prefix(t),c), ())
        t = "Therefore, the seven-digit number is 1212356. But that's smaller than 333369."
        checks = comparison_supports(prefix(t),c)
        self.assertEqual([(item.left,item.right,item.relation) for item in checks],[(1212356,333369,"<")])
        self.assertEqual(checks[0].left_span.text, "1212356")
        self.assertTrue(checks[0].source_span.text.endswith("333369."))
        t = "The largest valid fibbish number is 444."
        self.assertEqual(detect_claims(prefix(t),c)[0].claim, {"kind":"MAX","value":444})

    def test_universal_scope_hypotheses_do_not_become_assertions(self):
        c = contract("lcm_divisor_count_v1","COUNT")
        surface = "removing any two numbers from 16 to 30 will result in an LCM that is not divisible by those two numbers, and divisible by all others."
        self.assertEqual(detect_claims(prefix("If " + surface),c), ())
        result = detect_claims(prefix("So, " + surface),c)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].claim, {"kind":"ALL_REMOVED_PAIR_LCM_FAILS_BOTH","lower":16,"upper":30})
        c = contract("greedy_coin_count_v1","COUNT")
        ctext = "For N from 20 to 80: for each N, if N mod 10 is in {0,2}, then it's optimal. Otherwise, it's not."
        result = detect_claims(prefix(ctext),c)
        self.assertEqual(result[0].claim, {"kind":"GREEDY_RESIDUE_CLASS","lower":20,"upper":80,
                                          "modulus":10,"residues":[0,2],"relation":"IFF"})
        self.assertEqual(detect_claims(prefix(ctext.replace("Otherwise, it's not.","")),c), ())

    def test_complete_solutions_claim_is_not_a_proof(self):
        c = contract("generic_complete", "ALL_SOLUTIONS")
        p = prefix(r"The complete set of solutions is \{-2,3\}.")
        _, rows = admit_all(c,p)
        self.assertEqual(rows[0].claim, {"kind":"COMPLETE_SOLUTIONS","values":[-2,3]})
        self.assertNotIn("certificate", rows[0].as_dict())


@unittest.skipUnless(TOK.is_file() and (D3 / "bank" / "native_results").is_dir(), "requires local frozen raw and tokenizer")
class FrozenRealTraces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tokenizers import Tokenizer
        cls.tokenizer = Tokenizer.from_file(str(TOK))
        cls.tokenizer_hash = sha256(TOK.read_bytes()).hexdigest()
        manifest = json.loads(TOK.with_name("TOKENIZER_FETCH_MANIFEST.json").read_bytes())
        expected = next(row["sha256"] for row in manifest["files"] if row["path"] == "tokenizer.json")
        if cls.tokenizer_hash != expected:
            raise ValueError("tokenizer cache differs from frozen bytes")

    @classmethod
    def fixture(cls, bank, case, seed, *steps):
        from witness_contract import compile_contract
        records = json.loads((D3 / bank / "GRADE_FREEZE.json").read_bytes())["records"]
        entry = next(item for item in records if (item["case_id"],item["seed"]) == (case,seed))
        raw = (D3 / entry["path"]).read_bytes()
        assert sha256(raw).hexdigest() == entry["sha256"]
        result = json.loads(raw)
        question = next(row["question"] for row in map(json.loads,(D3/"prepared_data"/bank/"visible.jsonl").read_bytes().splitlines())
                        if row["case_id"]==case)
        c = compile_contract(question)
        def frozen_decode(ids):
            return cls.tokenizer.decode(ids,skip_special_tokens=False)
        prefixes = []
        for step in steps:
            count = len(result["generated_ids"]) if step is None else result["steps"][step]["end"]
            p = ObservedPrefix.from_frozen_record(raw,entry["sha256"],count,frozen_decode,tokenizer_sha256=cls.tokenizer_hash)
            assert result["text"].startswith(p.text)
            prefixes.append(p)
        return (c,*prefixes)

    def test_real_e12_exact_to_final_revision(self):
        c, before, full = self.fixture("bank","D3_E12",20261110,153,None)
        a, early = admit_all(c,before)
        checkpoint = [row for row in early if row.goal_claim_type=="EXACT_ANSWER"][-1]
        self.assertEqual((checkpoint.value, checkpoint.segment, checkpoint.source_span.text),(61,"thinking",r"\boxed{61}"))
        self.assertEqual(checkpoint.assignments,{"a1":{"op":"rat","num":1,"den":2},
                                                "b1":{"op":"rat","num":1,"den":2},"d":5,"r":-3})
        self.assertEqual(a.validated(checkpoint.candidate_id,full).candidate_id,checkpoint.candidate_id)
        b, late = admit_all(c,full)
        revision = next(x for x in late if x.goal_claim_type=="FINAL_ANSWER_REVISION")
        self.assertEqual((revision.value,revision.segment),(45,"final"))
        self.assertEqual(b.validated(revision.lineage[0],full).candidate_id,checkpoint.candidate_id)

    def test_real_e15_witness_first_appears_at_step_316_and_scope_gate(self):
        c, narrow, before, observed, current, full = self.fixture("bank","D3_E15",20261110,241,315,316,463,None)
        self.assertNotIn("MAXIMALITY_CLAIM",{item.goal_claim_type for item in detect_claims(narrow,c)})
        self.assertFalse(any(row.value==1011235 for row in detect_claims(before,c)))
        _, rows = admit_all(c,observed)
        witness = next(item for item in rows if item.value==1011235)
        self.assertEqual(witness.observed_count,19902)
        supports = [item for item in comparison_supports(observed,c) if item.left==1011235 and item.right==303369]
        self.assertEqual(len(supports),1)
        self.assertEqual(supports[0].paragraph_span.token_span,(19747,19902))
        self.assertIn("But that's smaller than 303369.",supports[0].source_span.text)
        _, rows = admit_all(c,current)
        self.assertEqual((rows[-1].role,rows[-1].claim),
                         ("provisional_cross_length_maximum",{"kind":"MAX","value":303369}))
        self.assertIn("cross_length_comparison",rows[-1].field_spans)
        _, rows = admit_all(c,full)
        self.assertEqual((rows[-1].segment,rows[-1].claim),("final",{"kind":"MAX","value":303369}))

    def test_real_p02_minimality_and_complete_set(self):
        c, p = self.fixture("precheck","D3_P02",20261109,137)
        _, rows = admit_all(c,p)
        self.assertEqual(rows[-1].claim,{"kind":"MIN","value":134,"p":17})
        self.assertEqual(rows[0].claim,{"kind":"COMPLETE_SOLUTIONS","values":[155,134],"modulus":289})
        self.assertEqual(rows[0].field_spans["modulus"].text,"17²")
        self.assertFalse(any(row.value==110 for row in rows))

    def test_real_e14_e06_point_witnesses_and_predicates(self):
        for bank,case,seed,step,expected_point,expected_claim in (
            ("bank","D3_E14",20261110,475,{"pair":[16,18]},
             {"kind":"ALL_REMOVED_PAIR_LCM_FAILS_BOTH","lower":16,"upper":30}),
            ("bank","D3_E06",20261109,329,{"n":45},
             {"kind":"GREEDY_RESIDUE_CLASS","lower":25,"upper":1000,"modulus":25,
              "residues":[0,1,2,3,4,10,11,12,13,14],"relation":"IFF"}),
        ):
            with self.subTest(case=case):
                c,p=self.fixture(bank,case,seed,step)
                _, rows=admit_all(c,p)
                self.assertTrue(any(row.value==expected_point and row.segment=="thinking" for row in rows))
                self.assertTrue(any(row.claim==expected_claim and row.segment=="thinking" for row in rows))


if __name__ == "__main__":
    unittest.main()
