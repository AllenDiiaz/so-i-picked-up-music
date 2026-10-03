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
