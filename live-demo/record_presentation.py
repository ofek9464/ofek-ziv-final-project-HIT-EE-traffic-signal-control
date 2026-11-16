"""Prepare real ten-minute SUMO sessions for dependency-free browser playback."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from web_demo import CONTROLLERS, LiveRun, geometry, torch, traci

HERE = Path(__file__).resolve().parent
SCENARIOS = ["Balanced", "Heavy west", "Pedestrian heavy", "Morning rush", "Evening rush", "Full day cycle"]


def record():
    torch.set_num_threads(1)
    destination = HERE / "recordings"
    destination.mkdir(exist_ok=True)
    manifest = {"duration": 600, "seed": 201, "step": 1, "geometry": geometry(), "scenarios": []}
    for index, scenario in enumerate(SCENARIOS):
        runs = []
        frames = []
        with tempfile.TemporaryDirectory(prefix="hit-recording-") as folder:
            try:
                for name, color, controller in CONTROLLERS:
                    run = LiveRun(name, color, controller, scenario, 201, 600, folder)
                    run.start()
                    runs.append(run)
                frames.append({"time": 0, "runs": [run.payload() for run in runs]})
                for elapsed in range(1, 601):
                    payloads = []
                    for run in runs:
                        run.step()
                        payload = run.payload()
                        payload["decisions"] = {junction: events[-1:] for junction, events in payload["decisions"].items()}
                        for vehicle in payload["vehicles"]:
                            vehicle["position"] = [round(value, 2) for value in vehicle["position"]]
                            vehicle["angle"] = round(vehicle["angle"], 1)
                            vehicle["speed"] = round(vehicle["speed"], 2)
                        payloads.append(payload)
                    frames.append({"time": elapsed, "runs": payloads})
            finally:
                for run in runs:
                    traci.getConnection(run.name).close()
        filename = f"scenario-{index}.json.gz"
        content = json.dumps({"scenario": scenario, "seed": 201, "duration": 600, "frames": frames},
                             separators=(",", ":"), allow_nan=False).encode()
        compressed = gzip.compress(content, mtime=0)
        (destination / filename).write_bytes(compressed)
        manifest["scenarios"].append({"id": index, "name": scenario, "file": filename,
                                      "sha256": hashlib.sha256(compressed).hexdigest(), "frames": len(frames)})
        print(f"Recorded {scenario}: {len(frames)} frames, {len(compressed)} bytes", flush=True)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    record()
