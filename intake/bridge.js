async function run() {
  const cfg=join(PathUtils.profileDir,"step4.json");
  if (!await IOUtils.exists(cfg)) return;
  const {root,jobs}=await IOUtils.readJSON(cfg);
  try {
    await Zotero.initializationPromise;
    if (Zotero.DataDirectory.dir.toLowerCase()!==join(root,"data").toLowerCase() ||
        PathUtils.profileDir.toLowerCase()!==join(root,"profile").toLowerCase())
      throw Error("Unexpected test profile");
    for (const name of jobs) {
      const out=join(root,name+"-receipt.json");
      if (!await IOUtils.exists(out)) await write(out,await bind(await IOUtils.readJSON(join(root,name+".json"))));
    }
  } catch(e) {await write(join(root,"error.json"),{error:String(e),stack:e.stack});}
}
function startup() {setTimeout(run,0);}
