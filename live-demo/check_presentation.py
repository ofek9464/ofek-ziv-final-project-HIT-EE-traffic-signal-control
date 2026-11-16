"""Check prepared assets and their server without importing SUMO, torch or site packages."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent


def check():
    data = json.loads((HERE / "presentation-data.json").read_text(encoding="utf-8"))
    assert len(data["experiments"]) == 2
    assert sum(len(s["results"]) for e in data["experiments"] for s in e["scenarios"]) == 48
    assert data["experiments"][0]["scenarios"][1]["results"]["DQN"]["display"] == "39.49 ± 4.90"
    assert data["experiments"][1]["scenarios"][1]["results"]["A2C"]["display"] == "45.07 ± 1.00"
    assert set(data["geometry"]["junctions"]) == {"B1", "C1"}
    assert all(len(event["vector"]) == 17 for event in data["recorded_decisions"].values())
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", str(HERE / "presentation_server.py"), "--port", "0", "--no-browser"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = process.stdout.readline().strip()
        assert line.startswith("Prepared presentation at "), line
        url = line.split()[-1]

        def fetch(path):
            with urllib.request.urlopen(url + path, timeout=5) as response:
                payload = response.read()
                assert response.status == 200 and payload
                assert response.headers["Cache-Control"] == "no-store"
                return payload

        for path in ["/", "/presentation.js", "/presentation.css", "/live.css", "/presentation-data.json"]:
            fetch(path)
        assert json.loads(fetch("/presentation-data.json")) == data
        manifest = json.loads(fetch("/recordings/manifest.json"))
        assert manifest["duration"] == 600 and len(manifest["scenarios"]) == 6
        for scenario in manifest["scenarios"]:
            compressed = fetch("/recordings/" + scenario["file"])
            assert hashlib.sha256(compressed).hexdigest() == scenario["sha256"]
            recording = json.loads(gzip.decompress(compressed))
            assert [frame["time"] for frame in recording["frames"]] == list(range(601))
            for frame in recording["frames"]:
                assert {run["name"] for run in frame["runs"]} == {"DQN", "A2C", "TIMER", "SCRIPT"}
                for run in frame["runs"]:
                    assert run["queued"] >= 0 and run["completed"] >= 0
                    for events in run["decisions"].values():
                        for event in events:
                            assert len(event["vector"]) == 17 and event["time"] <= frame["time"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert len(list(pool.map(fetch, ["/presentation-data.json"] * 40))) == 40
        try:
            fetch("/../web_demo.py")
            raise AssertionError("Unexpected file exposure")
        except urllib.error.HTTPError as error:
            assert error.code == 404
        assert process.poll() is None
        print("PASS: 48 report cells, six complete 600-second recordings with four controllers and real inputs, geometry, isolated standard-library server, 40 concurrent requests, file allowlist")
    finally:
        process.terminate()
        process.communicate(timeout=10)


if __name__ == "__main__":
    check()
