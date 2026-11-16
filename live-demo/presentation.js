"use strict";

const order = ["DQN", "A2C", "TIMER", "SCRIPT"];
const scenarioSelect = document.getElementById("scenario");
const experimentSelect = document.getElementById("experiment");
const play = document.getElementById("play");
const dialog = document.getElementById("decision-dialog");
const cards = {};
const controllerNames = ["TIMER", "SCRIPT", "DQN", "A2C"];
const number = (value, decimals = 1) => value == null ? "—" : Number(value).toFixed(decimals);
const clock = value => `${Math.floor(value / 60).toString().padStart(2, "0")}:${Math.floor(value % 60).toString().padStart(2, "0")}`;
const recordingCache = new Map();
let recording;
let geometry;
let fullGrid = false;
let expandedModel = null;
let renderedSecond = -1;
let data;
let elapsed = 0;
let playing = false;
let resumeAfterDialog = false;
let lastFrame = performance.now();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

function currentExperiment() {
  return data.experiments.find(item => item.id === experimentSelect.value);
}

function currentScenario() {
  return currentExperiment().scenarios[Number(scenarioSelect.value)];
}

function updateStatus() {
  const complete = elapsed >= 600;
  document.getElementById("time").textContent = clock(elapsed);
  play.textContent = playing ? "השהה הצגה" : complete ? "הצג שוב" : elapsed ? "המשך הצגה" : "התחל הצגה";
  document.getElementById("status").textContent = complete ? "ההצגה הסתיימה" : playing ? "הרצה מוקלטת" : "מוכן להצגה";
}

function reset() {
  elapsed = 0;
  renderedSecond = -1;
  document.getElementById("seek").value = 0;
  updateStatus();
  renderComparison();
  drawAll();
}

function frameIndex() {
  return Math.min(recording.frames.length - 1, Math.floor(elapsed));
}

function currentFrame() {
  return recording?.frames[frameIndex()];
}

function playbackSnapshot() {
  if (!recording) return null;
  const current = currentFrame();
  return {time: elapsed, runs: current.runs, history: recording.frames.slice(0, frameIndex() + 1)
    .filter(item => item.time % 5 === 0).map(item => ({time: item.time,
      waiting: Object.fromEntries(item.runs.map(run => [run.name, run.waiting]))}))};
}

function renderComparison() {
  if (!recording) return;
  const experiment = currentExperiment();
  const scenario = currentScenario();
  const current = currentFrame();
  document.getElementById("comparison-rows").innerHTML = controllerNames.map(name => {
    const run = current.runs.find(item => item.name === name);
    return `<tr><td><span class="controller-name ${name.toLowerCase()}">${name}</span></td><td>${number(run.waiting)}</td><td>${run.queued}</td><td>${run.completed}</td><td><bdi>${scenario.results[name].display}</bdi></td></tr>`;
  }).join("");
  document.getElementById("comparison-scenario").textContent = `${scenario.label} · ${experiment.source}`;
  document.getElementById("metric-note").textContent = "כעת — נסיעות שהושלמו ב־10 הדקות הראשונות בהקלטת s201. בספר — תוצאות הניסוי המלא והמצרפי שנבחר, כולל ± כפי שפורסם.";
  const junction = document.getElementById("junction").value;
  const labels = {west: "מערב", east: "מזרח", north: "צפון", south: "דרום"};
  for (const run of current.runs) {
    const article = cards[run.name].article;
    article.querySelector("[data-expand]").disabled = false;
    const event = run.decisions[junction]?.at(-1);
    const light = run.lights[junction];
    const phase = light?.phase === 3 ? "מזרח–מערב" : light?.phase === 0 ? "צפון–דרום" : "מעבר פאזה";
    article.querySelector(".map-time").textContent = `${clock(elapsed)} · ${phase} · ${number(light?.remaining, 0)}s`;
    article.querySelector(".current-input").textContent = event
      ? `קלט ${clock(event.time)} · ${Object.entries(labels).map(([key, label]) => `${label} ${event.state.approaches[key].queue_length}`).join(" · ")}`
      : `תור בצומת · ${Object.entries(labels).map(([key, label]) => `${label} ${run.queues[junction]?.[key] ?? 0}`).join(" · ")}`;
    article.querySelector(".method").textContent = event
      ? `בחר ${event.chosen}s לירוק ${event.phase === 3 ? "מזרח–מערב" : "צפון–דרום"}${event.override ? ` · בטיחות ${event.applied}s` : ""}`
      : `${run.name === "TIMER" ? "מחזור קבוע" : run.name === "SCRIPT" ? "כללי Python" : "ממתין להחלטה הראשונה"} · ${phase}`;
    const before = event ? Object.values(event.state.approaches).reduce((total, row) => total + row.queue_length, 0) : null;
    const queue = Object.values(run.queues[junction] || {}).reduce((a, b) => a + b, 0);
    article.querySelector(".current-result").textContent = event ? `התור בקלט ${before} ← כעת ${queue} · השינוי כולל הגעות ועזיבות` : `${queue} ממתינים בצומת הנבחר`;
    const button = article.querySelector("[data-decision]");
    if (button) button.disabled = !event;
  }
  renderedSecond = Math.floor(elapsed);
  drawChart();
}

