# Autonomous work log (2026-11-16)

Log of an unattended working session: decisions taken without asking, what was verified, and what still needs the board. Newest entries at the bottom; the summary is at the end.

## Part 0: environment

| Item | Result |
|---|---|
| 0-1 Permissions | `.claude/settings.local.json` written (allow list as requested; `git push --force`, `rm -rf`, `sudo` denied) and git-ignored. Verified with `git check-ignore -v` |
| 0-2 Video kit | `~/Downloads/readme_video_kit (1).zip` (the only candidate) unpacked to `media/readme_video/` |
| 0-2 Practice video | `~/Downloads/814115789.158804.mp4` copied to `media/readme_video/private/`. Chosen because `v4_gif.py` in the kit names exactly this file as `VID`. `linkedin-video-789kbps.mp4` (same day) was not copied: nothing identifies it as a practice video |
| 0-2 Previous render | `~/Downloads/so_i_picked_up_music_20s.mp4` and `.gif` (2026-11-16) copied to `private/` as reference |
| 0-2 BioRender arm PNG | **Not found.** `~/Downloads` holds no PNG that could be it (only screenshots from 2025 and two JPGs); a search of Desktop, Documents and Pictures for `biorender`, `arm`, `forearm`, `muscle`, `emg` found nothing. The kit's `arm_extract.py` reads it from an upload path of another machine. Nothing was guessed; see the video section for how the arm is handled |
| 0-2 Ignore check | `git status` shows nothing under `private/`; `git check-ignore -v` matches `media/readme_video/private/` |
| 0-3 Ollama | `brew install ollama ffmpeg`, `brew services start ollama`, `ollama pull llama3.2:3b` all succeeded (Ollama 0.40.16). The `curl localhost:11434/api/generate` check returned `"response":"OK"` |

Also done before this session's task list: `.venv` created, `tests/test_e2e_replay.py` passed, `10_usb_stream` built with ESP-IDF v6.0.3.

## Decisions

- **`hard_scale` as the one tunable parameter.** The task names `{"hard_scale": n}` without a definition. It is implemented as a multiplier on the hard entry and exit ratios (2.72 / 2.45), allowed range 0.80-1.50, default 1.00. The lower limit keeps hard above medium (0.80 x 2.45 = 1.96 > 1.49). The range is a design choice, not derived from data.
- **`emg_dsp.c` is not modified** (07, 08 and 10 share it). The scaled level is computed in a new component `11_coach_loop/components/coach` from the DSP's normalized value. The host test shows it equals the DSP's level on every hop at scale 1.00 for both experiment 06 recordings.
- **Invalid command lines get no ack**: they are dropped and counted (`core0.parse_fail`), as specified. Out-of-range values are clamped and acked with `"clamped":true`.
- **Fallback never re-sends a command.** When the model is unreachable, late or its reply is unusable, the last good feedback text is shown again, marked `fallback`, and no command goes to the board. Repeating an old parameter change without a fresh judgement seemed the less conservative choice.
- **Empty `set_params` in naive mode.** A naive device blocks until a reply arrives. When the coach has no parameter to send (null or rejected command), the bridge sends `set_params` without a value, which changes nothing but releases the device. In designed mode nothing is sent in that case.
- **Board button.** 10 uses the button for calibration. In 11 a short press sends a `button` message (segment start / end) and holding it for 1 s calibrates. Untested on the board.
- **The designed path tests one extra flag** (`s_naive_wait`, set only in naive mode) at the end of each frame. Beyond that, and the lock-free read of the parameter word and the timing counters, the sampler is the code of 10.
- **Simulated `cores` numbers.** The fake device has no ADC or DMA, so its core 1 timing is a model: 0 µs when the sampler never waits, the wait length when it blocks. Every such message carries `"simulated": true`. Real jitter is not modelled.
- **Side effect of `brew install`:** Homebrew also installed Python 3.15 and made it the default `python3` (it was 3.14.8). ESP-IDF's `export.sh` then fails, because its environment is `idf6.0_py3.14_env`. Nothing was reinstalled; `scripts/idf_env.sh` puts the matching `python3.14` first on PATH and then sources `export.sh`. `.venv` still uses 3.14.8.
- **"Only design C" in the front end.** C (edge glow) is now the default and the A / B buttons are hidden. A and B were not deleted: keys 1 / 2 and `?designs=all` still reach them, because `tests/screenshot_frontend.py` covers all three and removing tested code was not asked for. In C the grey guitar / arm stand-ins are hidden, so the centre stays clear.
- **WebXR wording.** The `immersive-ar` code is kept and untouched in behaviour. README, architecture and mvp now say "browser view, WebXR-ready" and state that it was never run on a headset. The Quest items were removed from the plan, not marked done.
- **Segment controls.** Keyboard = Enter in the bridge's terminal (plus `n` / `d` / `f` then Enter); browser = space or the button; board = short button press (code path exists in the bridge and firmware, but the simulated device has no button, so it is untested end to end).
- **Ollama timing.** The first real reply took 7.2 s from cold (about 3.4 s of it loading the model), close to the 10 s timeout. The bridge now loads the model at start and asks Ollama to keep it for 30 min; warm replies took 0.7-1.5 s.
- **Ollama quality (finding, not fixed).** In the saved round trip the segment was 82 % relax, 10 % medium, 7 % hard. `llama3.2:3b` answered "Maintain consistent tension to avoid discomfort." and raised `hard_scale` to 1.10, although the prompt says to lower it when the player was mostly relaxed. The loop handled it correctly (valid shape, in range, sent, acked), but the coaching itself is not trustworthy with this model and prompt. The prompt was not tuned to make the example look better.

