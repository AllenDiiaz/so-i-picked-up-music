"""Read-only parsers for the serial captures in docs/data/."""
import re

import numpy as np

from style import REPO

DATA_DIR = REPO / "docs" / "data"
FRAME_PERIOD_US = 16000

# I (1391) adc_wifi: core=0 wifi=1  rate=... frame_dt min/avg/max=13432/16849/66569  late=2/56 ...
_STATS = re.compile(r"^I \((\d+)\) adc_wifi: core=.*frame_dt min/avg/max=(\d+)/(\d+)/(\d+)")
_CONFIG = re.compile(r"^I \((\d+)\) adc_wifi: GPIO")


def load_03(filename):
    """Per-second windows of experiment 03.

    Returns arrays (start_s, end_s, min_us, max_us). Each statistics line covers the
    window from the previous line (or the config line, for the first one) to itself.
    """
    start = None
    ends, mins, maxs = [], [], []
    for line in (DATA_DIR / "03_wifi_interference" / filename).read_text().splitlines():
        m = _CONFIG.match(line)
        if m and start is None:
            start = int(m.group(1)) / 1000
            continue
        m = _STATS.match(line)
        if m:
            ends.append(int(m.group(1)) / 1000)
            mins.append(int(m.group(2)))
            maxs.append(int(m.group(4)))
    ends = np.array(ends)
    starts = np.concatenate([[start], ends[:-1]])
    return starts, ends, np.array(mins), np.array(maxs)


def load_04(filename):
    """Frame-to-frame intervals (us) between DATA_BEGIN and DATA_END of experiment 04."""
    lines = (DATA_DIR / "04_isr_core_affinity" / filename).read_text().splitlines()
    begin, end = lines.index("DATA_BEGIN"), lines.index("DATA_END")
    return np.array([int(x) for x in lines[begin + 1:end]])


#   5.819\tI (10867) adc_pot: raw=1934  voltage=1591 mV
_ONESHOT = re.compile(r"^\s*([\d.]+)\tI \((\d+)\) adc_pot: raw=\s*\d+\s+voltage=\s*(\d+) mV")


def load_05(filename):
    """Calibrated ADC readings of experiment 05, on the recording's own time axis.

    Each line carries the host arrival time (s since the recording started) and the
    board's log time (ms since boot). Lines buffered before the recording started all
    arrive at once near t = 0, so time comes from the board's clock: the offset between
    the two clocks is taken from lines that arrived live (smallest transfer delay), and
    readings taken before t = 0 are dropped.

    Returns arrays (t_s, mv).
    """
    host, board, mv = [], [], []
    for line in (DATA_DIR / "05_ad8232_bringup" / filename).read_text().splitlines():
        m = _ONESHOT.match(line)
        if m:
            host.append(float(m.group(1)))
            board.append(int(m.group(2)) / 1000)
            mv.append(int(m.group(3)))
    host, board, mv = np.array(host), np.array(board), np.array(mv)
    live = host > 0.5
    t = board - (board[live] - host[live]).max()
    keep = t >= 0
    return t[keep], mv[keep]
