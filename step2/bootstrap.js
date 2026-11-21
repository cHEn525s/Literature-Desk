// Single-DOI integration probe, restricted to its own profile and database.
async function run() {
  const profile = PathUtils.profileDir;
  const config = PathUtils.join(profile, "step2.json");
  if (!(await IOUtils.exists(config))) return;
  const {root, doi, title} = await IOUtils.readJSON(config);
  const receipt = PathUtils.join(root, "receipt.json");
  if (await IOUtils.exists(receipt)) return;
  const events = [];
  const mark = async (state, details = {}) => {
    events.push({state, at: new Date().toISOString(), ...details});
    await IOUtils.writeJSON(receipt, {doi, events}, {tmpPath: receipt + ".tmp"});
  };
  try {
    await Zotero.initializationPromise;
    if (profile.toLowerCase() !== PathUtils.join(root,"profile").toLowerCase() ||
        Zotero.DataDirectory.dir.toLowerCase() !== PathUtils.join(root,"data").toLowerCase())
      throw new Error("Unexpected profile or data directory");
    const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
    const addon = await AddonManager.getAddonByID("scihub@example.com");
    for (let i=0; i<100 && !Zotero.Scihub?.updateItem; i++) await Zotero.Promise.delay(100);
    if (!addon?.isActive || typeof Zotero.Scihub?.updateItem !== "function" ||
        Zotero.Scihub.isAutomaticPdfDownload()) throw new Error("Plugin preflight failed");
    await mark("ready", {zotero: Zotero.version, plugin: addon.version});
    const item = new Zotero.Item("journalArticle");
    item.setField("title", title);
    item.setField("DOI", doi);
    item.setField("url", "https://journals.plos.org/plosmedicine/article?id=" + doi);
    await item.saveTx();
    await mark("submitted", {item: item.key, attachmentsBefore: item.getAttachments().length});
    await Zotero.Scihub.updateItem(doi, item);
    await mark("plugin_returned", {attachmentCount: item.getAttachments().length});
    for (let i=0; i<40; i++) {
      for (const id of item.getAttachments()) {
        const a = Zotero.Items.get(id);
        const path = await a.getFilePathAsync();
        if (path && await IOUtils.exists(path)) {
          const header = await IOUtils.read(path, {maxBytes: 5});
          if (new TextDecoder().decode(header) === "%PDF-") {
            await mark("candidate_readable", {attachment: a.key, path});
            return;
          }
        }
      }
      await Zotero.Promise.delay(250);
    }
    throw new Error("Plugin returned without a readable PDF");
  } catch (err) { await mark("paused", {error: String(err)}); }
}
function startup() { setTimeout(() => run().catch(e => Zotero.logError(e)), 0); }