- **A mistake of mine, caught and fixed.** One scripted edit of `web/app.js` matched an empty string and inserted text between every character of the file. The capture script failed immediately, the file was restored from the last commit and the two small edits were reapplied. Nothing broken was committed.

## Video

- **The kit cannot run here as delivered.** `v3_layers.py` imports `arm_svg.py`, `v5_layers.py` reads `arm/bio_arm_cream.png`, `v3_gif.py` opens a hand photo, and several paths point at another machine (`/root/.claude/uploads/...`, `/home/claude/...`); none of those files came with the zip, and the BioRender source PNG was not in `~/Downloads`. After establishing that, I stopped trying to run it and changed the approach.
- **Approach taken:** new scripts `v6_layers.py`, `v6_capture_ab.py`, `v6_gif.py` beside the untouched kit files. The header, the arm (with electrodes and leads), the demo scene and the circuit scene are taken from the frames of the previous render (`private/so_i_picked_up_music_20s.mp4`, found in `~/Downloads`). The architecture scene and the A/B scene are new. Palette, fonts (Inter installed with `brew install --cask font-inter`) and the helper code follow the kit.
- **Architecture scene:** Quest card removed; "Browser view (WebXR-ready)" card; AI coach card drawn as built (solid), because both the mock and the local Ollama model were actually run through the loop in this session; core 0 / core 1 split; the coach round trip. The downlink into the board and the `cmd_rx` task are dashed with the legend "built · not yet run on the board". This goes beyond the instruction (which only asked about the coach card) on the side of saying less.
- **A/B scene:** the real `web/` page (`?view=cores`, a compact layout added for this) recorded in headless Chrome as timed screenshots, once per mode, lined up on the segment end. Labelled "simulated device" in the page itself and in the caption line. The segment is 2.5 s of relaxed forearm, chosen so the edge glow stays quiet; with an earlier timing the recording's hard grip turned both panels red and made the text unreadable.
- **In the naive panel the glow turns reddish for a moment after the wait.** This is not staged: the lost samples leave a step in the filter input and the DSP shows a short burst.
- **Demo scene:** unchanged frames, still carrying its own note ("draft · signal: lab recording ... not synced to the video · sections are placeholders"). It was shortened from 11 s to 8.5 s to fit; nothing else was touched.
- **Checks:** stills of all four scenes inspected at 1600 px and frames of the final GIF at 1100 px: no clipped or overlapping text found. GIF 7.6 MB, 25.0 s; MP4 2.1 MB, video only (no audio track). The GIF's 128-colour palette shifts the lead-wire colours slightly and bands the dark gradients.

## To verify on the board

Nothing in `11_coach_loop` has been flashed. In order:

1. **Bring-up as in session 2**: fresh electrodes, AD8232 output near 1600 mV with the lead cable unplugged, `10_usb_stream` still streams and calibrates (confirms the hardware before changing firmware).
2. **Flash `11_coach_loop`**; `bridge.py --serial /dev/cu.usbmodem1101 --llm mock`. Expect `emg` at 20 Hz and one `cores` message per second, `simulated: false`.
3. **`cores` numbers plausible**: `frames` 62-63, `max_dev_us` in the tens of µs (experiment 04: within 63 µs), `late` 0, `ovf` 0, `drop` 0.
4. **Downlink**: start and end a segment from the browser. `core0.cmd_rx` and `applied` count up, acks arrive, `parse_fail` stays 0. This is the first time the board reads its USB input: `usb_serial_jtag_read_bytes` behaviour is untested.
5. **`set_params` takes effect**: an ack with `applied.hard_scale` and a `sample_index`; the hard threshold line in the chart moves.
6. **Does opening or writing the port reset the board?** Session 2 saw a reset on open. The bridge opens once; check that writes do not reset it.
7. **Timing under command load**: `max_dev_us` and `late` while commands arrive, compared with step 3. This is the claim "commands do not disturb sampling", so far only argued and simulated.
8. **Naive mode** (`m` in the page): after a segment end the stream stops until the reply, `blocked_ms` and `ovf` rise, then the board recovers and `mode designed` restores normal behaviour. Check the 15 s timeout with the bridge stopped.
9. **Button**: short press toggles a segment, 1 s hold calibrates. Check that a short press never calibrates and the other way round.
10. **Stack and queues**: no `event_drop`, no watchdog or stack overflow over a 10 min run with several segments.
11. **Ollama on the real stream**: `--llm ollama`, a few segments while playing; read the replies.
12. **Level identity**: at `hard_scale` 1.00 the levels should look like 10's. On the board this can only be checked by eye; the host test covers it exactly.

