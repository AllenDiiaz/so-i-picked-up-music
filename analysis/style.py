"""Shared figure style: fixed colors, font and white background for every plot."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIG_DIR = REPO / "docs" / "figures"

# One color per scenario, used in every figure.
COLORS = {
    "A": "#7f7f7f",  # gray
    "B": "#f08060",  # coral (experiment 03 only)
    "C": "#1a9e8f",  # teal
    "D": "#2b6cc4",  # blue
}
WARMUP_COLOR = "#e6e6e6"
REF_COLOR = "#555555"

DPI = 200
WIDTH_IN = 7.5


def apply():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.transparent": False,
        "axes.grid": True,
        "grid.color": "#dddddd",
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def save(fig, name):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO)}")
