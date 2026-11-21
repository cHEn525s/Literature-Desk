const join = (...args) => PathUtils.join(...args);
const write = (path, data) => IOUtils.writeJSON(path,data,{tmpPath:path+".tmp"});

async function ensureCollection(name,parent) {
  const libraryID=Zotero.Libraries.userLibraryID;
  const siblings=parent ? Zotero.Collections.getByParent(parent.id) : Zotero.Collections.getByLibrary(libraryID);
  let c=siblings.find(c=>!c.deleted && c.name===name && (parent || !c.parentID));
  if (!c) {
    c=new Zotero.Collection();
    c.libraryID=libraryID;
    c.name=name;
    if (parent) c.parentID=parent.id;
    await c.saveTx();
  }
  return c;
}

async function bind(batch) {
  const parent=await ensureCollection(batch.parent);
  const groups=new Map();
  for (const s of batch.sources) groups.set(s.group,await ensureCollection(s.group,parent));
  const items=(await Zotero.Items.getAll(Zotero.Libraries.userLibraryID,true)).filter(i=>i.isRegularItem());
  const byTag=new Map();
  for (const i of items) for (const {tag} of i.getTags()) byTag.set(tag,i);
  const rows=[];
  for (const w of batch.works) {
    const tag="intake:"+w.work_id;
    let item=byTag.get(tag);
    if (!item && !w.review) {
      const matching=items.filter(i=>{
        const doi=i.getField("DOI").toLowerCase();
        const pmid=i.getField("extra").match(/^PMID:\s*(\d+)\s*$/im)?.[1];
        return (w.doi && doi===w.doi) || (w.pmid && pmid===w.pmid);
      });
      if (matching.length) {
        const c=matching[0], oldDOI=c.getField("DOI").toLowerCase();
        const oldPMID=c.getField("extra").match(/^PMID:\s*(\d+)\s*$/im)?.[1];
        const titleKey=s=>s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu,"");
        if (matching.length>1 || (oldDOI && w.doi && oldDOI!==w.doi) ||
            (oldPMID && w.pmid && oldPMID!==w.pmid) ||
            titleKey(c.getField("title"))!==titleKey(w.title)) {
          rows.push({work_id:w.work_id,review:"library_identity_conflict"});
          continue;
        }
        item=c;
      }
    }
    if (!item) {
      item=new Zotero.Item("journalArticle");
      for (const [key,value] of Object.entries({title:w.title,DOI:w.doi,date:w.year,
        publicationTitle:w.journal,url:w.url,extra:w.pmid ? "PMID: "+w.pmid : ""}))
        if (value) item.setField(key,value);
      if (w.author) item.setCreators(w.author.split(/\s+and\s+/i).map(name=>
        ({creatorType:"author",name:name.trim()})));
      items.push(item);
    }
    item.addTag(tag);
    for (const g of w.groups) item.addToCollection(groups.get(g).id);
    await item.saveTx();
    byTag.set(tag,item);
    if (w.local_pdf && !item.getAttachments().length)
      await Zotero.Attachments.importFromFile({parentItemID:item.id,file:w.local_pdf.path});
    const candidates=[];
    for (const id of item.getAttachments()) {
      const a=Zotero.Items.get(id);
      if (a.attachmentContentType==="application/pdf")
        candidates.push({key:a.key,path:await a.getFilePathAsync()});
    }
    rows.push({work_id:w.work_id,item:item.key,review:w.review,
      groups:item.getCollections().map(id=>Zotero.Collections.get(id).key),candidates});
  }
  return {parent:parent.key,groupKeys:Object.fromEntries([...groups].map(([g,c])=>[g,c.key])),rows};
}

