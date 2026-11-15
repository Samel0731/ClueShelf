"use client";

import { useEffect, useState } from "react";
import { errorMessage, getSave } from "../lib/api";
import { applySuggestion, createTaxon, mergeTaxon, previewTaxon, readSuggestions, startSuggestions, templateNames, templateSchema, updateTaxon, type Catalog, type Suggestion, type Taxon, type TaxonomyPreview, type Template } from "../lib/taxonomy";

export default function TaxonomyManager({catalog,onChanged}:{catalog:Catalog|null;onChanged:()=>Promise<void>}){
  const [query,setQuery]=useState("");
  const [kind,setKind]=useState<Taxon["kind"]>("topic");
  const [editing,setEditing]=useState<Taxon|null>(null);
  const [name,setName]=useState("");
  const [description,setDescription]=useState("");
  const [template,setTemplate]=useState<Template>("generic");
  const [targetId,setTargetId]=useState("");
  const [preview,setPreview]=useState<TaxonomyPreview|null>(null);
  const [action,setAction]=useState<"edit"|"merge"|"archive"|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [suggestion,setSuggestion]=useState<Suggestion|null>(null);
  const [proposalIndex,setProposalIndex]=useState<number|null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [titles,setTitles]=useState<Record<string,string>>({});
  const [mergePreviews,setMergePreviews]=useState<TaxonomyPreview[]>([]);
  const proposal=proposalIndex===null?null:suggestion?.result?.[proposalIndex];
  useEffect(()=>{void readSuggestions().then(setSuggestion).catch(()=>undefined);},[]);
  useEffect(()=>{
    if(!suggestion || !["queued","running"].includes(suggestion.state))return;
    const timer=window.setInterval(()=>{void readSuggestions().then(setSuggestion).catch(e=>setError(errorMessage(e)));},3000);
    return()=>window.clearInterval(timer);
  },[suggestion]);
  useEffect(()=>{
    if(!proposal)return;
    let cancelled=false;
    void Promise.all(proposal.save_ids.map(async id=>{try{const save=await getSave(id);return {id,title:save.title||"尚未命名的收藏"};}catch{return {id,title:"收藏已移除或無法讀取"};}})).then(rows=>{if(!cancelled)setTitles(Object.fromEntries(rows.map(row=>[row.id,row.title])));});
    return()=>{cancelled=true;};
  },[proposal]);
  function edit(item:Taxon){setEditing(item);setKind(item.kind);setName(item.name);setDescription(item.description);setTemplate(item.template);setTargetId("");setAction(null);setPreview(null);setMessage("");setError("");}
  function reset(){setEditing(null);setName("");setDescription("");setTemplate("generic");setTargetId("");setAction(null);setPreview(null);}
  async function perform(operation:()=>Promise<unknown>,success:string){setBusy(true);setError("");try{await operation();await onChanged();reset();setMessage(success);return true;}catch(e){setError(errorMessage(e));return false;}finally{setBusy(false);}}
  async function prepare(next:"edit"|"merge"|"archive"){
    if(!editing)return;
    setBusy(true);setError("");
    try{const result=await previewTaxon(editing.id,next==="merge"?{target_id:targetId}:next==="edit"?{name}:{});setPreview(result);setAction(next);}
    catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function confirm(){
    if(!editing||!action)return;
    if(action==="merge"){
      const target=catalog?.items.find(item=>item.id===targetId);
      if(target)await perform(()=>mergeTaxon(editing,target),"分類已合併，舊名稱保留為別名。");
    }else if(action==="archive")await perform(()=>updateTaxon(editing.id,{version:editing.version,archived:!editing.archived}),editing.archived?"分類已恢復。":"分類已封存，既有收藏關聯保留。");
    else await perform(()=>updateTaxon(editing.id,{version:editing.version,name,description,template}),"分類已更新。");
  }
  const items=(catalog?.items||[]).filter(item=>!item.merged_into&&item.kind===kind&&(item.name.toLowerCase().includes(query.toLowerCase())||item.aliases.some(alias=>alias.toLowerCase().includes(query.toLowerCase()))));
  const targets=(catalog?.items||[]).filter(item=>item.kind===editing?.kind&&item.id!==editing?.id&&!item.merged_into&&!item.archived);
  return <section className="taxonomy-manager" aria-label="主題與標籤管理"><div className="taxonomy-body">
    <div className="taxonomy-layout"><section><div className="segmented"><button type="button" aria-pressed={kind==="topic"} onClick={()=>{reset();setKind("topic");}}>主題</button><button type="button" aria-pressed={kind==="tag"} onClick={()=>{reset();setKind("tag");}}>標籤</button></div><label className="sr-only" htmlFor="taxonomy-search">搜尋分類或別名</label><input id="taxonomy-search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜尋名稱或別名…"/><div className="taxonomy-list">{items.map(item=><button type="button" key={item.id} className={editing?.id===item.id?"selected":""} onClick={()=>edit(item)}><span>{item.name}{item.archived&&<small>已封存</small>}</span><span>{item.count} 則</span></button>)}{items.length===0&&<p className="field-note">沒有符合的分類。</p>}</div></section>
    <section className="taxonomy-form"><div className="section-heading"><h3>{editing?`編輯${kind==="topic"?"主題":"標籤"}`:`新增${kind==="topic"?"主題":"標籤"}`}</h3>{editing&&<button type="button" className="text-button" onClick={reset}>新增另一個</button>}</div><label htmlFor="taxonomy-name">名稱</label><input id="taxonomy-name" maxLength={60} value={name} onChange={e=>{setName(e.target.value);setAction(null);}} disabled={busy}/>{kind==="topic"&&<><label htmlFor="taxonomy-description">說明，供 AI 分類參考</label><textarea id="taxonomy-description" rows={3} maxLength={1000} value={description} onChange={e=>{setDescription(e.target.value);setAction(null);}} disabled={busy}/><label htmlFor="taxonomy-template">推薦展示</label><select id="taxonomy-template" value={template} onChange={e=>{const next=templateSchema.safeParse(e.target.value);if(next.success)setTemplate(next.data);setAction(null);}}>{templateSchema.options.map(value=><option key={value} value={value}>{templateNames[value]}</option>)}</select></>}
      {editing&&<p className="field-note">{editing.count} 則收藏{editing.aliases.length?` · 別名：${editing.aliases.join("、")}`:""}。人工分類與原始 AI 分析會保留。</p>}
      <div className="edit-actions"><button type="button" className="primary" disabled={busy||!name.trim()} onClick={()=>editing?void prepare("edit"):void perform(()=>createTaxon({kind,name,description,template}),"分類已建立，可在收藏內容中使用。")}>{editing?"預覽修改":"建立分類"}</button>{editing&&<button type="button" className="text-button" disabled={busy} onClick={()=>void prepare("archive")}>{editing.archived?"恢復分類":"封存分類"}</button>}</div>
      {editing&&!editing.archived&&<div className="taxonomy-merge"><label htmlFor="taxonomy-target">合併至</label><select id="taxonomy-target" value={targetId} onChange={e=>{setTargetId(e.target.value);setAction(null);}}><option value="">選擇要保留的分類</option>{targets.map(item=><option key={item.id} value={item.id}>{item.name}（{item.count}）</option>)}</select><button type="button" className="secondary" disabled={busy||!targetId} onClick={()=>void prepare("merge")}>預覽合併</button></div>}
      {preview&&action&&<div className="taxonomy-preview"><strong>{action==="merge"?`合併「${editing?.name}」至「${preview.target?.name||targets.find(item=>item.id===targetId)?.name}」`:action==="archive"?editing?.archived?"恢復此分類":"封存此分類":`修改為「${name}」`}</strong><p>影響 {preview.count} 則收藏。{action==="merge"?"舊名稱會成為別名，這項合併不能直接拆回。":""}</p><ul>{preview.saves.map(save=><li key={save.id}>{save.title||"尚未命名的收藏"}</li>)}</ul><div className="edit-actions"><button type="button" className="primary" disabled={busy} onClick={()=>void confirm()}>確認{action==="merge"?"合併":action==="archive"?editing?.archived?"恢復":"封存":"修改"}</button><button type="button" className="text-button" disabled={busy} onClick={()=>setAction(null)}>取消</button></div></div>}
    </section></div>
    <section className="taxonomy-suggestions"><div className="explorer-heading"><div><h3>讓 AI 提議整理</h3><p>依近期收藏樣本提出建議，不會自動套用。先查看原因與相關收藏，再確認。</p></div><button type="button" className="secondary" disabled={busy||!!suggestion&&["queued","running"].includes(suggestion.state)} onClick={()=>{setBusy(true);setError("");void startSuggestions().then(result=>{setSuggestion(result);setProposalIndex(null);}).catch(e=>setError(errorMessage(e))).finally(()=>setBusy(false));}}>請 AI 建議整理</button></div>
      {suggestion&&["queued","running"].includes(suggestion.state)&&<p className="notice warning" role="status">{suggestion.state==="queued"?"已排入 AI 工作，會與其他整理工作依序執行。":"AI 正在檢視分類線索…"}</p>}{suggestion?.error&&<p className="notice error">{suggestion.error}</p>}
      {suggestion?.result&&suggestion.result.length===0&&<p className="field-note">這次沒有需要新增或合併的分類建議。</p>}
      {suggestion?.result?.map((item,index)=>suggestion.applied.includes(index)?null:<div className="suggestion-row" key={`${item.kind}-${index}`}><div><strong>{item.kind==="new_topic"?`新增主題：${item.name}`:`合併建議：${item.name}`}</strong><p>{item.reason}</p><small>{item.save_ids.length} 則相關收藏</small></div><button type="button" className="text-button" onClick={()=>{setProposalIndex(index);setSelected([]);setTitles({});setMergePreviews([]);}}>查看與選取</button></div>)}
      {proposal&&proposalIndex!==null&&suggestion&&<div className="taxonomy-preview"><h4>{proposal.name}</h4><p>{proposal.description}</p><p className="field-note">勾選要套用的收藏。{proposal.kind==="new_topic"?"請至少勾選一筆收藏；只要建立空主題時，使用上方新增功能。":"分類合併會影響該分類全部收藏，確認前請查看合併預覽。"}</p><div className="proposal-saves">{proposal.save_ids.map(id=><label key={id}><input type="checkbox" checked={selected.includes(id)} onChange={()=>setSelected(current=>current.includes(id)?current.filter(value=>value!==id):[...current,id])}/><span>{titles[id]||"正在讀取收藏標題…"}</span></label>)}</div>{proposal.kind==="merge"?<><button type="button" className="secondary" disabled={busy} onClick={()=>{setBusy(true);setError("");void Promise.all(proposal.source_ids.map(id=>previewTaxon(id,{target_id:proposal.target_id||undefined}))).then(setMergePreviews).catch(e=>setError(errorMessage(e))).finally(()=>setBusy(false));}}>預覽整組合併</button>{mergePreviews.length>0&&<div className="merge-proposal-preview">{mergePreviews.map(value=><div key={value.source.id}><strong>「{value.source.name}」→「{value.target?.name}」</strong><p>影響 {value.count} 則收藏</p><ul>{value.saves.map(save=><li key={save.id}>{save.title||"尚未命名的收藏"}</li>)}</ul></div>)}<p className="field-note">確認後將合併上述分類的全部關聯，保留舊名稱別名，不能直接拆回。</p><button type="button" className="primary" disabled={busy} onClick={()=>void perform(()=>applySuggestion(suggestion.id,proposalIndex,[]),"分類合併建議已套用。").then(async success=>{if(success){setProposalIndex(null);setMergePreviews([]);setSuggestion(await readSuggestions());}})}>確認整組合併</button></div>}</>:<button type="button" className="primary" disabled={busy||selected.length===0} onClick={()=>{if(proposalIndex!==null)void perform(()=>applySuggestion(suggestion.id,proposalIndex,selected),"建議已套用。未選取的收藏維持原分類。").then(async success=>{if(success){setProposalIndex(null);setSuggestion(await readSuggestions());}});}}>確認建立主題{selected.length?`並套用 ${selected.length} 則`:""}</button>}<button type="button" className="text-button" onClick={()=>setProposalIndex(null)}>關閉建議</button></div>}
    </section>{error&&<p className="notice error" role="alert">{error}</p>}{message&&<p className="notice success" role="status">{message}</p>}
  </div></section>;
}
