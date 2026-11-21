let closing = false;
async function heartbeat(root,token) {
  let lastFocus;
  while (!closing) {
    try {
      await write(join(root,"hello.json"),{token,at:Date.now(),version:Zotero.version});
      const path=join(root,"focus.json");
      if(await IOUtils.exists(path)){
        const req=await IOUtils.readJSON(path);
        if(req.token===token && req.id!==lastFocus){
          const win=Zotero.getMainWindow();
          if(win){if(win.windowState===win.STATE_MINIMIZED)win.restore();win.focus();lastFocus=req.id;}
        }
      }
    }
    catch(e) {Zotero.logError(e);}
    await Zotero.Promise.delay(2000);
  }
}
async function serve() {
  const config = join(PathUtils.profileDir,"desktop.json");
  if (!await IOUtils.exists(config)) return;
  const {root,token} = await IOUtils.readJSON(config);
  await Zotero.initializationPromise;
  if (Zotero.DataDirectory.dir.toLowerCase() !== join(root,"data").toLowerCase()) return;
  const input = join(root,"request.json");
  heartbeat(root,token).catch(e=>Zotero.logError(e));
  while (!closing) {
    try {
      if (await IOUtils.exists(input)) {
        const request = await IOUtils.readJSON(input);
        const {id,op} = request;
        if (request.token !== token || !/^[a-f0-9]{32}$/.test(id)) throw Error("Invalid request");
        const reply=join(root,"replies",id+".json");
        const marker=join(root,"replies",id+".started");
        if (!await IOUtils.exists(reply)) {
          let result;
          try {
            if (request.batch_id && /^[a-f0-9]{32}$/.test(request.batch_id) &&
                await IOUtils.exists(join(root,"batches",request.batch_id,"aborted"))) throw Error("批次已中止");
            if (await IOUtils.exists(marker)) throw Error("上次请求中断，请核对附件后手动继续");
            await write(marker,{at:Date.now()});
            if (op==="bind") result=(await bind(request.batch)).rows[0];
            else if (op==="acquire") {
              const plugin=Zotero.Scihub;
              if (!plugin?.updateItem || plugin.isAutomaticPdfDownload()) throw Error("请检查下载插件及自动下载设置");
              const item=Zotero.Items.getByLibraryAndKey(Zotero.Libraries.userLibraryID,request.item);
              if (!item || item.getField("DOI").toLowerCase()!==request.doi) throw Error("目标条目 DOI 不一致");
              try { await plugin.updateItem(request.doi,item); }
              catch (e) {
                if (e.name==="PdfNotFoundError") result={missing:"not_found"};
                else {
                  if (/captcha|verification/i.test(String(e)))
                    Zotero.openInViewer(new URL(request.doi,plugin.getBaseScihubUrl()).href);
                  throw e;
                }
              }
              if (!result) {
                const candidates=[];
                for (const key of item.getAttachments()) {
                  const a=Zotero.Items.get(key);
                  if(a.attachmentContentType==="application/pdf") candidates.push({path:await a.getFilePathAsync()});
                }
                result={candidates};
              }
            } else throw Error("Unknown operation");
          } catch(e) {result={error:String(e)};}
          await write(reply,result);
        }
      }
    } catch(e) {Zotero.logError(e);}
    await Zotero.Promise.delay(350);
  }
}
function startup(){setTimeout(()=>serve().catch(e=>Zotero.logError(e)),0);}
function shutdown(){closing=true;}
