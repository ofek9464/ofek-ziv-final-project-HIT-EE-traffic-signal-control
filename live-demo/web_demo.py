"""Local, headless SUMO demo with the actual trained controllers and inference data."""
import argparse
from collections import deque
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
import tempfile
import threading
import time
import uuid
from unittest.mock import patch
import webbrowser

from demo import (
    ACTIONS, CONTROLLERS, HERE, Run, SCENARIOS, SIM, config, sumolib, traci,
)
from controllers.ai_controller import state_to_vector
from modules import state_builder
import torch
import traci.constants as tc


def geometry():
    net = sumolib.net.readNet(config.NET_FILE, withInternal=True, withPedestrianConnections=True)
    signals = {}
    for junction in config.CONTROLLED_JUNCTIONS:
        signals[junction] = [
            {"index": index, "shape": incoming.getShape()}
            for incoming, outgoing, index in net.getTLS(junction).getConnections()
        ]
    return {
        "bounds": net.getBoundary(),
        "lanes": [
            {"shape": lane.getShape(), "width": lane.getWidth(),
             "pedestrian": lane.allows("pedestrian") and not lane.allows("passenger")}
            for edge in net.getEdges(withInternal=True) for lane in edge.getLanes()
        ],
        "junctions": {j: net.getNode(j).getCoord() for j in config.CONTROLLED_JUNCTIONS},
        "signals": signals,
    }


