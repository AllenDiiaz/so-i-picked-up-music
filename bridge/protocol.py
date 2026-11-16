"""Protocol v1 (docs/protocol.md): message construction, validation and sequence tracking.

Shared by tools/replay_stream.py, tools/fake_device.py, bridge/bridge.py and the tests.
"""
import json
import math
import re

VERSION = 1
UDP_PORT = 9750
WS_PORT = 8765
_MAC = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
CAL_RESULTS = {1: "accepted", 2: "saturated", 3: "too_high", 4: "unstable"}   # emg_cal_result_t values

_DEVICE_FIELDS = {
    "type": str, "v": int, "dev": str, "boot": int, "seq": int, "sample_index": int, "device_ms": int,
    "rms_mV": (int, float), "norm": (int, float), "level": int, "saturated": bool, "calibrating": bool,
    "baseline_mV": (int, float), "led_state": int,
}
_CAL_FIELDS = {"attempt": int, "result": str, "valid": (int, float), "cv": (int, float), "rms_mV": (int, float)}
# Coach loop (firmware 11_coach_loop, docs/protocol.md "Downlink commands").
HARD_SCALE_MIN, HARD_SCALE_MAX, HARD_SCALE_DEFAULT = 0.80, 1.50, 1.00     # COACH_HARD_SCALE_* in coach.h
MODES = ("designed", "naive")
COMMANDS = ("set_params", "segment", "mode")
SEGMENT_STATES = ("idle", "recording", "thinking", "feedback")
_ACK_FIELDS = {"type": str, "v": int, "dev": str, "boot": int, "seq": int, "cmd": str, "applied": dict,
               "clamped": bool, "sample_index": int, "device_ms": int}
_CORES_FIELDS = {"type": str, "v": int, "dev": str, "boot": int, "device_ms": int, "mode": str,
                 "simulated": bool, "hard_scale": (int, float), "core1": dict, "core0": dict}
_CORE1_FIELDS = {"frames": int, "max_dev_us": int, "late": int, "blocked_ms": int, "ovf": int, "drop": int}
_CORE0_FIELDS = {"cmd_rx": int, "parse_fail": int, "applied": int, "sent": int}
_BUTTON_FIELDS = {"type": str, "v": int, "dev": str, "boot": int, "event": str, "device_ms": int}
_SEGMENT_FIELDS = {"type": str, "v": int, "id": int, "state": str, "trigger": str, "bridge_ms": (int, float)}
_COACH_FIELDS = {"type": str, "v": int, "id": int, "feedback": str, "llm": str, "fallback": bool,
                 "latency_ms": (int, float), "bridge_ms": (int, float)}
_COMMAND_FIELDS = {"type": str, "v": int, "seq": int, "cmd": str, "sent": bool, "bridge_ms": (int, float)}
_SYNC_FIELDS = {"type": str, "v": int, "id": int, "bridge_ms": (int, float)}

_STATUS_FIELDS = {
    "type": str, "v": int, "bridge_ms": (int, float), "received": int, "lost": int, "out_of_order": int,
    "reboots": int, "sources": list,
}


def _is(value, kind):
    """Type check that keeps bool apart from int (bool is a subclass of int in Python)."""
    if kind is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    return isinstance(value, kind)


def _check_types(msg, fields, what):
    for key, kind in fields.items():
        if key not in msg:
            raise ValueError(f"{what}: missing field {key!r}")
        if not _is(msg[key], kind):
            raise ValueError(f"{what}: {key!r} has the wrong type: {msg[key]!r}")


def validate_device_message(msg):
    """Raise ValueError unless msg is a valid v1 device message."""
    _check_types(msg, _DEVICE_FIELDS, "device message")
    if msg["type"] != "emg" or msg["v"] != VERSION:
        raise ValueError(f"device message: type/v must be 'emg'/{VERSION}")
    if msg["level"] not in (-1, 0, 1, 2):
        raise ValueError(f"device message: bad level {msg['level']}")
    if msg["led_state"] not in (0, 1):
        raise ValueError(f"device message: bad led_state {msg['led_state']}")
    for key in ("boot", "seq", "sample_index", "device_ms"):
        if not 0 <= msg[key] < 2 ** 32:
            raise ValueError(f"device message: {key} out of uint32 range")
    if msg["rms_mV"] < 0 or msg["norm"] < 0 or msg["baseline_mV"] < 0:
        raise ValueError("device message: negative rms/norm/baseline")
    if (msg["calibrating"] or msg["baseline_mV"] == 0) and msg["level"] != -1:
        raise ValueError("device message: level must be -1 while calibrating or without a baseline")
    if "cal" in msg:
        _check_types(msg["cal"], _CAL_FIELDS, "cal object")
        if msg["cal"]["result"] not in CAL_RESULTS.values():
            raise ValueError(f"cal object: bad result {msg['cal']['result']!r}")
    if _MAC.search(msg["dev"]):
        raise ValueError("device message: dev must not contain a MAC address")


