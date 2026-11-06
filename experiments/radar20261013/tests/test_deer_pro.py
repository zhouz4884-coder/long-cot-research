import math
import unittest
from deer_pro import calibrated_confidence, pro_prompts, PAPER_PRO_CUES, QWEN_SOURCE_CUE


class ProControls(unittest.TestCase):
    def test_paper_score_not_a_probability_and_no_clipping(self):
        self.assertEqual(calibrated_confidence([1.,0.,0.,0.])['score'], -.125)
        self.assertAlmostEqual(calibrated_confidence([.9,.9,.9,.6])['score'], .7125)
        self.assertAlmostEqual(calibrated_confidence([.96]*4)['score'], .96)
        self.assertFalse(calibrated_confidence([.96]*4)['score_is_calibrated_correctness_probability'])

    def test_invalid_or_missing_trial_cannot_be_silently_omitted(self):
        for scores in [[.9]*3, [.9]*5, [.9,.9,.9,math.nan], [.9,.9,.9,1.1]]:
            with self.assertRaises(AssertionError): calibrated_confidence(scores)

    def test_only_source_cue_removed_and_all_paper_cues_preserved(self):
        prefix='thought contains \\boxed earlier'
        self.assertEqual(pro_prompts(prefix+QWEN_SOURCE_CUE),[prefix+x for x in PAPER_PRO_CUES])
        with self.assertRaises(AssertionError):pro_prompts(prefix+'unrecognized cue')


if __name__=='__main__':unittest.main()
