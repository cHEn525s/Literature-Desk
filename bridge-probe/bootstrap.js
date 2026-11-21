// Test-only bridge. Both the profile and the data directory must match the fixture.
let active = false;
let timer, lock, root, token;
const join = (...parts) => PathUtils.join(...parts);
const put = (file, value) => IOUtils.writeJSON(file, value, {tmpPath: file + ".tmp"});

async function collection(name, parentID) {
  const libraryID = Zotero.Libraries.userLibraryID;
  const siblings = parentID ? Zotero.Collections.getByParent(parentID)
    : Zotero.Collections.getByLibrary(libraryID);
  let result = siblings.find(c => c.name === name && !c.deleted);
  if (!result) {
    result = new Zotero.Collection();
    result.libraryID = libraryID;
    result.name = name;
    if (parentID) result.parentID = parentID;
    await result.saveTx();
  }
  return result;
}

async function inspect(bind) {
  const libraryID = Zotero.Libraries.userLibraryID;
  const title = "Synthetic bridge fixture " + token;
  const items = await Zotero.Items.getAll(libraryID, true);
  let matches = items.filter(i => i.getField("title") === title);
  if (bind) {
    const parent = await collection("Step 1 " + token);
    const a = await collection("Group A", parent.id);
    const b = await collection("Group B", parent.id);
    if (matches.length > 1) throw new Error("Ambiguous fixture");
    let item = matches[0] || new Zotero.Item("journalArticle");
    item.libraryID = libraryID;
    item.setField("title", title);
    item.setCollections([a.id, b.id]);
    await item.saveTx();
    if (!item.getAttachments().length) {
      await Zotero.Attachments.importFromFile({
        file: join(root, "fixture.pdf"), parentItemID: item.id
      });
    }
    return inspect(false);
  }
  if (matches.length !== 1) throw new Error("Unexpected item count: " + matches.length);
  const item = matches[0];
  const attachments = [];
  for (const id of item.getAttachments()) {
    const attachment = Zotero.Items.get(id);
    attachments.push({key: attachment.key, path: await attachment.getFilePathAsync()});
  }
  return {libraryID, item: item.key, count: matches.length, attachments,
    collections: item.getCollections().map(id => {
      const c = Zotero.Collections.get(id);
      return {name: c.name, key: c.key, parent: c.parentKey};
    })};
}

async function poll() {
  try {
    if (!active) return;
    const commandDir = join(root, "commands");
    for (const path of (await IOUtils.getChildren(commandDir)).sort()) {
      const name = PathUtils.filename(path);
      if (!/^\d{2}\.json$/.test(name)) continue;
      const receipt = join(root, "receipts", name);
      if (await IOUtils.exists(receipt)) continue;
      const cmd = await IOUtils.readJSON(path);
      if (cmd.token !== token || cmd.command_id !== "fixture-bind" || cmd.op !== "bind")
        throw new Error("Unexpected fixture command");
      try { await put(receipt, {command_id:cmd.command_id, result:await inspect(true)}); }
      catch (e) { await put(receipt, {error:String(e), stack:e.stack}); }
    }
    if (await IOUtils.exists(join(root, "finish"))) {
      active = false;
      Services.startup.quit(Components.interfaces.nsIAppStartup.eAttemptQuit);
      return;
    }
  } catch (e) { await put(join(root, "error.json"), {error:String(e), stack:e.stack}); }
  if (active) timer = setTimeout(poll, 250);
}

async function startup() {
  const profile = Services.dirsvc.get("ProfD", Components.interfaces.nsIFile).path;
  const cfgPath = join(profile, "step1.json");
  if (!(await IOUtils.exists(cfgPath))) return;
  const cfg = await IOUtils.readJSON(cfgPath);
  root = cfg.root;
  token = cfg.token;
  try {
    await Zotero.initializationPromise;
    if (profile.toLowerCase() !== join(root, "profile").toLowerCase()
      || Zotero.DataDirectory.dir.toLowerCase() !== join(root, "data").toLowerCase())
      throw new Error("Isolation check failed");
    const {Sqlite} = ChromeUtils.importESModule("resource://gre/modules/Sqlite.sys.mjs");
    lock = await Sqlite.openConnection({path:join(root, "bridge-lock.sqlite")});
    await lock.execute("PRAGMA busy_timeout=0");
    await lock.execute("BEGIN EXCLUSIVE");
    await put(join(root, "hello.json"), {token, version:Zotero.version,
      libraryID:Zotero.Libraries.userLibraryID, data:Zotero.DataDirectory.dir,
      profile, protocol:1});
    active = true;
    await poll();
  } catch (e) { await put(join(root, "error.json"), {error:String(e), stack:e.stack}); }
}

async function shutdown() {
  active = false;
  clearTimeout(timer);
  if (lock) await lock.close();
}