Still open from before, unchanged by this session: three levels on the guitar (criterion 1), latency with the LED and slow motion (criterion 2), the 5 min run (criteria 3, 4), Wi-Fi interference.

## Summary

### Done

| Item | State |
|---|---|
| 0. Environment | Permissions file, video kit unpacked, private media ignored, Ollama + `llama3.2:3b` installed and answering, ffmpeg and Inter installed |
| 1. Bridge | Two-way serial on one handle; segments from keyboard, browser and board button; statistics -> coach in a worker thread (10 s timeout) -> validated, clamped reply -> command -> ack; fallback; everything in the session log |
| 2. Simulated device | `tools/fake_device.py`: pty, experiment 06 recordings, the firmware's own `emg_dsp.c` and `coach.c`, `!` commands with acks, `cores` once per second marked simulated, naive and designed modes |
| 3. Firmware | `firmware/experiments/11_coach_loop` (10 untouched): `cmd_rx` on core 0, single 32-bit hand-over word, acks, clamping, `cores`, naive mode, button; host test for the parser and the level |
| 4. Front end | Coach text with fade, segment states, the "LLM -> command -> ack" line, two-core timeline, mode display, sync flash with beep and bridge time stamp |
| 5. Tests | `tests/test_e2e_coach.py` (both modes, scripted coach, optional real Ollama); host test; existing replay and screenshot tests still pass |
| 6. Documents | README, architecture.md, protocol.md, mvp.md, 11 README |
| 7. Video | `docs/figures/so_i_picked_up_music_25s.gif` (7.6 MB, 25 s) and `.mp4`, embedded at the top of the README |

### Verified (by running it in this session)

- Host test: 32 malformed command lines rejected; clamping; level at `hard_scale` 1.00 identical to `emg_dsp` on 1495 + 1295 hops.
- `idf.py build` of `11_coach_loop`: passes, no warnings from the new sources (ESP-IDF v6.0.3).
- End-to-end with the simulated device, both modes: seq continuous, every ack matches its command, illegal command stopped, out-of-range command clamped to 1.50 and acked, non-JSON reply -> fallback marked and nothing applied, session log complete. Designed: longest pause 20-24 ms while the coach thought for 1 s. Naive: about 1 s hole per segment, blocking and lost samples reported.
- Real Ollama round trip (`llama3.2:3b`): schema-constrained reply, command sent and acked; 7.2 s from cold, 0.7-1.5 s warm.
- Existing tests: `tests/test_e2e_replay.py` and `tests/screenshot_frontend.py` pass.
- Front end: looked at headless Chrome screenshots in both modes.
- Video: stills of every scene and frames of the final GIF inspected.

### Only built or only simulated

- Everything in `11_coach_loop` on the actual board (see the list above).
- The designed-versus-naive comparison: simulation only. The simulated core 1 timing is a model.
- The board button path (firmware and bridge code exist; no simulated button, so never exercised end to end).
- The front-end additions have no automated test; `tests/screenshot_frontend.py` does not look at them.
- The sync flash: the round trip is tested, the beep and the visual flash were not checked by ear or eye.
- The Mermaid diagram in architecture.md was not rendered here; check it on GitHub.
- The coach's usefulness: not evaluated. With `llama3.2:3b` and this prompt the one saved reply contradicted the prompt's rule.
- `hard_scale` and its range: a design choice without data.
- WebXR: code kept, never run on a headset. No AR is claimed anywhere.

### Not done, and why

- **BioRender PNG not placed in `private/`**: it is not in `~/Downloads`. If you have it, put it in `media/readme_video/private/`; nothing in the v6 scripts needs it yet.
- **Demo scene not rebuilt**: the kit scripts that draw it cannot run here (missing files), and the real take does not exist yet.
- **No Parade material of any kind** was added; the demo scene shows bar numbers and placeholder sections only.

### Before recording on Friday

1. Work through "To verify on the board" 1-8 first; if 11 misbehaves, 10 plus the browser view still gives the tension demo, without the coach loop.
2. ESP-IDF shell: `. scripts/idf_env.sh` (plain `export.sh` now fails because Homebrew changed the default python3).
3. Start Ollama before the take (`brew services start ollama`); the bridge warms the model up. Decide whether the 3B model's feedback is good enough to show; `--model` takes any model you have pulled, and `--llm mock` is the deterministic fallback. The prompt is in `bridge/coach.py`.
4. Recording: `bridge.py --serial ... --llm ollama`, page at http://localhost:8000/, press `f` once at the start (white flash and beep) so the screen recording, the camera and `sessions/*.jsonl` can be lined up, space to start and end each segment.
5. Keep the session log of the take: it holds the tension stream, the coach request and reply, the command and the ack.
6. For the README video afterwards: see "What to swap" in `media/readme_video/README.md`.
7. Wording for the form: USB transport, browser view (WebXR-ready, not run on a headset), coach loop tested on the board or not, depending on steps 2-8. Wi-Fi interference is an open problem.
