"""Read-only event candidates from complete, observed thinking paragraphs."""

import base64
import hashlib
import re

CHALLENGE = re.compile(
    r"\b(wait|hold on|double[- ]check|check(?:ing)? (?:this|that|the|my)|rethink|"
    r"reconsider|actually|counterexample|mistake|incorrect|contradiction|wrong|"
    r"does not work|doesn't work|scratch that|instead)\b",
    re.IGNORECASE,
)
CANDIDATE = re.compile(r"\\boxed\s*\{|\b(?:final answer|answer is|solution is)\b", re.IGNORECASE)
MATH_MARK = re.compile(r"(?:=|\\equiv|\\mid|\\ne|\\neq|\\in|\\le|\\ge)")


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def state_bytes(state):
    return base64.b64encode(bytes(state.cpu().tolist())).decode("ascii")


class Observer:
    def __init__(self):
        self.step_start = None
        self.steps = []
        self.events = []
        self.checkpoints = {}
        self.repeats = {}

    def open(self, generated_count):
        self.step_start = generated_count

    def complete(self, engine, prompt, generated, end, rng, *, open_thinking, boundary):
        if self.step_start is None or end <= self.step_start:
            return
        start = self.step_start
        self.step_start = end
        text = engine.tokenizer.decode(generated[start:end], skip_special_tokens=False)
        key = text_hash(" ".join(text.split()).casefold())
        if not text.strip():
            return
        self.repeats[key] = self.repeats.get(key, 0) + 1
        step_id = len(self.steps)
        types = []
        if CANDIDATE.search(text):
            types.append("candidate")
        if CHALLENGE.search(text):
            types.append("reflection_cue")
        if MATH_MARK.search(text):
            types.append("relation")
        if self.repeats[key] == 3:
            types.append("repeated_paragraph")
        self.steps.append({"step": step_id, "start": start, "end": end, "text": text,
                           "boundary": boundary, "event_types": types})
        if not types:
            return
        event = {"step": step_id, "start": start, "end": end, "types": types,
                 "thinking_open": open_thinking}
        self.events.append(event)
        if open_thinking:
            state = state_bytes(rng.get_state())
            event["rng_state_base64"] = state
            # Freeze the first occurrence of each class at its observed boundary.
            # Checker inputs are reconstructed later from these past-only tokens.
            for kind in types:
                if kind not in self.checkpoints:
                    self.checkpoints[kind] = {"step": step_id, "generated_count": end,
                                              "prefix_tokens": len(prompt) + end,
                                              "rng_state_base64": state,
                                              "boundary": boundary}
