"""Run both trained policies in SUMO and display or record the comparison."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SIM = HERE / "sim"
sys.path.insert(0, str(SIM))

import sumolib
import traci
from controllers.ai_controller import ACTIONS, AiController
from controllers.a2c_controller import A2CController
from controllers.script_controller import ScriptController
from controllers.timer_controller import TimerController
from modules import config, data_collection

CONTROLLERS = (
    ("DQN", "#60d8ff", AiController),
    ("A2C", "#c5a2ff", A2CController),
    ("TIMER", "#ffcd80", TimerController),
    ("SCRIPT", "#78ecc1", ScriptController),
)
APPROACH_EDGES = tuple(config.J1_APPROACHES.values()) + tuple(config.J2_APPROACHES.values())

SCENARIOS = {
    "Heavy west": ("heavy_west", 0, 1200),
    "Balanced": ("balanced", 0, 1200),
    "Morning rush": ("morning_flow", 0, 1200),
    "Evening rush": ("evening_flow", 0, 1200),
    "Pedestrian heavy": ("pedestrian_heavy", 0, 1200),
    "Full day cycle": ("day_cycle", 0, 3600),
    "Night (day-cycle segment)": ("day_cycle", 2700, 900),
}
SIZE = (1280, 720)
BG, PANEL, INK, MUTED = "#0c111b", "#141e2e", "#eff5ff", "#a8b9cf"
network = sumolib.net.readNet(config.NET_FILE)
roads = [lane.getShape() for edge in network.getEdges() for lane in edge.getLanes()]
xmin, ymin, xmax, ymax = network.getBoundary()
font_dir = Path("C:/Windows/Fonts")
fonts = {
    (size, bold): ImageFont.truetype(str(font_dir / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)
    for size in (14, 16, 19, 24, 35) for bold in (False, True)
}


class Run:
    def __init__(self, name, color, controller_type, scenario):
        self.name, self.color = name, color
        self.demand, self.begin, _ = SCENARIOS[scenario]
        self.learned = name in ("DQN", "A2C")
        if self.learned:
            path = SIM / "models" / f"{name.lower()}_{self.demand}_ms_weights.pt"
            if not path.is_file():
                raise FileNotFoundError(path)
            self.controller = controller_type(config.CONTROLLED_JUNCTIONS, weights_path=str(path))
            model = self.controller.q_net if name == "DQN" else self.controller.net
            model.register_forward_hook(self.capture)
        else:
            self.controller = controller_type(config.CONTROLLED_JUNCTIONS)
        self.decisions = {}
        self.count = 0
        self.override_count = 0
        self.arrived = 0
        self.vehicles = []
        self.phases = {}
        self.green = {}
        self.remaining = {}
        self.queue_total = 0
        self.queue_samples = 0
        self.ped_wait_total = 0
        self.ped_wait_samples = 0
        self.vehicle_wait = None

    def start(self, window=None):
        folder = SIM / "scenarios"
        route = folder / f"{self.demand}.rou.xml"
        if not route.is_file():
            raise FileNotFoundError(route)
        routes = [route, folder / f"{self.demand}.ped.xml"]
        gui_args = []
        if window:
            width, height, left, top = window
            gui_args = ["--start", "--window-size", f"{width},{height}",
                        "--window-pos", f"{left},{top}"]
        command = [sumolib.checkBinary("sumo-gui" if window else "sumo"), "-n", config.NET_FILE,
             "-r", ",".join(str(p) for p in routes if p.exists()), "--seed", "42",
             "--begin", str(self.begin),
             "--no-step-log", "--no-warnings", *gui_args]
        if window:
            traci.start(command, label=self.name, stdout=subprocess.DEVNULL)
            return
        port = sumolib.miscutils.getFreeSocketPort()
        process = subprocess.Popen(command + ["--remote-port", str(port)],
                                   stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            traci.init(port, label=self.name, proc=process)
        except BaseException:
            process.terminate()
            process.wait()
            raise

    def capture(self, model, inputs, output):
        vector = inputs[0][0].tolist()
        if self.name == "DQN":
            self.outputs.append((vector, output[0].tolist(), None))
        else:
            logits, value = output
            self.outputs.append((vector, logits.softmax(dim=-1)[0].tolist(), value.item()))

    def step(self):
        traci.switch(self.name)
        traci.simulationStep()
        t = traci.simulation.getTime()
        phases = {j: traci.trafficlight.getPhase(j) for j in config.CONTROLLED_JUNCTIONS}
        due = [j for j, p in phases.items() if p in (0, 3) and p != self.phases.get(j)]
        self.outputs = []
        self.controller.step(t - self.begin)
        if self.learned:
            assert len(due) == len(self.outputs)
        self.arrived += traci.simulation.getArrivedNumber()
        for j, (vector, values, critic) in zip(due, self.outputs):
            selected = max(range(len(values)), key=values.__getitem__)
            applied = traci.trafficlight.getNextSwitch(j) - t
            self.decisions[j] = (t - self.begin, phases[j], vector, values, critic, selected, applied)
            self.count += 1
            self.override_count += applied != ACTIONS[selected]
        self.phases = phases
        self.remaining = {j: max(0, traci.trafficlight.getNextSwitch(j) - t) for j in phases}
        for j in due:
            self.green[j] = traci.trafficlight.getPhaseDuration(j) if self.name == "TIMER" else self.remaining[j]

    def sample_metrics(self):
        traci.switch(self.name)
        self.queue_total += sum(traci.edge.getLastStepHaltingNumber(edge) for edge in APPROACH_EDGES)
        self.queue_samples += 1
        vehicles = sum(traci.edge.getLastStepVehicleNumber(edge) for edge in APPROACH_EDGES)
        self.vehicle_wait = (sum(traci.edge.getWaitingTime(edge) for edge in APPROACH_EDGES) / vehicles
                             if vehicles else None)
        persons = traci.person.getIDList()
        waits = [data_collection.pedestrian_waiting_at_junction(j, persons)[1]
                 for j in config.CONTROLLED_JUNCTIONS]
        waits = [wait for wait in waits if wait > 0]
        if waits:
            self.ped_wait_total += sum(waits) / len(waits)
            self.ped_wait_samples += 1

    def snapshot(self):
        traci.switch(self.name)
        self.vehicles = [
            (*traci.vehicle.getPosition(v), traci.vehicle.getSpeed(v))
            for v in traci.vehicle.getIDList()
        ]
        self.phases = {j: traci.trafficlight.getPhase(j) for j in config.CONTROLLED_JUNCTIONS}


def frame(runs, t, status, scenario):
    image = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(image)

    def label(x, y, value, size=16, color=INK, bold=False):
        d.text((x, y), str(value), fill=color, font=fonts[size, bold])

    label(30, 18, "Traffic signal control", 35, bold=True)
    label(31, 65, f"SUMO  /  {scenario}  /  Trained policies  /  Seed 42", color=MUTED)
    label(976, 31, f"{status}    t = {t:03d} s", 24, "#78ecc1", True)

    for index, run in enumerate(runs):
        x = 30 + index * 620
        d.rounded_rectangle((x, 104, x + 598, 669), radius=16, fill=PANEL)
        label(x + 20, 116, run.name, 24, run.color, True)
        label(x + 180, 124, f"{len(run.vehicles)} active     {run.arrived} arrived     {run.count} decisions", color=MUTED)

        d.rounded_rectangle((x + 14, 157, x + 584, 388), radius=10, fill=BG)
        scale = min(510 / (xmax - xmin), 173 / (ymax - ymin))

        def project(px, py):
            return (x + 299 + (px - (xmin + xmax) / 2) * scale,
                    272 - (py - (ymin + ymax) / 2) * scale)

        for lane in roads:
            d.line([project(*pt) for pt in lane], fill="#33435a", width=6)
        for px, py, speed in run.vehicles:
            sx, sy = project(px, py)
            d.ellipse((sx - 2, sy - 2, sx + 2, sy + 2), fill=run.color if speed > 0.1 else "#ffab78")
        for i, (j, p) in enumerate(run.phases.items(), 1):
            sx, sy = project(*network.getNode(j).getCoord())
            signal = "#78ecc1" if p in (0, 3) else "#ffab78"
            d.ellipse((sx - 5, sy - 5, sx + 5, sy + 5), fill=signal, outline=BG)
            phase_name = {0: "N/S green", 3: "E/W green"}.get(p, "Transition")
            label(x + 33 + (i - 1) * 277, 365, f"J{i}  {phase_name}", 14, signal, True)

        for i, j in enumerate(config.CONTROLLED_JUNCTIONS):
            sx = x + 22 + i * 290
            label(sx, 399, f"J{i + 1}  /  Last decision", 19, bold=True)
            if j not in run.decisions:
                continue
            when, phase, vec, scores, critic, selected, applied = run.decisions[j]
            axis = "north–south" if phase == 0 else "east–west"
            changed = applied != ACTIONS[selected]
            choice = ACTIONS[selected]
            label(sx, 425, f"{choice}s green for {axis}", 19, run.color, True)
            rank = "Highest Q-value" if critic is None else f"Top choice ({scores[selected]:.0%})"
            label(sx, 450, f"{rank}  /  at {when:.0f}s", 14, MUTED)
            queues = "   ".join(f"{direction} {round(value * 20)}" for direction, value in zip("NSEW", vec[:4]))
            label(sx, 473, f"Observed queue   {queues}", 14, INK)
            applied_text = f"Safety changed green to {applied:g}s" if changed else f"SUMO applied {applied:g}s"
            label(sx, 494, applied_text, 14, "#ffab78" if changed else "#78ecc1", True)
            score_label = "Q-value by duration" if critic is None else "Probability by duration"
            label(sx, 517, score_label, 14, MUTED)
            for row, (seconds, value) in enumerate(zip(ACTIONS, scores)):
                yy = 538 + row * 19
                if row == selected:
                    d.rounded_rectangle((sx - 5, yy - 2, sx + 250, yy + 20), radius=5, fill="#26394d")
                color = run.color if row == selected else INK
                label(sx, yy, f"{seconds}s", 14, color, row == selected)
                label(sx + 64, yy, f"{value:.2f}" if critic is None else f"{value:.1%}", 14, color, row == selected)
                if row == selected:
                    label(sx + 161, yy, "SELECTED", 14, run.color, True)
        label(x + 22, 640, f"Safety adjustments   {run.override_count}", 14, "#ffab78")

    label(31, 684, "Ofek & Ziv  /  HIT", 14, MUTED)
    label(435, 684, "Orange vehicles are stopped   /   Space pauses live view", 14, MUTED)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, help="Write a 30 fps MP4 instead of opening a live window")
    parser.add_argument("--sumo-gui", action="store_true", help="Open two native SUMO windows")
    parser.add_argument("--embed-sumo", action="store_true", help="Embed both native SUMO views in one Windows window")
    parser.add_argument("--seconds", type=int, help="Limit elapsed simulated time")
    parser.add_argument("--scenario", choices=SCENARIOS, default="Heavy west")
    parser.add_argument("--speed", type=float, default=8, help="Simulation seconds per wall-clock second")
    args = parser.parse_args()
    if (args.seconds is not None and args.seconds < 1) or args.speed <= 0:
        parser.error("Both --seconds and --speed must be positive")
    if args.record and (args.sumo_gui or args.embed_sumo):
        parser.error("Choose --record or a live SUMO view")
    scenario = args.scenario
    runs = []
    started = []
    gui_runs = set()
    window = None
    hosts = []
    embedded = []

    def duration():
        return args.seconds or SCENARIOS[scenario][2]

    def close_runs():
        while embedded:
            embedded.pop()()
        while started:
            name = started.pop()
            try:
                connection = traci.getConnection(name)
                if name in gui_runs:
                    # SUMO GUI keeps its window open after TraCI disconnects.
                    process = connection._process
                    connection.close(wait=False)
                    if process.poll() is None:
                        process.terminate()
                    process.wait()
                else:
                    connection.close()
            except (traci.FatalTraCIError, OSError):
                pass
            finally:
                if name in gui_runs:
                    gui_runs.remove(name)

    def load_runs(selection):
        nonlocal scenario, runs
        candidates = [Run(*controller, selection)
                      for controller in (CONTROLLERS if args.embed_sumo else CONTROLLERS[:2])]
        close_runs()
        embedded.clear()
        for index, run in enumerate(candidates):
            placement = None
            if window and index < 2:
                placement = (*window, 0 if hosts else index * window[0], -1600 if hosts else 0)
            run.start(placement)
            started.append(run.name)
            if placement:
                gui_runs.add(run.name)
            if hosts and placement:
                from native_view import embed

                embedded.append(embed(hosts[index], traci.getConnection(run.name)._process))
        runs = candidates
        scenario = selection

    def advance():
        for run in runs:
            run.step()

    def render(t, status):
        for run in runs:
            run.snapshot()
        return frame(runs, t, status, scenario)

    try:
        if not args.record:
            import tkinter as tk
            from tkinter import messagebox, ttk
            from PIL import ImageTk

            root = tk.Tk()
            root.withdraw()
            if args.sumo_gui or args.embed_sumo:
                width = root.winfo_screenwidth() // 2
                height = int(root.winfo_screenheight() * 0.63)
                window = (width, height)
        if args.record:
            load_runs(scenario)
        if args.record:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise FileNotFoundError("ffmpeg is required for --record")
            with subprocess.Popen(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
                 "-pixel_format", "rgb24", "-video_size", "1280x720", "-framerate", "30",
                 "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 str(args.record)],
                stdin=subprocess.PIPE,
            ) as encoder:
                frames = 0
                for t in range(1, duration() + 1):
                    advance()
                    target = round(t * 30 / args.speed)
                    if target > frames:
                        pixels = render(t, "SUMO RUN").tobytes()
                        for _ in range(target - frames):
                            encoder.stdin.write(pixels)
                        frames = target
                encoder.stdin.close()
                if encoder.wait() != 0:
                    raise RuntimeError("FFmpeg could not encode the demo")
            assert all(run.count >= 2 for run in runs)
            print({run.name: {"decisions": run.count, "adjustments": run.override_count} for run in runs})
        else:
            root.title("Traffic decisions | HIT Traffic Lab")
            root.configure(bg=BG)
            if args.embed_sumo:
                root.geometry(f"{min(1920, window[0] * 2 - 32)}x{int(root.winfo_screenheight() * 0.87)}+10+10")
                root.minsize(960, 620)
            elif window:
                root.geometry(f"+0+{window[1]}")
            t = 0
            paused = args.sumo_gui
            controls = tk.Frame(root, bg=PANEL, padx=16, pady=13)
            controls.pack(fill="x")
            tk.Label(controls, text="HIT Traffic Lab", bg=PANEL, fg=INK,
                     font=("Segoe UI", 17, "bold")).pack(side="left", padx=(0, 28))
            tk.Label(controls, text="Traffic scenario", bg=PANEL, fg=INK,
                     font=("Segoe UI", 12, "bold")).pack(side="left", padx=8)
            selector = ttk.Combobox(controls, values=list(SCENARIOS), state="readonly", width=25,
                                    font=("Segoe UI", 12))
            selector.set(scenario)
            selector.pack(side="left", padx=5)
            cards = []
            if args.embed_sumo:
                comparison = tk.Frame(root, bg=BG, padx=12, pady=8)
                comparison.pack(fill="x")
                tk.Label(comparison, bg=BG, fg=MUTED, anchor="w",
                         text="RUNNING COMPARISON   ·   J1/J2 traffic sampled every 5 simulation seconds",
                         font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=4, sticky="ew", padx=3)
                for index, (name, color, _) in enumerate(CONTROLLERS):
                    comparison.grid_columnconfigure(index, weight=1, uniform="controller")
                    card = tk.Frame(comparison, bg=PANEL, padx=10, pady=7)
                    card.grid(row=1, column=index, padx=3, pady=(5, 0), sticky="nsew")
                    tk.Label(card, text=name, bg=PANEL, fg=color, anchor="w",
                             font=("Segoe UI", 13, "bold")).pack(fill="x")
                    choice = tk.Label(card, bg=PANEL, fg=INK, anchor="w", justify="left",
                                      font=("Segoe UI", 11, "bold"))
                    choice.pack(fill="x")
                    metrics = tk.Label(card, bg=PANEL, fg=MUTED, anchor="w", justify="left",
                                       font=("Segoe UI", 10))
                    metrics.pack(fill="x", pady=(5, 0))
                    cards.append((choice, metrics))
                maps = tk.Frame(root, bg=BG, padx=12, pady=8)
                maps.pack(fill="both", expand=True)
                maps.grid_rowconfigure(1, weight=1)
                for index, (model, color) in enumerate((("DQN", "#60d8ff"), ("A2C", "#c5a2ff"))):
                    tk.Label(maps, text=model, bg=BG, fg=color, font=("Segoe UI", 15, "bold")).grid(
                        row=0, column=index, padx=6, sticky="w")
                    host = tk.Frame(maps, bg=BG)
                    host.grid(row=1, column=index, padx=2, sticky="nsew")
                    maps.grid_columnconfigure(index, weight=1, uniform="sumo")
                    hosts.append(host)
            display = tk.Label(root, borderwidth=0, bg=BG)
            if not args.embed_sumo:
                display.pack(fill="x")

            def update_comparison():
                for run, (choice, metrics) in zip(runs, cards):
                    lines = []
                    for index, junction in enumerate(config.CONTROLLED_JUNCTIONS, 1):
                        phase = run.phases.get(junction)
                        if phase is None:
                            lines.append(f"J{index}  Waiting for first step")
                            continue
                        direction = {0: "N/S", 3: "E/W"}.get(phase)
                        remaining = run.remaining[junction]
                        if direction is None:
                            lines.append(f"J{index}  Transition · {remaining:g}s left")
                            continue
                        applied = run.green.get(junction, remaining)
                        decision = run.decisions.get(junction)
                        chosen = ACTIONS[decision[5]] if decision else applied
                        verb = "chose" if run.learned else ("fixed" if run.name == "TIMER" else "rule")
                        applied_note = f" → {applied:g}s" if chosen != applied else ""
                        lines.append(f"J{index}  {direction} · {verb} {chosen:g}s{applied_note} · {remaining:g}s left")
                    choice.configure(text="\n".join(lines))
                    queue = f"{run.queue_total / run.queue_samples:.1f}" if run.queue_samples else "—"
                    ped = f"{run.ped_wait_total / run.ped_wait_samples:.1f}s" if run.ped_wait_samples else "—"
                    wait = f"{run.vehicle_wait:.1f}s" if run.vehicle_wait is not None else "—"
                    metrics.configure(text=f"Avg queue  {queue} vehicles\nCurrent vehicle wait / vehicle  {wait}\n"
                                           f"Avg pedestrian wait  {ped}\n"
                                           f"Completed trips  {run.arrived}")

            def toggle(_event=None):
                nonlocal paused
                paused = not paused
                button.configure(text="Start / Resume" if paused else "Pause")

            button = tk.Button(controls, text="Start / Resume" if paused else "Pause",
                               command=toggle, bg="#78ecc1", fg=BG, padx=16,
                               font=("Segoe UI", 11, "bold"))
            button.pack(side="left", padx=12)
            status_text = tk.Label(controls, bg=PANEL, fg="#78ecc1", font=("Segoe UI", 12, "bold"))
            status_text.pack(side="right", padx=8)

            def select(_event=None):
                nonlocal t, paused
                status_text.configure(text="Loading scenario…")
                root.update_idletasks()
                try:
                    load_runs(selector.get())
                except Exception as error:
                    messagebox.showerror("Could not load scenario", str(error), parent=root)
                    root.quit()
                    return
                t = 0
                paused = args.sumo_gui
                button.configure(text="Start / Resume" if paused else "Pause")
                button.focus_set()

            selector.bind("<<ComboboxSelected>>", select)

            def tick():
                nonlocal t
                try:
                    if not paused and t < duration():
                        advance()
                        t += 1
                        if cards and (t == 1 or t % 5 == 0):
                            for run in runs:
                                run.sample_metrics()
                    status = "COMPLETE" if t == duration() else ("PAUSED" if paused else "LIVE")
                    status_text.configure(text=f"{status}   ·   {t} s")
                    if cards:
                        update_comparison()
                        root.after(round(1000 / args.speed), tick)
                        return
                    picture = frame(runs, t, status, scenario) if t == 0 else render(t, status)
                    if window:
                        panel = Image.new("RGB", (SIZE[0], 310), BG)
                        panel.paste(picture.crop((0, 390, SIZE[0], 669)), (0, 31))
                        draw = ImageDraw.Draw(panel)
                        for index, run in enumerate(runs):
                            draw.text((52 + 620 * index, 5), run.name, fill=run.color, font=fonts[19, True])
                        draw.text((460, 5), f"{status}    t = {t:03d} s", fill=INK, font=fonts[19, True])
                        picture = panel
                        picture.thumbnail((window[0] * 2, max(170, root.winfo_screenheight() - window[1] - 108)),
                                          Image.Resampling.LANCZOS)
                    display.image = ImageTk.PhotoImage(picture)
                    display.configure(image=display.image)
                    root.after(round(1000 / args.speed), tick)
                except Exception:
                    root.quit()
                    raise

            root.deiconify()
            root.update_idletasks()
            load_runs(scenario)
            root.bind("<space>", toggle)
            root.protocol("WM_DELETE_WINDOW", root.quit)
            root.after(0, tick)
            root.mainloop()
    finally:
        close_runs()


if __name__ == "__main__":
    main()

