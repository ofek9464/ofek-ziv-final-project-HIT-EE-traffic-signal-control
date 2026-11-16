"use strict";

const models = document.getElementById("models");
const names = ["DQN", "A2C", "TIMER", "SCRIPT"];
const learnedNames = ["DQN", "A2C"];
const controllerNames = ["TIMER", "SCRIPT", "DQN", "A2C"];
const scenarioLabels = {
  "Balanced": "תנועה מאוזנת",
  "Heavy west": "עומס כבד ממערב",
  "Morning rush": "עומס בוקר",
  "Evening rush": "עומס ערב",
  "Pedestrian heavy": "עומס הולכי רגל",
  "Full day cycle": "מחזור יום מלא",
  "Night (day-cycle segment)": "תנועת לילה",
};
const directions = [["north", "צפון N"], ["south", "דרום S"], ["east", "מזרח E"], ["west", "מערב W"]];
let geometry;
let snapshot;
let fullGrid = false;
let busy = false;
let lastSessionId;
let serverRestarted = false;
const modelBodies = {};
const canvases = {};

function number(value, decimals = 1) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(decimals);
}

function clock(value) {
  return `${Math.floor(value / 60).toString().padStart(2, "0")}:${Math.floor(value % 60).toString().padStart(2, "0")}`;
}

let selectedDecision = null;
let resumeAfterDetails = false;
const decisionDialog = document.getElementById("decision-dialog");

function textIn(root, selector, value) {
  root.querySelector(selector).textContent = value;
}

for (const name of names) {
  const article = document.createElement("article");
  article.className = `model ${name}`;
  const learned = learnedNames.includes(name);
  const controls = learned
    ? `<button type="button" data-details="${name}" disabled>הסבר החלטה</button><button type="button" data-next="${name}" disabled>עצור בהחלטה הבאה</button>`
    : `<span class="controller-type">${name === "TIMER" ? "מחזור קבוע" : "כללי Python"}</span>`;
  const footer = learned
    ? `<p class="waiting">ממתין להחלטה הראשונה…</p><div class="decision-body" hidden><div class="queue-inputs"><span class="decision-time"></span>${directions.map(([key,label]) => `<span data-direction="${key}">${label.split(" ")[0]} <strong>0</strong></span>`).join("")}</div><div class="brief"><strong class="chosen"></strong><span class="progress"></span></div><div class="outcome"><strong></strong><span></span></div></div>`
    : `<div class="summary-top"><span class="method"></span><span class="baseline-queue"></span></div><div class="brief"><strong class="chosen"></strong></div>`;
  article.innerHTML = `<div class="model-head"><h2 dir="ltr">${name}</h2><div class="model-actions">${controls}</div></div><div class="map-stage"><canvas aria-label="מפת SUMO החיה של ${name}"></canvas><div class="map-caption"><span class="map-time"></span><div class="legend"><span><i class="stopped"></i>עומדים</span><span><i></i>נעים</span></div></div></div><div class="model-body">${footer}</div>`;
  models.appendChild(article);
  modelBodies[name] = article.querySelector(".model-body");
  canvases[name] = article.querySelector("canvas");
  article.querySelector("[data-next]")?.addEventListener("click", () => control("next", name));
  article.querySelector("[data-details]")?.addEventListener("click", () => openDecision(name));
}

function renderBaseline(run) {
  const junction = document.getElementById("junction").value;
  const light = run.lights[junction];
  const phase = light ? ({0: "ירוק לצפון–דרום", 3: "ירוק למזרח–מערב"}[light.phase] ?? "מעבר בין פאזות") : "ממתין";
  const body = modelBodies[run.name];
  textIn(body, ".method", run.name === "TIMER" ? "משך ירוק קבוע" : "משך ירוק לפי כללי התנועה");
  textIn(body, ".baseline-queue", `בצומת הנבחר ${Object.values(run.queues?.[junction] || {}).reduce((a,b)=>a+b,0)} ממתינים`);
  textIn(body, ".chosen", `${phase}${light ? ` · נותרו ${number(light.remaining, 0)}s` : ""}`);
}

