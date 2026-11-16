"""Coach: turns the statistics of one practice segment into a short feedback line and, at most,
one parameter command for the device. Used by bridge/bridge.py.

Two back ends, neither needs an API key:
  mock    a fixed rule on the segment statistics (deterministic; for tests and as the fallback
          when Ollama is not installed). --mock-replies FILE replays raw replies instead.
  ollama  a local model through the Ollama HTTP API (default http://localhost:11434, model
          llama3.2:3b), with the reply constrained to REPLY_SCHEMA by Ollama's "format" field.

The reply is never trusted: protocol.check_llm_reply() validates it and clamps the parameter to
the allowed range before anything is sent to the board.
"""
import json
import time
import urllib.request

from protocol import FEEDBACK_MAX_WORDS, HARD_SCALE_MAX, HARD_SCALE_MIN

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"
TIMEOUT_S = 10.0

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "feedback": {"type": "string"},
        "command": {"anyOf": [
            {"type": "object", "properties": {"hard_scale": {"type": "number"}}, "required": ["hard_scale"]},
            {"type": "null"},
        ]},
    },
    "required": ["feedback", "command"],
}


def build_prompt(summary, hard_scale):
    share = summary["level_share"]
    norm = summary["norm"]
    return (
        "You are a guitar practice coach. A forearm EMG sensor measured the fretting hand's tension during one "
        "practice segment. Levels: relax, medium, hard (hard = squeezing more than needed).\n\n"
        f"Segment data:\n"
        f"- duration: {summary['duration_s']:.1f} s\n"
        f"- time share: relax {100 * share['relax']:.0f}%, medium {100 * share['medium']:.0f}%, "
        f"hard {100 * share['hard']:.0f}%\n"
        f"- entries into hard: {summary['hard_entries']}; longest continuous hard: {summary['longest_hard_s']:.1f} s\n"
        f"- tension as a multiple of the relax baseline: mean {norm['mean']}, 90th percentile {norm['p90']}, "
        f"max {norm['max']}\n"
        f"- current hard_scale: {hard_scale:.2f}\n\n"
        "Reply with JSON only: {\"feedback\": string, \"command\": {\"hard_scale\": number} or null}.\n"
        f"- feedback: one sentence for the player, at most {FEEDBACK_MAX_WORDS} words, based only on the numbers "
        "above. No medical claims.\n"
        "- command: hard_scale multiplies the threshold of the hard level (1.0 = default). Lower it (stricter) "
        "when the player was mostly relaxed, raise it (more lenient) when hard dominated the whole segment, "
        f"otherwise null. Allowed range {HARD_SCALE_MIN:.2f} to {HARD_SCALE_MAX:.2f}; change it by at most 0.10 "
        "at a time."
    )


def mock_reply(summary, hard_scale):
    """Fixed rule, written as the same JSON text a model would return."""
    share = summary["level_share"]
    hard, relax = share["hard"], share["relax"]
    if hard >= 0.60:
        new = round(min(HARD_SCALE_MAX, hard_scale + 0.10), 2)
        text = f"Hard for {100 * hard:.0f}% of the segment. Ease the grip; raising the hard threshold slightly."
        command = {"hard_scale": new} if new != round(hard_scale, 2) else None
    elif hard < 0.05 and relax >= 0.50:
        new = round(max(HARD_SCALE_MIN, hard_scale - 0.10), 2)
        text = f"Relaxed {100 * relax:.0f}% of the time, hard only {100 * hard:.0f}%. Tightening the hard threshold."
        command = {"hard_scale": new} if new != round(hard_scale, 2) else None
    else:
        text = (f"Hard {100 * hard:.0f}% of the time, longest {summary['longest_hard_s']:.1f} s. "
                "Release the grip between changes.")
        command = None
    return json.dumps({"feedback": text, "command": command})


class Coach:
    def __init__(self, kind="mock", model=DEFAULT_MODEL, url=OLLAMA_URL, timeout=TIMEOUT_S, mock_delay=0.8,
                 mock_replies=None):
        if kind not in ("mock", "ollama"):
            raise ValueError(f"unknown LLM back end {kind!r}")
        self.kind, self.model, self.url, self.timeout = kind, model, url.rstrip("/"), timeout
        self.mock_delay = mock_delay
        self.mock_replies = list(mock_replies or [])     # raw reply texts, used in order, then the rule
        self.calls = 0

    def describe(self):
        return {"llm": self.kind, "model": self.model if self.kind == "ollama" else "rule"}

    def request(self, prompt):
        """The exact request for the session log (ollama) or a description (mock)."""
        if self.kind == "ollama":
            return {"url": f"{self.url}/api/generate", "model": self.model, "prompt": prompt, "stream": False,
                    "format": REPLY_SCHEMA, "options": {"temperature": 0.2, "num_predict": 120}}
        return {"mock": "replies file" if self.calls < len(self.mock_replies) else "rule", "prompt": prompt}

    def call(self, prompt, summary, hard_scale):
        """Blocking; returns the raw reply text. Raises on connection errors and timeouts."""
        index, self.calls = self.calls, self.calls + 1
        if self.kind == "mock":
            time.sleep(self.mock_delay)
            if index < len(self.mock_replies):
                return self.mock_replies[index]
            return mock_reply(summary, hard_scale)
        body = self.request(prompt)
        url = body.pop("url")
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as res:
            return json.loads(res.read())["response"]
