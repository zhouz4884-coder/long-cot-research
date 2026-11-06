"""Minimal native-prefix preparation; no model is loaded by this module.

The generated suffix must have been captured from a Qwen3 thinking-mode assistant
turn, BEFORE its closing </think>. Strict equality is checked using token IDs.
This does not recover the original KV: generate() will prefill exact token IDs.
"""
from __future__ import annotations


def make_thinking_prompt_ids(tokenizer, question: str) -> list[int]:
    out = tokenizer.apply_chat_template(
        [{"role": "user", "content": question}],
        tokenize=True, add_generation_prompt=True, enable_thinking=True)
    if not isinstance(out,list) or not all(isinstance(t,int) for t in out):
        raise ValueError("Token-level chat template mismatch")
    return out


def append_in_thought_bridge(tokenizer, checkpoint_ids: list[int], bridge: str,
                             ) -> list[int]:
    """Append bridge as new causal tokens, not a new role/message turn.

    Only call at a known complete step boundary. The lexical naturalness and
    effectiveness of a bridge are hypotheses to be tested, not guarantees.
    """
    ids=list(checkpoint_ids)
    added=tokenizer.encode(bridge,add_special_tokens=False)
    forbidden=("<|im_start|>", "<|im_end|>", "<|endoftext|>")
    if any(tag in bridge for tag in forbidden):
        raise ValueError("Bridge must not inject chat role delimiters")
    if not all(isinstance(x,int) for x in added):raise ValueError("Invalid bridge token IDs")
    return ids+added


def model_continue_reference(model, tokenizer, prefix_ids: list[int],
                             max_new_tokens: int, seed: int):
    """Simple reference; a fast KV-clone path must match its token/logit behavior.

    The caller must validate original prefix structure, available context and
    memory before invoking; use batch=1 and a declared complete reasoning event.
    """
    import torch
    from transformers import GenerationConfig
    dev=next(model.parameters()).device
    torch.manual_seed(seed)
    x=torch.tensor([prefix_ids],device=dev,dtype=torch.long)
    gen=GenerationConfig(
        do_sample=True, temperature=0.6, top_p=0.95, top_k=20,
        max_new_tokens=max_new_tokens,
        eos_token_id=model.generation_config.eos_token_id,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    with torch.inference_mode():
        output=model.generate(input_ids=x,generation_config=gen,use_cache=True)
    return output[0,len(prefix_ids):].detach().cpu().tolist()
