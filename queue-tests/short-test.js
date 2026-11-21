// Exercise the actual drive loop, including persisted checkpoints, with a fake clock.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const files = new Map();
const calls = [];
const clone = x => JSON.parse(JSON.stringify(x));
let onWait = () => {};
const ctx = vm.createContext({PathUtils:{join:path.posix.join}, Date,
  IOUtils:{writeJSON:async (p,v)=>files.set(p,clone(v)), readJSON:async p=>clone(files.get(p)),
    exists:async p=>files.has(p), remove:async p=>files.delete(p)},
  Zotero:{Promise:{delay:async () => onWait()}}, console});
for (const file of ["queue.js","bootstrap.js"])
  vm.runInContext(fs.readFileSync(path.join(__dirname,file),"utf8"),ctx);
vm.runInContext('base="/test"',ctx);
const dir="/test/short";
const state=dir+"/state.json";
const tasks=[0,1,2,3].map(i=>({i,offset:0}));
async function acquire(t) {
  calls.push(t.i);
  if(t.i===1) files.set(dir+"/pause",true);
  return {status:t.i===1?"missing":"obtained"};
}
(async()=>{
  onWait=()=>{if(files.get(state).phase==="paused") throw Error("test process exit");};
  await assert.rejects(ctx.drive("short",tasks,acquire),/test process exit/);
  assert.deepEqual(calls,[0,1]);
  assert.equal(files.get(state).next,2);
  let polls=0;
  onWait=()=>{
    if(files.get(state).phase==="paused" && ++polls===3) {
      assert.deepEqual(calls,[0,1]);
      files.set(dir+"/continue",true);
    }
  };
  await ctx.drive("short",tasks,acquire);
  assert.deepEqual(calls,[0,1,2,3]);
  const end=files.get(state);
  assert.equal(end.phase,"done");
  assert.equal(end.missing,1);
  assert.equal(end.obtained,3);
  console.log("PASS: 4 tasks, 1 missing, 3 obtained, paused across driver restart, explicit continue, no repeated calls");
})().catch(e=>{console.error(e);process.exitCode=1;});
