"""Observe a running demo without changing it; report availability and live updates."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("Duration must be positive")
    names = ("TIMER", "SCRIPT", "DQN", "A2C")
    result = {"duration_seconds": args.seconds, "samples": 0, "failures": [],
              "max_response_ms": 0, "max_stall_seconds": 0,
              "motion_updates": dict.fromkeys(names, 0),
              "metric_updates": dict.fromkeys(names, 0), "graph_updates": 0, "examples": {}}
    started = time.monotonic()
    deadline = started + args.seconds
    last_time = None
    last_advance = started
    last_motion, last_metrics = {}, {}
    last_history_time = None
    run_id = None
    last_progress = -1
    while time.monotonic() < deadline:
        sample_started = time.monotonic()
        try:
            with urlopen(args.url + "/api/state", timeout=3) as response:
                state = json.load(response)
            result["max_response_ms"] = max(result["max_response_ms"], (time.monotonic() - sample_started) * 1000)
            result["samples"] += 1
            assert state["scenario"] == "Heavy west", "Scenario changed during observation"
            assert state["status"] == "running", f"Simulation status: {state['status']}, {state['error']}"
            if run_id is None:
                run_id = state["run_id"]
                result["start_sim_time"] = state["time"]
            assert state["run_id"] == run_id, "Simulation restarted during observation"
            if state["time"] != last_time:
                last_advance = time.monotonic()
                last_time = state["time"]
            stall = time.monotonic() - last_advance
            result["max_stall_seconds"] = max(result["max_stall_seconds"], stall)
            assert stall < 3, "Simulation clock stalled for three seconds"
            assert {run["name"] for run in state["runs"]} == set(names), "Missing controller"
            for run in state["runs"]:
                name = run["name"]
                positions = [(vehicle["id"], vehicle["position"]) for vehicle in run["vehicles"]]
                if run["vehicles"] and positions != last_motion.get(name):
                    result["motion_updates"][name] += 1
                last_motion[name] = positions
                metrics = (run["completed"], run["waiting"], run["queued"])
                if metrics != last_metrics.get(name):
                    result["metric_updates"][name] += 1
                last_metrics[name] = metrics
                for junction, decisions in run["decisions"].items():
                    if not decisions:
                        continue
                    decision = decisions[-1]
                    selected = max(range(len(decision["scores"])), key=decision["scores"].__getitem__)
                    assert selected == decision["selected"], "Displayed action differs from model output"
                    assert decision["chosen"] == state["actions"][selected], "Wrong action duration"
                    west = decision["state"]["approaches"]["west"]["queue_length"]
                    previous = result["examples"].get(name)
                    if previous is None or west > previous["west_queue"]:
                        result["examples"][name] = {"junction": junction, "decision_time": decision["time"],
                                                   "west_queue": west, "chosen": decision["chosen"],
                                                   "applied": decision["applied"], "phase": decision["phase"]}
            history_time = state["history"][-1]["time"] if state["history"] else None
            if history_time != last_history_time:
                result["graph_updates"] += 1
                last_history_time = history_time
            result["end_sim_time"] = state["time"]
        except Exception as error:
            result["failures"].append({"elapsed": round(time.monotonic() - started, 2), "error": str(error)})
        progress = int((time.monotonic() - started) // 30)
        if progress != last_progress:
            last_progress = progress
            print(f"elapsed={time.monotonic()-started:.0f}s samples={result['samples']} failures={len(result['failures'])} sim={last_time}", flush=True)
        time.sleep(max(0, min(deadline - time.monotonic(), 1 - (time.monotonic() - sample_started))))
    result["observed_seconds"] = round(time.monotonic() - started, 2)
    result["passed"] = not result["failures"] and all(result["motion_updates"].values()) and result["graph_updates"] > 1
    destination = Path(__file__).with_name("heavy-west-soak-report.json")
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
