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

