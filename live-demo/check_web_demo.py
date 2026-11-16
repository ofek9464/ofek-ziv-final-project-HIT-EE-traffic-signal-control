"""Integration check against real SUMO, weights and the report's tripinfo metric."""
import argparse
import json
import tempfile
import time

from web_demo import Simulation, geometry, state_to_vector, torch, traci, config
from modules.metrics import MetricsCollector


def check_worker_recovery():
    simulation = Simulation(duration=60)

    def wait_for(predicate):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = simulation.read()
            if predicate(state):
                return state
            time.sleep(0.05)
        raise AssertionError("Simulation recovery timed out")

    simulation.thread.start()
    try:
        initial = wait_for(lambda state: state["status"] == "paused")

        def fail_step():
            raise RuntimeError("Injected simulation failure for recovery check")

        simulation.runs[0].step = fail_step
        simulation.commands.put({"action": "play"})
        wait_for(lambda state: state["status"] == "error")
        assert simulation.thread.is_alive()
        simulation.commands.put({"action": "restart"})
        wait_for(lambda state: state["status"] == "paused" and state["run_id"] > initial["run_id"])
        simulation.commands.put({"action": "play"})
        recovered = wait_for(lambda state: state["status"] == "running" and state["time"] >= 3)
        assert len(recovered["runs"]) == 4
        assert json.loads(simulation.read_bytes())["status"] == "running"
    finally:
        simulation.stop.set()
        simulation.thread.join(timeout=30)
        assert not simulation.thread.is_alive()
    print("PASS: simulation worker recovered after an injected failure")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=180)
    parser.add_argument("--scenario", default="Balanced")
    args = parser.parse_args()
    simulation = Simulation(scenario=args.scenario, duration=args.steps)
    torch.set_num_threads(1)
    report = {}
    with tempfile.TemporaryDirectory(prefix="hit-demo-check-") as folder:
        try:
            simulation.load(folder)
            for step in range(args.steps):
                for run in simulation.runs:
                    run.step()
                    for junction, events in run.events.items():
                        for event in events:
                            outcome = event["outcome"]
                            if outcome and outcome["time"] == step + 1:
                                assert outcome["time"] == event["time"] + event["applied"]
                                assert outcome["queues"] == run.queues[junction]
                    if not run.learned:
                        continue
                    for junction, events in run.events.items():
                        if not events or events[-1]["time"] != step + 1:
                            continue
                        event = events[-1]
                        vector = state_to_vector(event["state"])
                        assert len(vector) == 17 and vector.tolist() == event["vector"]
                        with torch.no_grad():
                            tensor = torch.tensor(vector).unsqueeze(0)
                            if run.name == "DQN":
                                expected = run.controller.q_net(tensor)[0].tolist()
                            else:
                                logits, critic = run.controller.net(tensor)
                                expected = logits.softmax(dim=-1)[0].tolist()
                                assert abs(event["critic"] - critic.item()) < 1e-6
                        assert expected == event["scores"]
                        assert event["selected"] == max(range(5), key=expected.__getitem__)
                        assert event["applied"] == run.remaining[junction]
                        assert event["override"] == (abs(event["chosen"] - event["applied"]) > 0.001)
            for run in simulation.runs:
                traci.switch(run.name)
                assert len(run.active) == traci.vehicle.getIDCount()
                assert run.persons == [traci.person.getPosition(person) for person in traci.person.getIDList()]
                assert all(light["state"] == traci.trafficlight.getRedYellowGreenState(junction)
                           for junction, light in run.lights.items())
                for junction, approaches in zip(config.CONTROLLED_JUNCTIONS,
                                                (config.J1_APPROACHES, config.J2_APPROACHES)):
                    assert run.queues[junction] == {
                        direction: traci.edge.getLastStepHaltingNumber(edge)
                        for direction, edge in approaches.items()
                    }
                assert sum(sum(queues.values()) for queues in run.queues.values()) == run.queued
                assert run.payload()["queues"] == run.queues
                traci.getConnection(run.name).close()
                final = MetricsCollector(run.name, run.demand).finalize(str(run.tripinfo), args.steps)
                assert final["throughput"] == run.completed_count
                waiting = run.completed_wait / run.completed_count if run.completed_count else 0
                assert abs(final["avg_waiting_time"] - waiting) < 1e-6
                report[run.name] = {"decisions": run.count, "completed": run.completed_count,
                                    "waiting": final["avg_waiting_time"], "overrides": run.override_count}
                if run.learned:
                    assert all(run.events[j] for j in run.events)
                    assert sum(sum(counts.values()) for counts in run.action_counts.values()) == run.count
                    assert any(event["outcome"] for events in run.events.values() for event in events)
            net = geometry()
            assert len(net["lanes"]) > 20 and len(net["signals"]) == 2
            print(json.dumps(report, indent=2))
            print("PASS: actual inputs, outputs, selected/applied actions and completed-trip waiting times")
        finally:
            simulation.close_runs()
    check_worker_recovery()


if __name__ == "__main__":
    main()