async function loadRecording() {
  playing = false;
  recording = null;
  document.getElementById("status").textContent = "טוען הרצה מוקלטת";
  document.getElementById("comparison-rows").replaceChildren();
  document.getElementById("comparison-scenario").textContent = currentScenario().label;
  for (const card of Object.values(cards)) {
    card.article.querySelector("[data-expand]").disabled = true;
    card.canvas.getContext("2d").clearRect(0, 0, card.canvas.width, card.canvas.height);
    card.article.querySelector(".current-input").textContent = "טוען הקלטה…";
    card.article.querySelector(".method").textContent = "";
    card.article.querySelector(".current-result").textContent = "";
    card.article.querySelector(".map-time").textContent = "";
    const button = card.article.querySelector("[data-decision]");
    if (button) button.disabled = true;
  }
  const chart = document.getElementById("comparison-chart");
  chart.getContext("2d").clearRect(0, 0, chart.width, chart.height);
  for (const item of [play, scenarioSelect, document.getElementById("seek"), document.getElementById("restart")]) item.disabled = true;
  const key = scenarioSelect.value;
  try {
    if (!recordingCache.has(key)) {
      const response = await fetch(`/recordings/scenario-${key}.json.gz`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const loaded = await response.json();
      if (loaded.duration !== 600 || loaded.frames.length !== 601) throw new Error("Incomplete recording");
      recordingCache.clear();
      recordingCache.set(key, loaded);
    }
    recording = recordingCache.get(key);
    reset();
    for (const item of [play, scenarioSelect, document.getElementById("seek"), document.getElementById("restart")]) item.disabled = false;
  } catch (error) {
    document.getElementById("status").textContent = "טעינת ההקלטה נכשלה";
    document.getElementById("presentation-guide").textContent = `בחרו שוב תרחיש כדי לנסות לטעון. ${error.message}`;
    scenarioSelect.disabled = false;
  }
}

function drawChart() {
  const snapshot = playbackSnapshot();
  if (!snapshot) return;
  const canvas = document.getElementById("comparison-chart");
  const ctx = canvas.getContext("2d");
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const history = [...(snapshot.history || [])];
  if (snapshot.time > 0 && history[history.length - 1]?.time !== snapshot.time) {
    history.push({time: snapshot.time, waiting: Object.fromEntries(snapshot.runs.map(run => [run.name, run.waiting]))});
  }
  const values = history.flatMap(point => Object.values(point.waiting)).filter(value => value !== null);
  const maxY = Math.max(10, Math.ceil(Math.max(0, ...values) / 10) * 10);
  const maxX = 600;
  const left = 35, right = w - 10, top = 20, bottom = h - 30;
  const x = time => left + time / maxX * (right - left);
  const y = value => bottom - value / maxY * (bottom - top);
  ctx.font = "11px Segoe UI";
  for (let i = 0; i <= 2; i++) {
    const value = maxY * i / 2;
    ctx.strokeStyle = "#d8dfd8";
    ctx.beginPath(); ctx.moveTo(left, y(value)); ctx.lineTo(right, y(value)); ctx.stroke();
    ctx.fillStyle = "#58675d"; ctx.textAlign = "right"; ctx.fillText(number(value, 0), left - 8, y(value) + 4);
    const time = maxX * i / 2;
    ctx.textAlign = i === 0 ? "left" : i === 2 ? "right" : "center";
    ctx.fillText(clock(time), x(time), h - 9);
  }
  ctx.textAlign = "left"; ctx.fillText("שניות", left, 10);
  const colors = {TIMER: "#627182", SCRIPT: "#b17928", DQN: "#14765d", A2C: "#705499"};
  for (const name of controllerNames) {
    ctx.strokeStyle = colors[name]; ctx.fillStyle = colors[name]; ctx.lineWidth = 2;
    ctx.setLineDash(name === "A2C" ? [5, 4] : name === "TIMER" ? [2, 3] : []);
    ctx.beginPath();
    let started = false;
    let last;
    for (const point of history) {
      const value = point.waiting[name];
      if (value === null || value === undefined) { started = false; continue; }
      if (started) ctx.lineTo(x(point.time), y(value));
      else ctx.moveTo(x(point.time), y(value));
      started = true;
      last = [x(point.time), y(value)];
    }
    ctx.stroke(); ctx.setLineDash([]);
    if (last) { ctx.beginPath(); ctx.arc(last[0], last[1], 2.5, 0, Math.PI * 2); ctx.fill(); }
  }
  if (!values.length) {
    ctx.textAlign = "center"; ctx.fillStyle = "#58675d";
    ctx.fillText("הגרף יתעדכן כשהנסיעות הראשונות יושלמו", (left + right) / 2, h / 2);
  }
}

function drawRecordedMap(canvas, run, showFullGrid = fullGrid) {
  const ctx = canvas.getContext("2d");
  const w = canvas.clientWidth, h = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  const junction = document.getElementById("junction").value;
  const center = geometry.junctions[junction];
  const bounds = showFullGrid ? geometry.bounds : [center[0] - 65, center[1] - 17.5, center[0] + 65, center[1] + 17.5];
  const horizontalScale = (w - 24) / (bounds[2] - bounds[0]);
  const verticalScale = (h - 24) / (bounds[3] - bounds[1]);
  const scale = Math.min(horizontalScale, verticalScale);
  const project = point => [w / 2 + (point[0] - (bounds[0] + bounds[2]) / 2) * scale, h / 2 - (point[1] - (bounds[1] + bounds[3]) / 2) * scale];
  ctx.lineCap = "butt";
  ctx.lineJoin = "round";
  for (const lane of geometry.lanes) {
    if (!lane.shape.length) continue;
    ctx.strokeStyle = lane.pedestrian ? "#b4c0b5" : "#171d1b";
    ctx.lineWidth = Math.max(showFullGrid ? 1 : 2, lane.width * scale);
    ctx.beginPath();
    lane.shape.forEach((point, i) => {
      const [x, y] = project(point);
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.stroke();
  }
  for (const [id, signals] of Object.entries(geometry.signals)) {
    const state = run.lights[id]?.state;
    if (!state) continue;
    for (const signal of signals) {
      const shape = signal.shape;
      if (shape.length < 2) continue;
      const end = project(shape[shape.length - 1]), prev = project(shape[shape.length - 2]);
      const dx = end[0] - prev[0], dy = end[1] - prev[1], length = Math.hypot(dx, dy) || 1;
      const radius = Math.max(2, 1.3 * scale);
      const lamp = state[signal.index];
      ctx.strokeStyle = "gG".includes(lamp) ? "#2aad7b" : "yY".includes(lamp) ? "#efb744" : "#e96855";
      ctx.lineWidth = showFullGrid ? 2 : 3;
      ctx.beginPath();
      ctx.moveTo(end[0] - dy / length * radius, end[1] + dx / length * radius);
      ctx.lineTo(end[0] + dy / length * radius, end[1] - dx / length * radius);
      ctx.stroke();
    }
  }
  for (const vehicle of run.vehicles) {
    const [x, y] = project(vehicle.position);
    if (x < -10 || x > w + 10 || y < -10 || y > h + 10) continue;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(vehicle.angle * Math.PI / 180);
    ctx.fillStyle = vehicle.speed <= 0.1 ? "#e4a232" : "#48b7a0";
    ctx.fillRect(-Math.max(1.5, scale), -Math.max(3.5, 2.5 * scale), Math.max(3, scale * 2), Math.max(7, scale * 5));
    ctx.restore();
  }
  ctx.fillStyle = "#8564ad";
  for (const person of run.pedestrians) {
    const [x, y] = project(person);
    ctx.beginPath();
    ctx.arc(x, y, Math.max(1.5, scale * .7), 0, 2 * Math.PI);
    ctx.fill();
  }
  for (const [id, point] of Object.entries(geometry.junctions)) {
    const [x, y] = project(point);
    ctx.fillStyle = id === junction ? "#172720" : "#fff";
    ctx.fillRect(x - 13, y - 10, 26, 20);
    ctx.fillStyle = id === junction ? "#fff" : "#172720";
    ctx.font = "600 12px Arial";
    ctx.textAlign = "center";
    ctx.fillText(id === "B1" ? "J1" : "J2", x, y + 4);
  }
}

function drawMap(name) {
  const run = currentFrame()?.runs.find(item => item.name === name);
  if (!run) return;
  const next = recording.frames[Math.min(recording.frames.length - 1, frameIndex() + 1)].runs.find(item => item.name === name);
  const nextVehicles = new Map(next.vehicles.map(vehicle => [vehicle.id, vehicle]));
  const fraction = reducedMotion.matches ? 0 : elapsed - Math.floor(elapsed);
  const vehicles = run.vehicles.map(vehicle => {
    const target = nextVehicles.get(vehicle.id);
    if (!target) return vehicle;
    return {...vehicle, position: vehicle.position.map((value, index) => value + (target.position[index] - value) * fraction)};
  });
  const rendered = {...run, vehicles};
  drawRecordedMap(cards[name].canvas, rendered);
  if (expandedModel === name) drawRecordedMap(document.getElementById("expanded-map"), rendered, true);
}

function drawAll() {
  if (!data) return;
  order.forEach(drawMap);
  drawChart();
}

function showRecordedDecision(name) {
  if (!recording) return;
  const junction = document.getElementById("junction").value;
  const event = currentFrame().runs.find(run => run.name === name).decisions[junction].at(-1);
  if (!event) return;
  const endTime = event.time + event.applied;
  const end = recording.frames.find(frame => frame.time >= endTime)?.runs.find(run => run.name === name);
  document.getElementById("decision-source").textContent = `${currentScenario().label} · s201 · ${junction === "B1" ? "J1" : "J2"} · קלט והחלטה מההרצה המוקלטת`;
  resumeAfterDialog = playing;
  playing = false;
  updateStatus();
  document.getElementById("detail-title").textContent = `${name} · החלטה מוקלטת ב־${event.time}s`;
  const rows = [["west", "מערב"], ["east", "מזרח"], ["north", "צפון"], ["south", "דרום"]].map(([key, label]) => {
    const approach = event.state.approaches[key];
    return `<tr><th>${label}</th><td>${approach.queue_length}</td><td>${approach.average_waiting_time.toFixed(1)}s</td><td>${approach.incoming_vehicles_30s}</td><td>${end?.queues[junction]?.[key] ?? "—"}</td></tr>`;
  });
  document.getElementById("detail-content").innerHTML = `<p class="decision-lead">בחר ${event.chosen} שניות לירוק ${event.phase === 3 ? "מזרח–מערב" : "צפון–דרום"}</p><p>המודל בוחר את משך הירוק. סדר הפאזות קובע את הכיוון.</p><table class="input-table"><thead><tr><th>כיוון</th><th>ממתינים בקלט</th><th>המתנה ממוצעת</th><th>צפי הגעה ב־30s</th><th>תור בסוף הירוק</th></tr></thead><tbody>${rows.join("")}</tbody></table><p>הוחלו ${event.applied} שניות${event.override ? " · התערבות בטיחות" : ""}. ${end ? `התור בסוף הירוק נלקח מההקלטה בזמן ${clock(endTime)}. השינוי כולל הגעות ועזיבות.` : "ההקלטה מסתיימת לפני סוף הירוק הזה."}</p><details><summary>וקטור הקלט שנשמר</summary><code dir="ltr">[${event.vector.map(value => value.toFixed(4)).join(", ")}]</code></details>`;
  dialog.showModal();
}

play.addEventListener("click", () => {
  if (elapsed >= 600) elapsed = 0;
  playing = !playing;
  lastFrame = performance.now();
  updateStatus();
});
document.getElementById("restart").addEventListener("click", reset);
scenarioSelect.addEventListener("change", loadRecording);
experimentSelect.addEventListener("change", renderComparison);
document.getElementById("close-details").addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => {
  playing = resumeAfterDialog;
  updateStatus();
});
document.getElementById("close-map").addEventListener("click", () => document.getElementById("map-dialog").close());
document.getElementById("map-dialog").addEventListener("close", () => { expandedModel = null; });
window.addEventListener("resize", drawAll);
document.getElementById("junction").addEventListener("change", () => { renderComparison(); drawAll(); });
document.getElementById("zoom").addEventListener("click", event => {
  fullGrid = !fullGrid;
  event.target.textContent = fullGrid ? "התמקד בצומת" : "הצג רשת מלאה";
  event.target.setAttribute("aria-pressed", !fullGrid);
  drawAll();
});
document.getElementById("seek").addEventListener("input", event => {
  elapsed = Number(event.target.value);
  if (elapsed >= 600) playing = false;
  updateStatus();
  renderComparison();
  drawAll();
});
document.getElementById("speed").addEventListener("change", event => {
  document.getElementById("source").textContent = `הרצה מוקלטת · 10:00 · ${event.target.value}×`;
});
document.addEventListener("visibilitychange", () => { lastFrame = performance.now(); });

function frame(now) {
  if (playing && !document.hidden) elapsed = Math.min(600, elapsed + (now - lastFrame) / 1000 * Number(document.getElementById("speed").value));
  lastFrame = now;
  if (playing) {
    order.forEach(drawMap);
    if (renderedSecond !== Math.floor(elapsed)) renderComparison();
    if (elapsed >= 600) {
      playing = false;
      updateStatus();
    }
  }
  document.getElementById("seek").value = Math.floor(elapsed);
  document.getElementById("time").textContent = `${Math.floor(elapsed / 60).toString().padStart(2, "0")}:${Math.floor(elapsed % 60).toString().padStart(2, "0")}`;
  requestAnimationFrame(frame);
}

async function initialize() {
  const response = await fetch("/presentation-data.json");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  data = await response.json();
  const manifestResponse = await fetch("/recordings/manifest.json");
  if (!manifestResponse.ok) throw new Error("Recording manifest unavailable");
  const manifest = await manifestResponse.json();
  geometry = manifest.geometry;
  experimentSelect.replaceChildren(...data.experiments.map(item => new Option(item.label, item.id)));
  scenarioSelect.replaceChildren(...data.experiments[0].scenarios.map((item, index) => new Option(item.label, index)));
  for (const name of order) {
    const article = document.createElement("article");
    article.className = `model ${name}`;
    article.innerHTML = `<div class="model-head"><h2 dir="ltr">${name}</h2>${["DQN", "A2C"].includes(name) ? "<button data-decision disabled>הסבר החלטה</button>" : `<span class="controller-type">${name === "TIMER" ? "מחזור קבוע" : "כללי Python"}</span>`}<button data-expand disabled>הגדל מפה</button></div><div class="map-stage"><canvas aria-label="מפת ההרצה המוקלטת של ${name}"></canvas><div class="map-caption"><span class="map-time"></span><div class="legend"><span><i class="stopped"></i>עומדים</span><span><i></i>נעים</span></div></div></div><div class="model-body"><p class="current-input"></p><p class="method"></p><p class="current-result"></p></div>`;
    document.getElementById("models").appendChild(article);
    article.querySelector("[data-decision]")?.addEventListener("click", () => showRecordedDecision(name));
    article.querySelector("[data-expand]").addEventListener("click", () => {
      expandedModel = name;
      document.getElementById("map-title").textContent = `${name} · רשת מלאה · הרצה מוקלטת`;
      document.getElementById("map-dialog").showModal();
      drawMap(name);
    });
    cards[name] = {canvas: article.querySelector("canvas"), article};
  }
  [play, scenarioSelect, experimentSelect, document.getElementById("restart")].forEach(item => item.disabled = false);
  await loadRecording();
  requestAnimationFrame(frame);
}

initialize().catch(error => {
  document.getElementById("status").textContent = "טעינת נתונים נכשלה";
  document.getElementById("presentation-guide").textContent = `רעננו את הדף או הפעילו שוב את Start-Web-Demo.cmd. ${error.message}`;
});