class LiveRun(Run):
    def __init__(self, name, color, controller_type, scenario, seed, duration, folder):
        super().__init__(name, color, controller_type, scenario)
        self.seed, self.duration = seed, duration
        self.tripinfo = Path(folder) / f"{name}-tripinfo.xml"
        self.events = {j: deque(maxlen=8) for j in config.CONTROLLED_JUNCTIONS}
        self.action_counts = {j: {str(action): 0 for action in ACTIONS}
                              for j in config.CONTROLLED_JUNCTIONS}
        self.completed_wait = 0.0
        self.completed_count = 0
        self.previous_waits = {}
        self.active = []
        self.persons = []
        self.lights = {}
        self.queued = 0
        self.queues = {}

    def start(self):
        routes = [SIM / "scenarios" / f"{self.demand}_s{self.seed}{suffix}.xml"
                  for suffix in (".rou", ".ped")]
        for path in routes:
            if not path.is_file():
                raise FileNotFoundError(f"Test route missing: {path}")
        command = [sumolib.checkBinary("sumo"), "-n", config.NET_FILE,
                   "-r", ",".join(map(str, routes)), "--seed", str(self.seed),
                   "--begin", str(self.begin),
                   "--waiting-time-memory", str(self.duration + 1),
                   "--tripinfo-output", str(self.tripinfo),
                   "--no-step-log", "--no-warnings"]
        port = sumolib.miscutils.getFreeSocketPort()
        process = subprocess.Popen(
            command + ["--remote-port", str(port)], stdout=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            traci.init(port, label=self.name, proc=process)
            for edge in (*config.J1_APPROACHES.values(), *config.J2_APPROACHES.values()):
                traci.edge.subscribe(edge, [tc.LAST_STEP_VEHICLE_HALTING_NUMBER])
        except BaseException:
            process.terminate()
            process.wait()
            raise

    def step(self):
        states = {}
        original = state_builder.build_state

        def observe(junction):
            state = original(junction)
            states[junction] = copy.deepcopy(state)
            return state

        # Capture the same state object used by the unmodified controller.
        # TraCI and this instrumentation run exclusively on the simulation thread.
        with patch.object(state_builder, "build_state", observe):
            super().step()
        for junction, state in states.items():
            if not self.learned:
                continue
            when, phase, vector, scores, critic, selected, applied = self.decisions[junction]
            if vector != state_to_vector(state).tolist():
                raise RuntimeError("Captured state differs from the model input")
            self.events[junction].append({
                "id": self.count * 2 + config.CONTROLLED_JUNCTIONS.index(junction),
                "time": when, "junction": junction, "phase": phase,
                "state": state, "vector": vector, "scores": scores,
                "score_type": "Q-value" if self.name == "DQN" else "Probability",
                "critic": critic, "chosen": ACTIONS[selected], "applied": applied,
                "override": abs(applied - ACTIONS[selected]) > 0.001,
                "selected": selected,
                "outcome": None,
            })
            self.action_counts[junction][str(ACTIONS[selected])] += 1
        self.telemetry()
        elapsed = traci.simulation.getTime() - self.begin
        for junction, events in self.events.items():
            for event in events:
                if event["outcome"] is None and elapsed >= event["time"] + event["applied"]:
                    event["outcome"] = {"time": elapsed, "queues": dict(self.queues[junction])}

    def telemetry(self):
        edge_results = traci.edge.getAllSubscriptionResults()
        self.queued = sum(row[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
                          for row in edge_results.values())
        self.queues = {
            junction: {direction: edge_results[edge][tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
                       for direction, edge in approaches.items()}
            for junction, approaches in zip(config.CONTROLLED_JUNCTIONS,
                                            (config.J1_APPROACHES, config.J2_APPROACHES))
        }
        for vehicle in traci.simulation.getArrivedIDList():
            if vehicle not in self.previous_waits:
                raise RuntimeError(f"Missing completed-trip waiting time for {vehicle}")
            self.completed_wait += self.previous_waits.pop(vehicle)
            self.completed_count += 1
        variables = [tc.VAR_ACCUMULATED_WAITING_TIME, tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_SPEED]
        for vehicle in traci.simulation.getDepartedIDList():
            traci.vehicle.subscribe(vehicle, variables)
        results = traci.vehicle.getAllSubscriptionResults()
        self.previous_waits = {v: row[tc.VAR_ACCUMULATED_WAITING_TIME] for v, row in results.items()}
        self.active = [
            {"id": v, "position": row[tc.VAR_POSITION], "angle": row[tc.VAR_ANGLE],
             "speed": row[tc.VAR_SPEED]} for v, row in results.items()
        ]
        self.persons = [traci.person.getPosition(p) for p in traci.person.getIDList()]
        self.lights = {
            j: {"state": traci.trafficlight.getRedYellowGreenState(j),
                "phase": traci.trafficlight.getPhase(j), "remaining": self.remaining[j]}
            for j in config.CONTROLLED_JUNCTIONS
        }

    def payload(self):
        return {
            "name": self.name, "decisions": copy.deepcopy({j: list(events) for j, events in self.events.items()}),
            "action_counts": copy.deepcopy(self.action_counts),
            "vehicles": self.active, "pedestrians": self.persons, "lights": self.lights,
            "completed": self.completed_count,
            "queued": self.queued,
            "queues": self.queues,
            "waiting": self.completed_wait / self.completed_count if self.completed_count else None,
            "weights": f"{self.name.lower()}_{self.demand}_ms_weights.pt" if self.learned else None,
        }


class Simulation:
    def __init__(self, scenario="Balanced", seed=201, duration=None, speed=4):
        self.scenario, self.seed, self.speed = scenario, seed, speed
        self.requested_duration = duration
        self.duration = duration if duration is not None else SCENARIOS[scenario][2]
        self.run_id = 0
        self.session_id = uuid.uuid4().hex
        self.history = []
        self.commands = Queue(maxsize=32)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.snapshot = {"status": "loading", "time": 0, "runs": [], "error": None}
        self.snapshot_bytes = json.dumps(self.snapshot).encode()
        self.runs = []
        self.thread = threading.Thread(target=self.work, name="SUMO", daemon=True)

    def read(self):
        with self.lock:
            return self.snapshot

    def publish(self, status, elapsed, error=None):
        runs = [] if status == "loading" else [r.payload() for r in self.runs]
        if elapsed > 0 and (not self.history or elapsed - self.history[-1]["time"] >= 5
                            or (elapsed > self.history[-1]["time"] and status in ("paused", "complete"))):
            self.history.append({"time": elapsed, "waiting": {r["name"]: r["waiting"] for r in runs}})
        snapshot = {"status": status, "time": elapsed, "error": error,
                    "scenario": self.scenario, "seed": self.seed, "duration": self.duration,
                    "speed": self.speed, "actions": ACTIONS, "runs": runs,
                    "run_id": self.run_id, "session_id": self.session_id,
                    "history": list(self.history), "scenarios": list(SCENARIOS)}
        with self.lock:
            self.snapshot = snapshot
            self.snapshot_bytes = json.dumps(snapshot, allow_nan=False).encode()

    def read_bytes(self):
        with self.lock:
            return self.snapshot_bytes

    def close_runs(self):
        for run in self.runs:
            try:
                traci.getConnection(run.name).close()
            except (traci.exceptions.TraCIException, traci.exceptions.FatalTraCIError, OSError):
                pass
        self.runs = []

    def load(self, folder):
        self.run_id += 1
        self.history = []
        self.duration = self.requested_duration if self.requested_duration is not None else SCENARIOS[self.scenario][2]
        self.publish("loading", 0)
        self.close_runs()
        for name, color, controller_type in CONTROLLERS:
            run = LiveRun(name, color, controller_type, self.scenario,
                          self.seed, self.duration, folder)
            run.start()
            self.runs.append(run)

    def work(self):
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory(prefix="hit-live-demo-") as folder:
            while not self.stop.is_set():
                try:
                    self.run_session(folder)
                except Exception as error:
                    import traceback
                    traceback.print_exc()
                    self.publish("error", self.read().get("time", 0), str(error))
                finally:
                    self.close_runs()
                while not self.stop.is_set():
                    try:
                        command = self.commands.get(timeout=0.1)
                    except Empty:
                        continue
                    if command["action"] in ("restart", "scenario"):
                        self.scenario = command.get("scenario", self.scenario)
                        break

    def run_session(self, folder):
        elapsed = 0
        playing = False
        target = None
        last_publish = 0.0
        self.load(folder)
        self.publish("paused", elapsed)
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                command = self.commands.get(timeout=0 if playing or target else 0.1)
            except Empty:
                command = None
            if command:
                action = command["action"]
                if action == "scenario":
                    self.scenario = command["scenario"]
                    self.load(folder)
                    elapsed, target = 0, None
                elif action == "restart":
                    self.load(folder)
                    elapsed, playing, target = 0, False, None
                elif action == "pause":
                    playing, target = False, None
                elif elapsed < self.duration:
                    if action == "play":
                        playing, target = True, None
                    elif action in ("next", "finish"):
                        run = next(r for r in self.runs if r.name == command["model"])
                        junction = command["junction"]
                        events = run.events[junction]
                        event_id = command.get("event_id") if action == "finish" else events[-1]["id"] if events else None
                        target = (run, junction, event_id, action)
                        playing = False
                self.publish("complete" if elapsed >= self.duration else
                             "seeking" if target else "running" if playing else "paused", elapsed)
            if (playing or target) and elapsed < self.duration:
                for run in self.runs:
                    run.step()
                elapsed += 1
                if target:
                    run, junction, previous, action = target
                    events = run.events[junction]
                    finished = any(e["id"] == previous and e["outcome"] is not None for e in events)
                    if (action == "finish" and finished or
                            action == "next" and events and events[-1]["id"] != previous):
                        target = None
                if elapsed >= self.duration:
                    playing, target = False, None
                now = time.monotonic()
                if now - last_publish >= 0.1 or not (playing or target):
                    self.publish("complete" if elapsed >= self.duration else
                                 "seeking" if target else "running" if playing else "paused", elapsed)
                    last_publish = now
                if playing:
                    self.stop.wait(max(0, 1 / self.speed - (time.monotonic() - started)))


class DemoServer(HTTPServer):
    # Simulation is asynchronous. HTTP replies need no per-request threads.
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            self.send_data(self.server.simulation.read_bytes(), "application/json")
        elif path == "/api/geometry":
            self.send_data(self.server.geometry_data, "application/json")
        elif path == "/favicon.ico":
            self.send_data(b"", "image/x-icon")
        elif path in ("/", "/live.html", "/live.css", "/live.js"):
            name = "live.html" if path == "/" else path[1:]
            mime = {"html": "text/html", "css": "text/css", "js": "text/javascript"}[name.rsplit(".", 1)[1]]
            self.send_data((HERE / name).read_bytes(), mime)
        else:
            self.send_error(404)

    def do_POST(self):
        expected = f"http://{self.headers.get('Host', '')}"
        allowed_hosts = (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
        if (self.headers.get("Host") not in allowed_hosts or self.path != "/api/control"
                or self.headers.get("Origin", expected) != expected
                or self.headers.get_content_type() != "application/json"):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid request size")
            command = json.loads(self.rfile.read(length))
            if not isinstance(command, dict) or command.get("action") not in ("play", "pause", "next", "finish", "restart", "scenario"):
                raise ValueError("Unknown command")
            if command["action"] == "scenario" and command.get("scenario") not in SCENARIOS:
                raise ValueError("Unknown scenario")
            if command["action"] in ("next", "finish"):
                if command.get("model") not in ("DQN", "A2C") or command.get("junction") not in config.CONTROLLED_JUNCTIONS:
                    raise ValueError("Unknown model or junction")
            if command["action"] == "finish":
                if type(command.get("event_id")) is not int:
                    raise ValueError("Missing decision")
                runs = self.server.simulation.read().get("runs", [])
                events = [e for r in runs if r["name"] == command["model"]
                          for e in r["decisions"][command["junction"]]]
                if not any(e["id"] == command["event_id"] for e in events):
                    raise ValueError("Decision no longer available")
        except (ValueError, TypeError):
            self.send_error(400)
            return
        try:
            self.server.simulation.commands.put_nowait(command)
        except Full:
            self.send_error(429)
            return
        self.send_data(b'{"ok":true}', "application/json")

    def send_data(self, data, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def log_message(self, format, *args):
        if args and str(args[1]) not in ("200", "304"):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="Balanced")
    parser.add_argument("--seed", type=int, default=201)
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--speed", type=float, default=4)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if (not math.isfinite(args.speed) or args.speed <= 0
            or (args.seconds is not None and args.seconds < 1) or not 0 <= args.port <= 65535):
        parser.error("Speed and duration must be positive; port must be in 0..65535")
    simulation = Simulation(args.scenario, args.seed, args.seconds, args.speed)
    server = DemoServer(("127.0.0.1", args.port), Handler)
    server.simulation = simulation
    server.geometry_data = json.dumps(geometry()).encode()
    simulation.thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"HIT Traffic Lab: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        simulation.stop.set()
        simulation.thread.join(timeout=30)
        server.server_close()


if __name__ == "__main__":
    main()