def validate_ack(msg):
    """Raise ValueError unless msg is a valid ack of a downlink command (11_coach_loop)."""
    _check_types(msg, _ACK_FIELDS, "ack")
    if msg["type"] != "ack" or msg["v"] != VERSION or msg["cmd"] not in COMMANDS:
        raise ValueError("ack: bad type/v/cmd")
    applied = msg["applied"]
    if msg["cmd"] == "set_params":
        if set(applied) - {"hard_scale"}:
            raise ValueError(f"ack: unexpected applied keys {sorted(applied)}")
        if "hard_scale" in applied and not (_is(applied["hard_scale"], (int, float))
                                            and HARD_SCALE_MIN - 1e-6 <= applied["hard_scale"] <= HARD_SCALE_MAX + 1e-6):
            raise ValueError(f"ack: hard_scale outside the allowed range: {applied.get('hard_scale')!r}")
    elif msg["cmd"] == "segment" and applied.get("state") not in ("start", "end"):
        raise ValueError("ack: segment needs applied.state start/end")
    elif msg["cmd"] == "mode" and applied.get("mode") not in MODES:
        raise ValueError("ack: mode needs applied.mode")


def validate_cores(msg):
    """Raise ValueError unless msg is a valid per-second core statistics message (11_coach_loop)."""
    _check_types(msg, _CORES_FIELDS, "cores")
    if msg["type"] != "cores" or msg["v"] != VERSION or msg["mode"] not in MODES:
        raise ValueError("cores: bad type/v/mode")
    _check_types(msg["core1"], _CORE1_FIELDS, "cores.core1")
    _check_types(msg["core0"], _CORE0_FIELDS, "cores.core0")
    if any(v < 0 for v in list(msg["core1"].values()) + list(msg["core0"].values())):
        raise ValueError("cores: negative counter")


def validate_button(msg):
    _check_types(msg, _BUTTON_FIELDS, "button")
    if msg["type"] != "button" or msg["v"] != VERSION or msg["event"] != "segment":
        raise ValueError("button: bad type/v/event")


_DEVICE_VALIDATORS = {"emg": validate_device_message, "ack": validate_ack, "cores": validate_cores,
                      "button": validate_button}


def validate_device_line(msg):
    """Validate any message a device may send (emg, ack, cores, button); returns its type."""
    if not isinstance(msg, dict) or msg.get("type") not in _DEVICE_VALIDATORS:
        raise ValueError(f"unknown device message type {msg.get('type') if isinstance(msg, dict) else msg!r}")
    _DEVICE_VALIDATORS[msg["type"]](msg)
    return msg["type"]


def validate_bridge_message(msg):
    """Raise ValueError unless msg is a valid v1 message as sent by the bridge."""
    kind = msg.get("type")
    if kind == "status":
        _check_types(msg, _STATUS_FIELDS, "status message")
        if "last_rx_ms" not in msg:
            raise ValueError("status message: missing field 'last_rx_ms'")
        return
    if kind == "segment":
        _check_types(msg, _SEGMENT_FIELDS, "segment message")
        if msg["state"] not in SEGMENT_STATES:
            raise ValueError(f"segment message: bad state {msg['state']!r}")
        return
    if kind == "coach":
        _check_types(msg, _COACH_FIELDS, "coach message")
        if "command" not in msg or not (msg["command"] is None or isinstance(msg["command"], dict)):
            raise ValueError("coach message: command must be an object or null")
        if len(msg["feedback"].split()) > FEEDBACK_MAX_WORDS:
            raise ValueError("coach message: feedback too long")
        return
    if kind == "command":
        _check_types(msg, _COMMAND_FIELDS, "command message")
        if msg["cmd"] not in COMMANDS:
            raise ValueError(f"command message: bad cmd {msg['cmd']!r}")
        return
    if kind == "sync":
        _check_types(msg, _SYNC_FIELDS, "sync message")
        return
    validate_device_line(msg)
    _check_types(msg, {"bridge_rx_ms": (int, float), "src": str}, "bridge message")


