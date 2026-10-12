"""Protocol v1 (docs/protocol.md): message construction, validation and sequence tracking.

Shared by tools/replay_stream.py, bridge/bridge.py and tests/test_e2e_replay.py.
"""
import json
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


def validate_bridge_message(msg):
    """Raise ValueError unless msg is a valid v1 message as sent by the bridge."""
    if msg.get("type") == "status":
        _check_types(msg, _STATUS_FIELDS, "status message")
        if "last_rx_ms" not in msg:
            raise ValueError("status message: missing field 'last_rx_ms'")
        return
    validate_device_message(msg)
    _check_types(msg, {"bridge_rx_ms": (int, float), "src": str}, "bridge message")


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
