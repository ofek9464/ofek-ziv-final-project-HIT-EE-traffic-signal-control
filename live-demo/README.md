# HIT Traffic project presentation

Run `Start-Web-Demo.cmd` to open the prepared presentation at http://127.0.0.1:8766. This mode requires Python and a browser. Its server uses the Python standard library, and its browser animation uses Canvas.

The report column contains waiting-time cells extracted verbatim from `traffic-ai-final-report-v23.docx`. The experiment selector chooses section 4.8.1, table 24, or section 4.1, table 12. The default is the later comparison in section 4.8.1. This column displays final experimental results, with the original printed precision and standard deviations.

Start, pause, restart and scenario selection control ten-minute recorded SUMO runs. Each of the six scenarios contains 601 snapshots from 00:00 through 10:00, with four controllers, vehicle positions, pedestrian positions, signal states, queues, completed-trip waiting metrics and actual model inputs and decisions. Canvas interpolates recorded positions between snapshots. Playback defaults to 1x and holds its final frame until the presenter explicitly restarts. The timeline and speed selector allow navigation during a defense.

The table's current metrics and the evolving graph come from the original demo checkpoints on seed 201 during the first ten minutes of each demand. The report column contains the selected full experimental cohort. The interface labels the recording and the report reference separately.

Use the full-network control to switch all four maps between the selected junction and the complete road grid. Each controller also has an enlarged-map button. DQN and A2C decision explanations show the latest recorded directional input and chosen green duration, together with measured directional queues at the end of that green when it falls within the recording.

## Live simulation setup

For live simulation or recording regeneration, install Eclipse SUMO and run `Setup-Demo.cmd` once to install CPU PyTorch and the Python dependencies into `.venv`. The package includes twelve checkpoint files, road geometry and seed-201 vehicle and pedestrian demand files.

Run `Start-Web-Demo.cmd -Live` to open the real SUMO and PyTorch demonstration on port 8765. It shows four independent controllers, actual network inputs and outputs, and measured queue changes. The launcher supervises the live simulation server. The prepared presentation opens directly with Python and a browser.

In the tested Heavy west rollout, the original demo DQN selected 20 seconds in all 84 decisions and A2C selected 30 seconds in all 62 decisions. See `policy-diagnosis.md` for the checkpoint investigation. The recorded runs use these original demo checkpoints, while the report-reference column can display the later experimental comparison.

Run `.venv\Scripts\python.exe check_web_demo.py --scenario "Heavy west" --steps 180` to check the live runtime.

Run `python check_presentation.py` to check the prepared assets, all six recordings and the isolated server. Run `node check_presentation_timing.js` for the ten-minute timing and final-frame regression check. To rebuild the report data, pass the report and network paths to `build_presentation_data.py`. With simulation dependencies installed, `python record_presentation.py` regenerates the six recordings offline.

## Patch notes

2026-11-16 — Added a prepared presentation mode with 48 exact report cells, six scenarios, two named experiments, illustrative road animation and archived model decision examples. The default launcher opens this standard-library mode, and the live simulation remains available through `-Live`.

2026-11-17 — Replaced the illustrative two-minute animation with six ten-minute recordings of actual four-controller SUMO runs, including changing metrics and decision inputs. Restored full-network navigation, added enlarged maps and retained the final playback frame until an explicit restart. Active playback now resumes automatically after a scenario switch, with a guard against stale animation timestamps.
