"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value: id === "speed" ? "1" : "0", textContent: "", addEventListener() {}});
  return elements.get(id);
}
const context = vm.createContext({
  document: {getElementById: element, hidden: false, addEventListener() {}},
  window: {addEventListener() {}},
  performance: {now: () => 0},
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