function renderDecision(run) {
  const junction = document.getElementById("junction").value;
  const events = run.decisions[junction];
  const event = events[events.length - 1];
  const body = modelBodies[run.name];
  body.querySelector(".waiting").hidden = Boolean(event);
  body.querySelector(".decision-body").hidden = !event;
  document.querySelector(`[data-details="${run.name}"]`).disabled = !event || busy;
  if (!event) {
    body.querySelector(".waiting").textContent = "ממתין לתחילת ההרצה ולהחלטה הראשונה…";
    return;
  }
  const state = event.state;
  const before = directions.reduce((total,[key]) => total + state.approaches[key].queue_length,0);
  const current = event.outcome?.queues || run.queues?.[junction];
  const after = current ? Object.values(current).reduce((a,b)=>a+b,0) : null;
  const when = event.outcome?.time ?? snapshot.time;
  textIn(body, ".decision-time", `קלט ${clock(event.time)} · בתור`);
  for (const [key] of directions) textIn(body, `[data-direction="${key}"] strong`, state.approaches[key].queue_length);
  textIn(body, ".chosen", `בחר ${event.chosen}s לירוק ${event.phase === 3 ? "מזרח–מערב" : "צפון–דרום"}`);
  const light = run.lights[junction];
  textIn(body, ".progress", event.override ? `בטיחות · הוחלו ${event.applied}s` : light?.phase === event.phase ? `נותרו ${number(light.remaining,0)}s` : "מעבר פאזה");
  textIn(body, ".outcome strong", after === null ? "ממתין למדידה" : `התור מ־${before} ל־${after}`);
  textIn(body, ".outcome span", `${event.outcome ? "בסוף הירוק" : "עד כה"} · ${number(when-event.time,0)}s · כולל הגעות`);
}

async function openDecision(model) {
  const junction = document.getElementById("junction").value;
  const run = snapshot.runs.find(r=>r.name===model);
  const events = run.decisions[junction];
  if (!events.length) return;
  resumeAfterDetails = snapshot.status === "running";
  selectedDecision = {model,junction,runId:snapshot.run_id,sessionId:snapshot.session_id,event:structuredClone(events[events.length-1]),weights:run.weights};
  if (!await control("pause")) {selectedDecision=null; return;}
  const history = document.getElementById("decision-history");
  history.replaceChildren(...[...events].reverse().map(e=>new Option(`${clock(e.time)} · ${e.chosen}s · ${e.phase===3 ? "מזרח–מערב" : "צפון–דרום"}`,e.id)));
  renderSelectedDecision();
  decisionDialog.showModal();
}

