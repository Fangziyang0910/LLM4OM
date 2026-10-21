const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = ts.transpileModule(fs.readFileSync(`${__dirname}/../src/useRun.ts`, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;

// Run the actual hook with immediate state updates and a scripted SDK stream.
async function disconnectedRun(finalStatus) {
  let state, reads = 0, finished = 0;
  const run = { run_id: "run", status: "running" };
  const client = {
    threads: { get: async () => { reads++; return { metadata: {}, values: {} }; } },
    runs: {
      list: async () => [{ ...run }],
      joinStream: async function* () { run.status = finalStatus; throw new Error("SSE retries exhausted"); },
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(source, {
    module, exports: module.exports, AbortController,
    require: name => name === "react" ? {
      useState: initial => { state = initial; return [state, update => { state = typeof update === "function" ? update(state) : update; }]; },
      useEffect: effect => effect(),
    } : { client, errorText: error => error.message },
  });
  module.exports.useRun("thread", () => finished++);
  await new Promise(resolve => setImmediate(resolve));
  return { state, reads, finished };
}

test("a broken stream still reads the completed run", async () => {
  const { state, reads, finished } = await disconnectedRun("success");
  assert.equal(state.run.status, "success");
  assert.equal(state.error, null);
  assert.equal(state.streaming, false);
  assert.equal(reads, 2);
  assert.equal(finished, 1);
});

test("a broken stream reports an active run as disconnected", async () => {
  const { state, reads } = await disconnectedRun("running");
  assert.equal(state.run.status, "running");
  assert.equal(state.error, "SSE retries exhausted");
  assert.equal(reads, 2);
});

test("leaving a run ignores its late state response", async () => {
  let state, cleanup, resolveThread;
  const pending = new Promise(resolve => { resolveThread = resolve; });
  const client = {
    threads: { get: () => pending },
    runs: { list: async () => [{ run_id: "old", status: "running" }] },
  };
  const module = { exports: {} };
  vm.runInNewContext(source, {
    module, exports: module.exports, AbortController,
    require: name => name === "react" ? {
      useState: initial => { state = initial; return [state, update => { state = typeof update === "function" ? update(state) : update; }]; },
      useEffect: effect => { cleanup = effect(); },
    } : { client, errorText: error => error.message },
  });
  module.exports.useRun("old-thread", () => assert.fail("unmounted run completed"));
  cleanup();
  resolveThread({ metadata: { title: "old-thread" }, values: { code: "stale" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.meta, null);
  assert.equal(state.run, null);
});
