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
