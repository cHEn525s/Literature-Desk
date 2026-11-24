const sampleDOI = "10.1371/journal.pmed.0020124";
function webAddress(value) {
  const url=new URL(value);
  if (!["http:","https:"].includes(url.protocol) || url.username || url.password)
    throw Error("请输入 HTTP 或 HTTPS 地址");
  return url;
}
async function handleSite(root,token) {
  const file=join(root,"site-request.json");
  if (!await IOUtils.exists(file)) return;
  const req=await IOUtils.readJSON(file);
  if(req.token!==token || !/^[a-f0-9]{32}$/.test(req.id) || req.until<Date.now()) return;
  const reply=join(root,"replies",req.id+".site.json");
  if(await IOUtils.exists(reply)) return;
  const plugin=Zotero.Scihub;
  let result;
  try {
    if(!plugin?.getBaseScihubUrl) throw Error("专用 Zotero 中没有启用下载插件");
    if(req.op==="current") result={address:plugin.getBaseScihubUrl()};
    else if(req.op==="select"){
      const address=webAddress(req.address).href;
      Zotero.Prefs.set("zoteroscihub.scihub_url",address);
      result={address:plugin.getBaseScihubUrl()};
      if(result.address!==address) throw Error("插件读回的地址不一致");
    } else if(req.op==="viewer"){
      const address=webAddress(req.address).href;
      Zotero.openInViewer(address);
      result={address};
    } else if(req.op==="probe"){
      const page=new URL(sampleDOI,webAddress(req.address));
      const xhr=await Zotero.HTTP.request("GET",page.href,{responseType:"document",noCache:true,successCodes:false,timeout:15000});
      const landing=webAddress(xhr.responseURL || page.href).href;
      const doc=xhr.responseXML;
      if(plugin.isCaptchaPage(doc?.querySelector("body"))) result={status:"需要人工验证",landing};
      else {
        if(xhr.status!==200) throw Error("论文页 HTTP "+xhr.status);
        const pdf=plugin.extractScihubPdfUrl(doc,landing);
        if(!pdf) throw Error("页面没有提供测试论文的 PDF");
        const res=await Zotero.HTTP.request("GET",webAddress(pdf).href,{responseType:"arraybuffer",noCache:true,successCodes:false,timeout:20000});
        if(res.status!==200) throw Error("PDF 请求 HTTP "+res.status);
        const bytes=new Uint8Array(res.response);
        if(String.fromCharCode(...bytes.slice(0,5))!=="%PDF-") throw Error("返回内容缺少 PDF 标识");
        await IOUtils.write(join(root,"replies",req.id+".probe.pdf"),bytes);
        result={status:"待核对测试论文",landing};
      }
    } else throw Error("站点操作无法识别");
  } catch(e){result={error:String(e)};}
  await write(reply,result);
}
let closing = false;
async function heartbeat(root,token) {
  let lastFocus;
  while (!closing) {
    try {
      await write(join(root,"hello.json"),{token,at:Date.now(),version:Zotero.version,sites:1});
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
      await handleSite(root,token);
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
                  if (/captcha|verification|verify that you are not a robot/i.test(String(e)))
                    result={error:"站点要求人工验证",verification:new URL(request.doi,plugin.getBaseScihubUrl()).href};
                  else throw e;
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

