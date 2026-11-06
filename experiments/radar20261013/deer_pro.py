"""Paper-based PRo extension; not the unpublished parallel-mask accelerator.

Prompts transcribed from the official ICLR PDF page 23; Eq.5 on page 5.
The pinned Qwen implementation uses a different first cue. That difference is
explicit: this extension uses all four paper cues and keeps Qwen score indices.
"""
import math

QWEN_SOURCE_CUE = '\n**Final Answer**\n\\boxed'
PAPER_PRO_CUES = (
    '\n\n Final Answer\n\\boxed',
    '\n\n Final Answer\n\n Based on the analysis above, the answer is \\boxed',
    '\n\n Final Answer\n\n The correct final answer is \\boxed',
    '\n\n Based on the previous thinking, I believe I already know the answer.\n Final Answer\n\\boxed',
)


def pro_prompts(source_prompt):
    assert source_prompt.endswith(QWEN_SOURCE_CUE), 'Unrecognized source trial cue; do not guess prefix'
    prefix = source_prompt[:-len(QWEN_SOURCE_CUE)]
    return [prefix + cue for cue in PAPER_PRO_CUES]


def calibrated_confidence(scores, alpha=1.):
    assert len(scores) == 4, 'Paper main setting requires four actual trials'
    assert math.isfinite(alpha) and alpha >= 0
    assert all(isinstance(x, (int, float)) and math.isfinite(x) and 0 <= x <= 1 for x in scores)
    mean = math.fsum(scores) / len(scores)
    mad = math.fsum(abs(x - mean) for x in scores) / len(scores)
    # Eq.5 can be negative. Do not silently clip it into a probability.
    return {'score': mean - alpha * mad, 'mean': mean, 'mad': mad,
            'alpha': alpha, 'N': len(scores), 'score_is_calibrated_correctness_probability': False}
