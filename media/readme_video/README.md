# README video

The GIF at the top of the repository README: `docs/figures/so_i_picked_up_music_25s.gif` (and `.mp4`). 1600x900 at 12 fps; the GIF is 10 fps, 1100 px wide, 128 colours (7.6 MB).

| Scene | Length | Source |
|---|---|---|
| Demo | 8.5 s | Frames of the previous render, unchanged: practice video next to a lab EMG recording. **Draft, placeholders**: the signal is not from that take, the sections are invented. It carries its own note saying so |
| Architecture | 6.5 s | New (`v6_layers.py`): two cores on the board, bridge, browser view (WebXR-ready), local AI coach. The command downlink is dashed: built, not yet run on the board |
| A/B | 7.0 s | New (`v6_capture_ab.py`): the real front end in headless Chrome, naive (left) and designed (right), lined up on the end of the practice segment. **Simulated device** and mock coach, labelled in the scene |
| Circuit | 3.0 s | Frames of the previous render, unchanged |

## Build

```sh
.venv/bin/pip install -r tests/requirements.txt        # Playwright; uses the installed Google Chrome
brew install ffmpeg gifsicle && brew install --cask font-inter
.venv/bin/python media/readme_video/v6_layers.py       # -> build/v6/*.png, geom.json
.venv/bin/python media/readme_video/v6_capture_ab.py   # -> build/ab/<mode>/*.png (about 1 min)
.venv/bin/python media/readme_video/v6_gif.py          # -> docs/figures/so_i_picked_up_music_25s.{mp4,gif}
.venv/bin/python media/readme_video/v6_gif.py OUT SNAP # stills of every scene into SNAP, for checking
```

`build/` and `private/` are git-ignored.

## private/ (not in the repository)

| File | Used for |
|---|---|
| `so_i_picked_up_music_20s.mp4` | The previous 20 s render (kit v4). The v6 scripts take the header, the arm with its electrodes and leads, the demo scene and the circuit scene from its frames |
| `814115789.158804.mp4` | The practice video the kit's `v4_gif.py` reads; not read by the v6 scripts |

The arm is a licensed BioRender illustration. Neither the source PNG nor the previous render is committed; the published GIF shows the arm as part of the figure, as the previous one did.

## The kit scripts (v3, v4, v5, arm_extract, demo_data)

Kept as received, for reference and for the real take. **They do not run in this repository as they are**: they point at paths of the machine they were written on (`/root/.claude/uploads/...`, `/home/claude/...`) and need files that did not come with the kit (`arm_svg.py`, `arm/bio_arm_cream.png`, the hand photo, the BioRender source PNG). That is why v6 reuses the previous render's frames instead of re-rendering those scenes.

## What to swap once real material exists

- Demo scene: render it again from the Parade practice take and the USB EMG captured during the same take (the session log of `bridge.py` plus a sync flash, key `f`, to line them up). This needs the kit's `v4_gif.py` made runnable (paths, missing files) or a new demo scene in `v6_gif.py`. Then remove "draft" from that scene.
- A/B scene: capture it again with the board instead of `tools/fake_device.py` and drop "simulated device".
- Architecture: make the downlink solid in `v6_layers.py` once 11_coach_loop has run on the board.
