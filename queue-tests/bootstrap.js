const join = (...parts) => PathUtils.join(...parts);
let base, lanes, stopped = false;
const write = (path, data) => IOUtils.writeJSON(path, data, {tmpPath:path+".tmp"});
const wait = ms => Zotero.Promise.delay(ms);

async function attachment(item) {
  for (const id of item.getAttachments()) {
    const a = Zotero.Items.get(id);
    const path = await a.getFilePathAsync();
    if (path && await IOUtils.exists(path) &&
        new TextDecoder().decode(await IOUtils.read(path, {maxBytes:5})) === "%PDF-")
      return {status:"obtained", item:item.key, attachment:a.key, path};
  }
  return null;
}

async function lookup(doi) {
  const items = await Zotero.Items.getAll(Zotero.Libraries.userLibraryID, true);
  return items.find(item => item.isRegularItem() && item.getField("DOI") === doi);
}

async function real(task) {
  let item = await lookup(task.doi);
  if (!item) {
    item = new Zotero.Item("journalArticle");
    item.setField("DOI", task.doi);
    item.setField("title", task.title);
    await item.saveTx();
  }
  const existing = await attachment(item);
  if (existing) return {...existing, reused:true};
  try {
    await Zotero.Scihub.updateItem(task.doi, item);
  } catch (e) {
    if (e.name === "PdfNotFoundError") return {status:"missing", reason:String(e)};
    throw e;
  }
  const file = await attachment(item);
  if (!file) throw Error("Plugin returned without a readable PDF");
  return file;
}

async function drive(name, tasks, acquire) {
  const dir = join(base,name);
  const state = join(dir,"state.json");
  const save = q => write(state,q);
  const existing = await IOUtils.exists(state);
  const q = existing ? await IOUtils.readJSON(state) : makeQueue(tasks,Date.now());
  if (existing && q.phase === "running") {
    q.phase = "paused";
    q.reason = "Instance restarted";
  }
  await save(q);
  const resultPath = index => join(dir,"results",index+".json");
  const api = {now:Date.now, save, acquire, receipt:(index,result) =>
    write(resultPath(index),{index,at:Date.now(),...result})};
  while (!stopped && q.phase !== "done") {
    const pause = join(dir,"pause");
    const resume = join(dir,"continue");
    if (await IOUtils.exists(pause)) {
      q.phase = "paused";
      q.reason = "User pause";
      await save(q);
      await IOUtils.remove(pause);
      if (await IOUtils.exists(resume)) await IOUtils.remove(resume);
    }
    if (q.phase === "paused" && await IOUtils.exists(resume)) {
      await IOUtils.remove(resume);
      if (q.active !== null && await IOUtils.exists(resultPath(q.active))) {
        const saved = await IOUtils.readJSON(resultPath(q.active));
        q[saved.status]++;
        q.next++;
      }
      q.active = null;
      q.reason = null;
      q.phase = q.next === tasks.length ? "done" : "running";
      await save(q);
    }
    await tick(q,tasks,api);
    if (q.phase !== "done") await wait(1000);
  }
}

async function startProbe() {
  const profile = PathUtils.profileDir;
  const file = join(profile,"step3.json");
  if (!await IOUtils.exists(file)) return;
  const cfg = await IOUtils.readJSON(file);
  base = cfg.root;
  try {
    await Zotero.initializationPromise;
    if (profile.toLowerCase() !== join(base,"profile").toLowerCase() ||
        Zotero.DataDirectory.dir.toLowerCase() !== join(base,"data").toLowerCase())
      throw Error("Unexpected test profile");
    for (let i=0; i<100 && !Zotero.Scihub?.updateItem; i++) await wait(100);
    if (!Zotero.Scihub?.updateItem || Zotero.Scihub.isAutomaticPdfDownload())
      throw Error("Plugin preflight failed");
    const synthetic = Array.from({length:1441}, (_,i) => ({offset:i*60000, index:i}));
    await Promise.all([
      drive("controlled",synthetic, async t => ({status:t.index % 5 === 1 ? "missing":"obtained"})),
      drive("real",cfg.papers,real)
    ]);
    await write(join(base,"completed.json"),{at:Date.now()});
  } catch(e) {await write(join(base,"error.json"),{error:String(e),stack:e.stack});}
}
function startup() {setTimeout(startProbe,0);}
function shutdown() {stopped=true;}