FEEDBACK_MAX_WORDS = 20


def command_line(cmd, seq, **fields):
    """One downlink command line for the device: b'!{"v":1,"cmd":...,"seq":N}\n'."""
    if cmd not in COMMANDS:
        raise ValueError(f"unknown command {cmd!r}")
    body = {"v": VERSION, "cmd": cmd, **fields, "seq": seq}
    return b"!" + json.dumps(body, separators=(",", ":")).encode() + b"\n"


def check_llm_reply(raw):
    """Validate a coach reply (the LLM's raw text). Returns a dict:

        feedback        str, at most FEEDBACK_MAX_WORDS words (longer text is cut, truncated=True)
        command         {"hard_scale": x} with x inside the allowed range, or None
        clamped         the model asked for a value outside the range; x is the nearest limit
        command_error   why a command was dropped (None if there was none or it was fine)

    Raises ValueError when the reply as a whole is unusable (not JSON, no feedback text). A bad
    command never makes it to the device: it is dropped here and the feedback is kept.
    """
    try:
        reply = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"reply is not JSON: {e}") from None
    if not isinstance(reply, dict):
        raise ValueError("reply is not a JSON object")
    feedback = reply.get("feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        raise ValueError("reply has no feedback text")
    words = feedback.split()
    result = {"feedback": " ".join(words[:FEEDBACK_MAX_WORDS]), "truncated": len(words) > FEEDBACK_MAX_WORDS,
              "command": None, "clamped": False, "command_error": None}
    extra = set(reply) - {"feedback", "command"}
    command = reply.get("command")
    if extra:
        result["command_error"] = f"unexpected keys {sorted(extra)}"
    elif command is None:
        pass
    elif not isinstance(command, dict) or set(command) != {"hard_scale"}:
        result["command_error"] = "command must be {\"hard_scale\": number} or null"
    else:
        value = command["hard_scale"]
        if not _is(value, (int, float)) or not math.isfinite(value):
            result["command_error"] = f"hard_scale is not a finite number: {value!r}"
        else:
            clamped = min(HARD_SCALE_MAX, max(HARD_SCALE_MIN, float(value)))
            result["clamped"] = clamped != float(value)
            result["command"] = {"hard_scale": round(clamped, 2)}
    return result


def device_message(*, dev, boot, seq, sample_index, device_ms, rms_mv, norm, level, saturated, calibrating,
                   baseline_mv, led_state, cal=None):
    msg = {
        "type": "emg", "v": VERSION, "dev": dev, "boot": boot, "seq": seq, "sample_index": sample_index,
        "device_ms": device_ms, "rms_mV": round(rms_mv, 3), "norm": round(norm, 3), "level": level,
        "saturated": saturated, "calibrating": calibrating, "baseline_mV": round(baseline_mv, 3),
        "led_state": led_state,
    }
    if cal is not None:
        msg["cal"] = cal
    return msg


def encode(msg):
    return json.dumps(msg, separators=(",", ":")).encode()


class SeqTracker:
    """Per-sender loss / reordering / restart bookkeeping (docs/protocol.md)."""

    def __init__(self):
        self.boot = None
        self.expected = None
        self.received = 0
        self.lost = 0
        self.out_of_order = 0
        self.reboots = 0
        self.missing = set()     # recent seq values counted as lost, so a late arrival can be un-counted

    def update(self, boot, seq):
        """Account for one message; returns 'first', 'ok', 'gap', 'reboot' or 'out_of_order'."""
        self.received += 1
        if self.boot is None:
            state = "first"
        elif boot != self.boot or (seq == 0 and self.expected and self.expected > 1):
            self.reboots += 1
            state = "reboot"
        elif seq == self.expected:
            state = "ok"
        elif seq > self.expected:
            self.lost += seq - self.expected
            self.missing.update(range(max(self.expected, seq - 1000), seq))
            state = "gap"
        else:
            self.out_of_order += 1
            if seq in self.missing:      # it was counted as lost: it arrived late instead
                self.missing.discard(seq)
                self.lost -= 1
            return "out_of_order"
        if state in ("first", "reboot"):
            self.missing.clear()
        elif len(self.missing) > 1000:
            self.missing = {m for m in self.missing if m > seq - 1000}
        self.boot = boot
        self.expected = seq + 1
        return state
