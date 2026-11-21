// Pure serial scheduler shared by the controlled and real-plugin runs.
function makeQueue(tasks, now) {
  return {phase:"running", started:now, last:now, next:0, active:null,
    pausePending:false, calls:0, obtained:0, missing:0, maxGap:0, tasks:tasks.length};
}

async function tick(q, tasks, api) {
  if (q.phase !== "running" || q.active !== null) return;
  const task = tasks[q.next];
  if (api.now() < q.started + task.offset) return;
  q.active = q.next;
  q.calls++;
  await api.save(q); // A restart with an active request requires reconciliation.
  try {
    const result = await api.acquire(task);
    if (!["obtained", "missing"].includes(result.status)) throw Error("Unknown result");
    await api.receipt(q.next, result);
    q[result.status]++;
    q.maxGap = Math.max(q.maxGap, api.now()-q.last);
    q.last = api.now();
    q.next++;
    q.active = null;
    if (q.next === tasks.length) q.phase = "done";
    else if (q.pausePending) q.phase = "paused";
  } catch (error) {
    q.phase = "paused";
    q.reason = String(error);
  }
  q.pausePending = false;
  await api.save(q);
}

if (typeof module !== "undefined") module.exports = {makeQueue, tick};
