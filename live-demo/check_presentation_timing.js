"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const elements = new Map();
let currentTime = 0;
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: id === "speed" ? "1" : "0",
    textContent: "",
    addEventListener() {},
    replaceChildren() {},
    getContext() { return {clearRect() {}}; },
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: {getElementById: element, hidden: false, addEventListener() {}},
  window: {addEventListener() {}},
  performance: {now: () => currentTime},
  matchMedia: () => ({matches: false}),
  fetch: () => new Promise(() => {}),
  requestAnimationFrame() {},
});
vm.runInContext(fs.readFileSync(`${__dirname}/presentation.js`, "utf8"), context);
vm.runInContext("drawMap = () => {}; renderComparison = () => { renderedSecond = Math.floor(elapsed); }; playing = true; lastFrame = 0; frame(10000)", context);
assert.equal(vm.runInContext("elapsed", context), 10);
vm.runInContext("frame(12000)", context);
assert.equal(vm.runInContext("elapsed", context), 12);
vm.runInContext("frame(600000)", context);
assert.equal(vm.runInContext("elapsed", context), 600);
assert.equal(vm.runInContext("playing", context), false);
assert.equal(element("time").textContent, "10:00");
vm.runInContext("frame(620000)", context);
assert.equal(vm.runInContext("elapsed", context), 600);
console.log("PASS: 1x timing passes ten seconds, reaches ten minutes and holds the final frame without automatic reset");

async function checkScenarioSwitch() {
  vm.runInContext('drawAll = () => {}; currentScenario = () => ({label: "Test"});', context);
  let finishLoading;
  context.fetch = () => new Promise(resolve => { finishLoading = resolve; });
  const response = {ok: true, json: async () => ({duration: 600, frames: Array(601).fill({})})};
  vm.runInContext('playing = true; elapsed = 24; scenarioSelect.value = "1";', context);
  const activeSwitch = vm.runInContext('loadRecording()', context);
  assert.equal(vm.runInContext('playing', context), false);
  currentTime = 150;
  finishLoading(response);
  await activeSwitch;
  assert.equal(vm.runInContext('playing', context), true);
  assert.equal(vm.runInContext('elapsed', context), 0);
  vm.runInContext('frame(100)', context);
  assert.equal(vm.runInContext('elapsed', context), 0);
  assert.equal(vm.runInContext('frameIndex()', context), 0);
  vm.runInContext('frame(1100)', context);
  assert.equal(vm.runInContext('elapsed', context), 1);

  vm.runInContext('playing = false; elapsed = 77; scenarioSelect.value = "2";', context);
  const pausedSwitch = vm.runInContext('loadRecording()', context);
  finishLoading(response);
  await pausedSwitch;
  assert.equal(vm.runInContext('playing', context), false);
  assert.equal(vm.runInContext('elapsed', context), 0);
  console.log("PASS: switching a playing scenario resumes automatically after loading, and a paused scenario stays paused");
}

checkScenarioSwitch().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