function renderSelectedDecision() {
  if (!selectedDecision) return;
  const {model,junction,event,runId} = selectedDecision;
  const run = snapshot.runs.find(r=>r.name===model);
  const updated = snapshot.run_id === runId ? run?.decisions[junction].find(e=>e.id===event.id) : null;
  if (updated) selectedDecision.event = structuredClone(updated);
  const decision = selectedDecision.event;
  const state = decision.state;
  const outcome = decision.outcome;
  document.getElementById("detail-title").textContent = `${model} · ${junction==="B1"?"J1":"J2"} · קלט ${clock(decision.time)}`;
  document.getElementById("detail-status").textContent = snapshot.status === "seeking" ? "מתקדם לסוף הירוק של ההחלטה הנבחרת…" : snapshot.status === "complete" ? "ההרצה הסתיימה · ניתוח החלטה שמורה" : "צילום החלטה שמור · ההדגמה מושהית לניתוח";
  document.getElementById("finish-decision").disabled = busy || Boolean(outcome) || snapshot.run_id!==runId || ["loading","error","complete","seeking"].includes(snapshot.status);
  const key = `${runId}/${decision.id}/${outcome?.time ?? "pending"}`;
  if (decisionDialog.dataset.key===key) return;
  decisionDialog.dataset.key=key;
  const counts=run?.action_counts?.[junction] || {};
  const total=Object.values(counts).reduce((a,b)=>a+b,0);
  const chosenCount=counts[String(decision.chosen)] || 0;
  const phase=decision.phase===3 ? "מזרח–מערב" : "צפון–דרום";
  document.getElementById("detail-content").innerHTML=`<p class="decision-lead">בחר ${decision.chosen} שניות לירוק ${phase} · הוחלו ${decision.applied} שניות${decision.override ? " · התערבות בטיחות" : ""}</p><p>המודל בוחר משך ירוק. סדר הפאזות קובע את הכיוון.</p><table class="input-table"><thead><tr><th>כיוון</th><th>תור בקלט</th><th>המתנה ממוצעת</th><th>צפי הגעה ב־30s</th><th>${outcome?`תור בסוף ${clock(outcome.time)}`:"תור בסוף הירוק"}</th></tr></thead><tbody>${directions.map(([key,label])=>{const row=state.approaches[key];return `<tr><th>${label}</th><td>${row.queue_length}</td><td>${number(row.average_waiting_time)}s</td><td>${row.incoming_vehicles_30s}</td><td>${outcome?outcome.queues[key]:"טרם נמדד"}</td></tr>`;}).join("")}</tbody></table><p class="measurement-note">${outcome?`מדידה לאחר ${number(outcome.time-decision.time,0)} שניות, בסוף הירוק שהוחל. השינוי כולל הגעות ועזיבות.`:snapshot.status==="complete"?"ההרצה הסתיימה לפני סוף הירוק הזה. אפשר לבחור החלטה קודמת עם מדידה מלאה.":"לחצו ״הצג תוצאה בסוף הירוק״ כדי להתקדם ולמדוד את אותה החלטה."}</p><p>קלט נוסף · פאזה ${phase}, חלפה ${number(state.phase_elapsed_time)}s · הקטע לצומת השני ${{free:"פנוי",moderate:"בינוני",congested:"עמוס"}[state.downstream_status.road_to_other]} · הולכי רגל ${state.pedestrians.waiting_count}, המתנה ${number(state.pedestrians.average_waiting_time)}s</p><h3>${model==="DQN"?"ערכי Q-values לכל משך · הערך הגבוה ביותר נבחר":"הסתברויות Actor לכל משך · ההסתברות הגבוהה ביותר נבחרת"}</h3><div class="scores">${snapshot.actions.map((action,i)=>`<div class="${action===decision.chosen?"selected":""}"><strong>${action}s</strong><span>${decision.score_type==="Probability"?`${number(decision.scores[i]*100)}%`:number(decision.scores[i])}</span></div>`).join("")}</div><p>${chosenCount} מתוך ${total} החלטות ${model} בצומת הזה בחרו ${decision.chosen}s בהרצה הנוכחית.</p><details><summary>וקטור הקלט וקובץ המשקלים</summary><code>[${decision.vector.map(v=>number(v,4)).join(", ")}]</code><code>${selectedDecision.weights}</code></details>`;
}

document.getElementById("decision-history").addEventListener("change",event=>{
  const {model,junction}=selectedDecision;
  selectedDecision.event=structuredClone(snapshot.runs.find(r=>r.name===model).decisions[junction].find(e=>e.id===Number(event.target.value)));
  renderSelectedDecision();
});
document.getElementById("finish-decision").addEventListener("click",()=>control("finish",selectedDecision.model,undefined,selectedDecision.event.id,selectedDecision.junction));
document.getElementById("close-details").addEventListener("click",()=>decisionDialog.close());
decisionDialog.addEventListener("close",()=>{
  selectedDecision=null;
  delete decisionDialog.dataset.key;
  if (resumeAfterDetails && !["complete","error","loading"].includes(snapshot.status)) control("play");
  resumeAfterDetails=false;
});

