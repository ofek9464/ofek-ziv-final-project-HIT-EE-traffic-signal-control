"""Extract the displayed result cells from the report, without simulation imports."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
SCENARIOS = ["מאוזן", "עומס ממערב", "ריבוי הולכי רגל", "בוקר", "ערב", "מחזור יום"]


def extract(report, network, recorded):
    with ZipFile(report) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    tables = []
    caption = ""
    for table in root.find("w:body", NS):
        if not table.tag.endswith("}tbl"):
            text = "".join(t.text or "" for t in table.findall(".//w:t", NS))
            if text.strip():
                caption = text
            continue
        tables.append((caption, [
            ["".join(t.text or "" for t in cell.findall(".//w:t", NS))
             for cell in row.findall("w:tc", NS)]
            for row in table.findall("w:tr", NS)
        ]))
    specifications = [
        ("later", ["תרחיש", "TIMER", "SCRIPT", "משך קבוע מכויל", "DQN", "A2C"],
         "השוואת תצורות · 4.8.1", "טבלה 24 · זרמי בדיקה 701–720 · שלושה אימונים לכל תצורה"),
        ("original", ["תרחיש", "TIMER", "SCRIPT", "DQN", "A2C"],
         "השוואה ראשונית · 4.1", "טבלה 12 · זרמי בדיקה 201–205 · ממוצע וסטיית תקן בין הזרמים"),
    ]
    experiments = []
    for key, header, label, source in specifications:
        table_number = 24 if key == "later" else 12
        matches = [table for caption, table in tables if caption.startswith(f"טבלה {table_number}:")
                   and table[0] == header and len(table) == 7
                   and [r[0] for r in table[1:]] == SCENARIOS]
        assert len(matches) == 1, f"Expected one result table for {key}"
        scenarios = []
        for row in matches[0][1:]:
            results = {}
            for model in ["TIMER", "SCRIPT", "DQN", "A2C"]:
                cell = row[header.index(model)]
                assert re.fullmatch(r"\d+\.\d+( ± \d+\.\d+)?", cell), cell
                results[model] = {"display": cell, "mean": float(cell.split()[0])}
            scenarios.append({"label": row[0], "results": results})
        experiments.append({"id": key, "label": label, "source": source, "scenarios": scenarios})
    net = ET.parse(network).getroot()
    lanes = []
    for edge in net.findall("edge"):
        for lane in edge.findall("lane"):
            if lane.get("allow") in ("pedestrian", "bicycle pedestrian"):
                continue
            shape = [[float(v) for v in point.split(",")] for point in lane.get("shape").split()]
            lanes.append({"shape": shape, "width": float(lane.get("width", "3.2")),
                          "internal": edge.get("function") == "internal"})
    junctions = {j.get("id"): [float(j.get("x")), float(j.get("y"))]
                 for j in net.findall("junction") if j.get("id") in ("B1", "C1")}
    recording = json.loads(Path(recorded).read_text(encoding="utf-8-sig"))
    decisions = {}
    for run in recording["before"]["runs"]:
        if run["name"] in ("DQN", "A2C"):
            decisions[run["name"]] = run["decisions"]["B1"][-1]
    return {"report": Path(report).name,
            "report_sha256": hashlib.sha256(Path(report).read_bytes()).hexdigest(),
            "experiments": experiments, "geometry": {"lanes": lanes, "junctions": junctions},
            "recorded_decisions": decisions,
            "recording_source": "Heavy west · s201 · J1 · archived local SUMO run"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("network", type=Path)
    parser.add_argument("--recorded", type=Path, default=HERE / "a2c-heavy-decision-outcome.json")
    args = parser.parse_args()
    data = extract(args.report, args.network, args.recorded)
    (HERE / "presentation-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Extracted 48 report cells, road geometry and two archived decisions.")
