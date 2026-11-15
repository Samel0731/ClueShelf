"use client";

import { useEffect, useState } from "react";
import { type TaxonFacet } from "../lib/explore";

export default function TagCloud({tags,selected,onSelect,preparing}:{tags:TaxonFacet[];selected:string[];onSelect:(id:string)=>void;preparing:boolean}){
  const [expanded,setExpanded]=useState(false);
  const [query,setQuery]=useState("");
  const [mode,setMode]=useState<"cloud"|"list">("cloud");
  useEffect(()=>{setMode(window.matchMedia("(max-width: 720px)").matches?"list":"cloud");},[]);
  const matching=tags.filter(tag=>tag.name.normalize("NFKC").toLocaleLowerCase().includes(query.normalize("NFKC").trim().toLocaleLowerCase()));
  const visible=matching.slice(0,expanded||query.trim()?60:12);
  const maximum=Math.max(1,...visible.map(tag=>tag.count));
  return <section className="tag-explorer" aria-labelledby="tag-explorer-title"><div className="explorer-heading"><div><h3 id="tag-explorer-title">瀏覽標籤</h3><p>選擇標籤後，會在收藏庫顯示相關收藏。</p></div><div className="segmented" aria-label="標籤展示方式"><button type="button" aria-pressed={mode==="cloud"} onClick={()=>setMode("cloud")}>文字雲</button><button type="button" aria-pressed={mode==="list"} onClick={()=>setMode("list")}>依數量排列</button></div></div>
    <input className="tag-search" aria-label="尋找標籤" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder={`尋找目前範圍的 ${tags.length} 個標籤…`}/>{visible.length===0?<p className="field-note">找不到標籤，試試縮短標籤名稱。</p>:<div className={mode==="cloud"?"word-cloud":"tag-count-list"}>{visible.map(tag=><button type="button" key={tag.id} title={`${tag.name} · ${tag.count} 則收藏`} aria-label={`${tag.name}，${tag.count} 則收藏`} className={selected.includes(tag.id)?"selected":""} style={mode==="cloud"?{fontSize:`${12+18*Math.sqrt(tag.count/maximum)}px`}:undefined} onClick={()=>onSelect(tag.id)}><span>{tag.name}</span><small>{tag.count}</small></button>)}</div>}
    <div className="tag-explorer-footer">{matching.length>12&&!query.trim()&&<button type="button" className="text-button" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?"收起標籤":"探索更多標籤 ＋"}</button>}<p className="field-note">{matching.length>60?`依收藏數顯示前 ${visible.length} 個，共 ${matching.length} 個標籤。`:"每筆收藏對同一標籤只計一次。"}{preparing?" AI 分類仍在更新。":""}</p></div>
  </section>;
}