function render() {
  const statuses = {loading: "טוען", paused: "מושהה", running: "החלטות אוטומטיות", seeking: "מתקדם ועוצר לניתוח", complete: "הריצה הסתיימה", error: "שגיאה"};
  const status = snapshot.status;
  if (lastSessionId && snapshot.session_id && lastSessionId !== snapshot.session_id) serverRestarted = true;
  if (snapshot.session_id) lastSessionId = snapshot.session_id;
  if (status === "running") serverRestarted = false;
  if (selectedDecision && (selectedDecision.runId !== snapshot.run_id || selectedDecision.sessionId !== snapshot.session_id)) {
    resumeAfterDetails = false;
    selectedDecision = null;
    if (decisionDialog.open) decisionDialog.close();
  }
  document.getElementById("status").textContent = statuses[status] ?? status;
  const guide = document.getElementById("presentation-guide");
  guide.textContent = serverRestarted ? "השרת הופעל מחדש ונפתחה הרצה חדשה. בחרו תרחיש ולחצו ״התחל הדגמה״."
    : document.body.dataset.view === "analysis"
    ? "ניתוח · עצירה בהחלטה הבאה, הסבר קלט ופלט, ומדידה בסוף הירוק."
    : status === "running" ? "מפות חיות · AI בוחר משך ירוק · ״הסבר החלטה״ עוצר ומציג קלט, בחירה ותוצאה."
    : status === "error" ? "הריצה נעצרה עקב שגיאה. ״התחל מחדש״ מפעיל סימולציה חדשה."
    : status === "complete" ? "ההרצה הסתיימה · הנתונים הם תוצאות ההרצה · אפשר להתחיל תרחיש נוסף."
    : "לחצו ״התחל הדגמה״ או ״המשך הדגמה״. ארבעת הבקרים יפעלו אוטומטית.";
  document.getElementById("time").textContent = clock(snapshot.time);
  if (snapshot.scenario) {
    const label = scenarioLabels[snapshot.scenario];
    document.getElementById("source").textContent = `SUMO · s${snapshot.seed} · ${snapshot.speed}×`;
    document.getElementById("scenario-description").textContent = `הרצה נוכחית · ${label}`;
    document.getElementById("comparison-scenario").textContent = `${label} · ${clock(snapshot.time)}`;
    const select = document.getElementById("scenario");
    if (!select.options.length) {
      for (const name of snapshot.scenarios) select.add(new Option(scenarioLabels[name], name));
    }
    if (!busy) select.value = snapshot.scenario;
  }
  const error = document.getElementById("error");
  error.hidden = !snapshot.error;
  error.textContent = snapshot.error ?? "";
  const disabled = ["loading", "error", "seeking", "complete"].includes(status) || busy;
  document.getElementById("play").disabled = ["loading", "error"].includes(status) || busy;
  document.getElementById("play").textContent = ["running", "seeking"].includes(status) ? "השהה הדגמה" : status === "complete" ? "התחל הדגמה חדשה" : snapshot.time > 0 ? "המשך הדגמה" : "התחל הדגמה";
  document.getElementById("restart").disabled = status === "loading" || busy;
  document.getElementById("scenario").disabled = status === "loading" || busy;
  document.querySelectorAll("[data-next]").forEach(button => {button.disabled = disabled;});
  const junction = document.getElementById("junction").value;
  if (status === "loading") {
    for (const name of names) {
      const canvas = canvases[name];
      canvas.getContext("2d").clearRect(0,0,canvas.width,canvas.height);
      canvas.parentNode.querySelector(".map-time").textContent = "טוען תרחיש חדש…";
    }
    for (const name of ["TIMER","SCRIPT"]) {
      textIn(modelBodies[name], ".method", "טוען תרחיש…");
      textIn(modelBodies[name], ".baseline-queue", "");
      textIn(modelBodies[name], ".chosen", "");
    }
    for (const name of learnedNames) {
      modelBodies[name].querySelector(".decision-body").hidden = true;
      modelBodies[name].querySelector(".waiting").hidden = false;
      modelBodies[name].querySelector(".waiting").textContent = "טוען תרחיש…";
      document.querySelector(`[data-details="${name}"]`).disabled = true;
    }
  }
  for (const run of snapshot.runs) {
    if (!names.includes(run.name)) continue;
    if (learnedNames.includes(run.name)) renderDecision(run);
    else renderBaseline(run);
    const light = run.lights[junction];
    const phase = light ? ({0: "צפון–דרום", 3: "מזרח–מערב"}[light.phase] ?? "מעבר") : "—";
    canvases[run.name].parentNode.querySelector(".map-time").textContent = `מפה חיה ${clock(snapshot.time)} · ${phase}${light ? ` · ${number(light.remaining, 0)}s נותרו` : ""}`;
  }
  document.getElementById("metric-note").textContent = `פחות המתנה = טוב יותר · נסיעות שהושלמו בלבד · התור בשני הצמתים · ${status === "complete" ? "תוצאות סיום ההרצה" : "מדדי ביניים בריצה"}`;
  const baseline = snapshot.runs.find(r => r.name === "TIMER")?.waiting;
  document.getElementById("comparison-rows").innerHTML = controllerNames.map(name => {
    const run = snapshot.runs.find(r => r.name === name);
    const wait = run?.waiting;
    const delta = baseline > 0 && wait !== null && wait !== undefined && name !== "TIMER" ? (wait - baseline) / baseline * 100 : null;
    const comparison = delta === null ? "—" : `${delta > 0 ? "+" : ""}${delta.toFixed(0)}%`;
    const waiting = wait === null || wait === undefined ? "—" : `${number(wait)}s`;
    return `<tr><td><span class="controller-name ${name.toLowerCase()}" dir="ltr">${name}</span></td><td><bdi>${waiting}</bdi></td><td>${run?.completed ?? 0}</td><td>${run?.queued ?? 0}</td><td class="${delta < 0 ? "better" : delta > 0 ? "worse" : ""}"><bdi>${comparison}</bdi></td></tr>`;
  }).join("");
  drawMaps();
  drawComparison();
  if (selectedDecision) renderSelectedDecision();
}

