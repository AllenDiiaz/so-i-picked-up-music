# README video kit (20 s GIF)

Order: demo 11 s -> architecture 5 s -> circuit 4 s. 1600x900, 12 fps -> GIF 10 fps, 1100 px, 128 colours.

Build:
    python3 arm_extract.py      # BioRender arm -> arm/bio_arm.png (needs the licensed source PNG; not in the repo)
    python3 v3_layers.py        # header + circuit vector layers -> v3/
    python3 v5_layers.py        # architecture layers -> v5/
    python3 v4_gif.py OUT_DIR   # -> so_i_picked_up_music_20s.mp4 / .gif

What to swap once real material exists:
- VID in v4_gif.py: the Parade practice video (+ -ss offset so the clap lines up).
- demo_data.py: replace the spliced lab recording with the USB EMG captured during the same take; drop SPLICE.
- scene_demo sections: real section names and bar ranges (4/4, 110 BPM already set).
- v5_layers.py: switch the Quest WebXR / AI coach cards from planned (dashed) to built, add a headset screenshot.
