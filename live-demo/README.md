# HIT Traffic live demonstration

A local browser demonstration of four independent SUMO runs under the same demand seed. TIMER, SCRIPT, DQN and A2C are shown together with completed-trip waiting time and a comparison graph.

## Windows setup

1. Extract the ZIP into a writable folder.
2. Install Python 3.11 or newer with `python` available on PATH.
3. Install [Eclipse SUMO](https://sumo.dlr.de/docs/Downloads.php). Make `sumo.exe` available on PATH or set `SUMO_HOME` to the installation folder. The launcher also detects the standard Windows installation folders.
4. Run `Setup-Demo.cmd` once. It downloads CPU PyTorch and the Python dependencies into `.venv`.
5. Run `Start-Web-Demo.cmd`. The browser opens at `http://127.0.0.1:8765/`.

The ZIP includes twelve trained checkpoint files, the network, and the twelve route and pedestrian files needed for test seed 201. The initial Python dependency installation requires Internet access. Simulation and inference run locally.

The Windows launcher supervises the server process. A server-process restart starts a new paused simulation. Closing the browser tab leaves the local server available for reopening.

## Presenting the project

Choose a scenario and start the demonstration. All four controllers run automatically. Select J1 or J2 and use the full-grid control when needed.

Use the model's decision-explanation button to pause the runs and inspect the actual seventeen inputs and network scores. Select a saved decision, then advance to the end of its applied green to compare directional queues. The measured change includes vehicle arrivals and departures. Closing the explanation resumes a previously running demonstration.

The live comparison uses completed trips at the current simulation time. Its result is provisional while the simulation runs. The model chooses a green duration from 20, 30, 40, 50 and 60 seconds. The phase sequence determines the direction, and the existing safety logic can constrain the applied duration.

## Model behavior

These are the checkpoints used by the verified local demonstration. In the tested Heavy west seed 201 rollout, DQN selected 20 seconds in all 84 decisions and A2C selected 30 seconds in all 62 decisions. The explanation view exposes real scores and observed action counts. See [the policy investigation](policy-diagnosis.md) for the direct-network tests and training limitations.

These checkpoint files are provided for inference and inspection. The package's hash inventory records the supplied runtime files. Historical training-machine provenance remains unresolved.

## Verification

After setup, run the following commands from this folder.

```powershell
.venv\Scripts\python.exe check_web_demo.py --scenario "Heavy west" --steps 180
.venv\Scripts\python.exe web_demo.py --port 8766 --scenario "Heavy west" --no-browser
```

The integration check compares actual model inputs and outputs, directional queues, end-of-green measurements and completed-trip waiting metrics against SUMO. It also injects a simulation failure and checks recovery. The expected injected-error traceback appears during that recovery check.

The main launcher uses port 8765. Choose an unused port for a separate command-line test. `demo-verification.json` and `heavy-west-soak-report.json` record the prior local checks. The archive is also tested after extraction before release.

## Runtime environment

The verified development environment used Python 3.11, CPU PyTorch 2.15.0, NumPy 2.4.4, Pillow 12.1.1 and SUMO Python tools 1.27.0. `requirements.txt` installs compatible current packages. The source repository's original historical environment remains documented in its root README.

## Patch notes

2026-11-16 â€” Added the packaged four-controller live demonstration with trained inference checkpoints, seed-201 demand, Windows setup and supervised launch scripts. Included saved decision explanations, end-of-green measurements, policy diagnosis and verification evidence.