function drawComparison() {
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
  const maxX = Math.max(60, snapshot.time);
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

function drawMap(canvas, run) {
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
  const bounds = fullGrid ? geometry.bounds : [center[0] - 65, center[1] - 17.5, center[0] + 65, center[1] + 17.5];
  const horizontalScale = (w - 24) / (bounds[2] - bounds[0]);
  const verticalScale = (h - 24) / (bounds[3] - bounds[1]);
  const scale = Math.min(horizontalScale, verticalScale);
  const project = point => [w / 2 + (point[0] - (bounds[0] + bounds[2]) / 2) * scale, h / 2 - (point[1] - (bounds[1] + bounds[3]) / 2) * scale];
  ctx.lineCap = "butt";
  ctx.lineJoin = "round";
  for (const lane of geometry.lanes) {
    if (!lane.shape.length) continue;
    ctx.strokeStyle = lane.pedestrian ? "#b4c0b5" : "#171d1b";
    ctx.lineWidth = Math.max(fullGrid ? 1 : 2, lane.width * scale);
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
      ctx.lineWidth = fullGrid ? 2 : 3;
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

function drawMaps() {
  if (!snapshot || !geometry) return;
  for (const run of snapshot.runs) if (canvases[run.name]) drawMap(canvases[run.name], run);
}

async function control(action, model, scenario, event_id, junction) {
  busy = true;
  render();
  try {
    const response = await request("/api/control", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action, model, scenario, event_id, junction: junction || document.getElementById("junction").value})});
    if (!response.ok) throw new Error(`Control failed (${response.status})`);
    return true;
  } catch (error) {
    showConnectionError(error);
    return false;
  } finally {
    busy = false;
  }
}

function showConnectionError(error) {
  const node = document.getElementById("error");
  node.hidden = false;
  node.textContent = `החיבור לשרת נכשל. ${error.message}`;
  document.getElementById("status").textContent = "אין חיבור";
  document.querySelectorAll("#play,#restart,#scenario,[data-next],[data-details],#finish-decision").forEach(button => {button.disabled = true;});
}

document.getElementById("play").addEventListener("click", async () => {
  if (snapshot.status === "complete" && !await control("restart")) return;
  await control(["running", "seeking"].includes(snapshot.status) ? "pause" : "play");
});

document.getElementById("inspect").addEventListener("click", event => {
  const analysis = document.body.dataset.view !== "analysis";
  document.body.dataset.view = analysis ? "analysis" : "presentation";
  event.target.setAttribute("aria-pressed", analysis);
  event.target.textContent = analysis ? "חזרה להצגה" : "ניתוח החלטה";
  if (snapshot) render();
});
document.getElementById("restart").addEventListener("click", async () => {
  if (await control("restart")) await control("play");
});
document.getElementById("scenario").addEventListener("change", event => control("scenario", undefined, event.target.value));
document.getElementById("junction").addEventListener("change", () => {if (snapshot) render();});
document.getElementById("zoom").addEventListener("click", event => {fullGrid = !fullGrid;event.target.textContent = fullGrid ? "התמקד בצומת" : "הצג רשת מלאה";event.target.setAttribute("aria-pressed", !fullGrid);drawMaps();});
new ResizeObserver(drawMaps).observe(models);
new ResizeObserver(drawComparison).observe(document.querySelector(".chart-panel"));

async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal});
    const body = await response.text();
    return {ok:response.ok,status:response.status,json:()=>JSON.parse(body)};
  } finally {
    clearTimeout(timeout);
  }
}

async function poll() {
  try {
    if (!geometry) {
      const response = await request("/api/geometry");
      if (!response.ok) throw new Error("Network geometry unavailable");
      geometry = await response.json();
    }
    const response = await request("/api/state");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    snapshot = await response.json();
    render();
  } catch (error) {
    showConnectionError(error);
  } finally {
    setTimeout(poll, 200);
  }
}
poll();
