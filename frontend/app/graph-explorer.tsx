"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Core, ElementDefinition, StylesheetJson } from "cytoscape";
import { z } from "zod";
import { errorMessage } from "../lib/api";
import { briefSaveSchema, browseSaves, exploreRequest, type BriefSave, type BrowseFilters, type BrowseResponse } from "../lib/explore";
import "./graph-explorer.css";

const nodeSchema = z.object({id:z.string(),kind:z.enum(["topic","tag","unclassified"]),label:z.string(),count:z.number()});
const graphSchema = z.object({nodes:z.array(nodeSchema),edges:z.array(z.object({id:z.string(),source:z.string(),target:z.string(),count:z.number()})),truncated:z.object({topics:z.boolean(),tags:z.boolean(),edges:z.boolean()}),data_revision:z.string()});
const expansionSchema = z.object({items:z.array(briefSaveSchema),total:z.number(),next_cursor:z.string().nullable()});
type GraphData = z.infer<typeof graphSchema>;
type GraphNode = z.infer<typeof nodeSchema>;
type Branch = z.infer<typeof expansionSchema>;
type Props = {scope:BrowseResponse;filters:BrowseFilters;onOpen:(id:string)=>void;onFilter:(kind:"topic"|"tag",id:string)=>void;revision:string;active:boolean;onScopeChanged:(scope:BrowseResponse)=>void;onReady:()=>void};
let lastOpenedGraph: { snapshot: string; graph: GraphData; branches: Record<string, Branch>; selected: string | null } | null = null;

const styles: StylesheetJson = [
  {selector:"node",style:{label:"data(label)","font-size":11,color:"#294b42","text-wrap":"ellipsis","text-max-width":"110px","text-valign":"bottom","text-margin-y":7,"border-width":2,"border-color":"#fffefa",width:"data(size)",height:"data(size)","background-color":"#8ba98b"}},
  {selector:'node[kind="topic"]',style:{shape:"hexagon","background-color":"#286557","font-weight":"bold"}},
  {selector:'node[kind="tag"]',style:{shape:"ellipse","background-color":"#8daa78"}},
  {selector:'node[kind="save"]',style:{shape:"round-rectangle","background-color":"#d2b57d",width:24,height:24}},
  {selector:'node[kind="unclassified"]',style:{shape:"diamond","background-color":"#a5aaa1"}},
  {selector:"node:selected",style:{"border-width":4,"border-color":"#e1b14f"}},
  {selector:"edge",style:{width:"data(width)","line-color":"#c7d4c0",opacity:0.55,"curve-style":"bezier"}},
];

function layout(cy:Core, fit:boolean) {
  cy.layout({name:"cose",animate:false,fit,padding:45,numIter:300,randomize:false,componentSpacing:80,nodeRepulsion:()=>8000,idealEdgeLength:()=>65}).run();
}

export default function GraphExplorer({scope,filters,onOpen,onFilter,revision,active,onScopeChanged,onReady}:Props) {
  const [graph,setGraph] = useState<GraphData|null>(null);
  const [branches,setBranches] = useState<Record<string,Branch>>({});
  const [selected,setSelected] = useState<string|null>(null);
  const [snapshot,setSnapshot] = useState(scope.snapshot_id);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const branchPanels=useRef(new Map<string,HTMLDivElement>());
  const container = useRef<HTMLDivElement>(null);
  const core = useRef<Core|null>(null);
  const generation = useRef(0);
  const opening = useRef(onOpen);
  const expandedRef = useRef(branches);
  const scopeRef = useRef(scope);
  const filtersRef = useRef(filters);
  const onScopeChangedRef=useRef(onScopeChanged);onScopeChangedRef.current=onScopeChanged;
  const initialized = useRef(false);
  const busyRef = useRef(false);
  opening.current = id => {
    if (graph) lastOpenedGraph = { snapshot, graph, branches, selected };
    onOpen(id);
  };
  expandedRef.current=branches; scopeRef.current=scope; filtersRef.current=filters;
  const filterKey=JSON.stringify(filters);

  const reload = useCallback(async (fresh=false) => {
    const token=++generation.current;
    setBusy(true);busyRef.current=true;setError("");setNotice("");
    try {
      const context=fresh?await browseSaves(filtersRef.current):scopeRef.current;
      const next=graphSchema.parse(await exploreRequest(`/graph?${new URLSearchParams({snapshot_id:context.snapshot_id})}`));
      if(token!==generation.current)return;
      if(fresh)onScopeChangedRef.current(context);
      if(lastOpenedGraph?.snapshot===context.snapshot_id)lastOpenedGraph=null;
      setSnapshot(context.snapshot_id);setGraph(next);setBranches({});setSelected(null);initialized.current=true;
    } catch(e){if(token===generation.current)setError(errorMessage(e));}
    finally{if(token===generation.current){setBusy(false);busyRef.current=false;}}
  },[]);

  useEffect(()=>{
    generation.current += 1;
    const saved = lastOpenedGraph?.snapshot === scopeRef.current.snapshot_id ? lastOpenedGraph : null;
    initialized.current = Boolean(saved);
    busyRef.current = false;
    setBusy(false);
    setGraph(saved?.graph ?? null);
    setBranches(saved?.branches ?? {});
    setSelected(saved?.selected ?? null);
    setSnapshot(scopeRef.current.snapshot_id);
    setError("");
  },[filterKey]);
  useEffect(() => { if (graph && active) onReady(); }, [active, graph, onReady]);
  useEffect(()=>{if(active&&!initialized.current&&!busyRef.current)void reload();},[active,filterKey,reload]);
  useEffect(()=>{if(active&&initialized.current&&snapshot!==scope.snapshot_id&&!busyRef.current)void reload();},[active,scope.snapshot_id,snapshot,busy,reload]);
  useEffect(()=>()=>{generation.current+=1;},[]);

  const collections=useMemo(()=>{
    const result=new Map<string,BriefSave>();
    Object.values(branches).forEach(branch=>branch.items.forEach(item=>result.set(item.id,item)));
    return result;
  },[branches]);
  const elements=useMemo(()=>{
    if(!graph)return [];
    const result:ElementDefinition[]=graph.nodes.map(node=>({data:{...node,size:Math.min(68,25+Math.sqrt(node.count)*2)}}));
    result.push(...graph.edges.map(edge=>({data:{...edge,width:Math.min(6,1+Math.sqrt(edge.count)/3)}})));
    collections.forEach(item=>result.push({data:{id:`save:${item.id}`,kind:"save",label:item.title||"尚未命名的收藏",size:24}}));
    Object.entries(branches).forEach(([parent,branch])=>branch.items.forEach(item=>result.push({data:{id:`member:${parent}:${item.id}`,source:parent,target:`save:${item.id}`,width:1}})));
    return result;
  },[graph,branches,collections]);

  useEffect(()=>{
    if(!container.current)return;
    let disposed=false;
    let observer:ResizeObserver|undefined;
    void import("cytoscape").then(({default:cytoscape})=>{
      if(disposed||!container.current)return;
      const cy=cytoscape({container:container.current,elements:[],style:styles,minZoom:0.15,maxZoom:3,wheelSensitivity:0.8,userZoomingEnabled:true,boxSelectionEnabled:false});
      core.current=cy;
      cy.on("tap","node",event=>{
        const identity:unknown=event.target.id();
        if(typeof identity!=="string")return;
        if(identity.startsWith("save:"))opening.current(identity.slice(5));
        else setSelected(identity);
      });
      observer=new ResizeObserver(()=>cy.resize());observer.observe(container.current);
      setRendererReady(true);
    }).catch(()=>{if(!disposed)setError("關係圖載入失敗，請重新整理頁面；仍可使用下方節點清單。");});
    return()=>{disposed=true;observer?.disconnect();core.current?.destroy();core.current=null;};
  },[]);
  const [rendererReady,setRendererReady]=useState(false);
  useEffect(()=>{
    const cy=core.current;
    if(!cy||!rendererReady)return;
    cy.batch(()=>{
      const wanted=new Set(elements.map(item=>item.data.id));
      cy.elements().forEach(item=>{if(!wanted.has(item.id()))item.remove();});
      for(const item of elements){const id=item.data.id;if(!id)continue;const existing=cy.getElementById(id);if(existing.empty())cy.add(item);else existing.data(item.data);}
    });
    if(elements.length)layout(cy,true);
  },[elements,rendererReady]);
  useEffect(()=>{if(active)core.current?.resize();},[active]);

  const expand=useCallback(async(node:GraphNode)=>{
    if(busyRef.current)return;
    const previous=expandedRef.current[node.id];
    if(previous&&!previous.next_cursor)return;
    const token=generation.current;
    busyRef.current=true;setBusy(true);setError("");setNotice("");
    try {
      const params=new URLSearchParams({snapshot_id:snapshot,node_id:node.id});
      if(previous?.next_cursor)params.set("cursor",previous.next_cursor);
      const next=expansionSchema.parse(await exploreRequest(`/graph/expand?${params}`));
      if(token!==generation.current)return;
      const known=new Set(Object.values(expandedRef.current).flatMap(branch=>branch.items.map(item=>item.id)));
      const extra=next.items.filter(item=>!known.has(item.id)).length;
      if(known.size+extra>150){setNotice("最多同時展示 150 筆收藏，請先收合其他分支後再展開。");return;}
      setBranches(current=>({...current,[node.id]:{...next,items:Array.from(new Map([...(current[node.id]?.items||[]),...next.items].map(item=>[item.id,item])).values())}}));
    }catch(e){if(token===generation.current)setError(errorMessage(e));}
    finally{if(token===generation.current){busyRef.current=false;setBusy(false);}}
  },[snapshot]);
  const nodesRef=useRef<GraphNode[]>([]);nodesRef.current=graph?.nodes||[];
  const expandRef=useRef(expand);expandRef.current=expand;
  useEffect(()=>{
    const node=nodesRef.current.find(item=>item.id===selected);
    if(node&&!expandedRef.current[node.id])void expandRef.current(node);
  },[selected]);

  function collapse(id:string){setBranches(current=>{const next={...current};delete next[id];return next;});setSelected(null);setNotice("");}
  const currentNode=graph?.nodes.find(node=>node.id===selected);
  const changed=!!graph&&revision!==graph.data_revision;
  return <section className="graph-explorer" aria-label="收藏關係圖">
    <div className="graph-toolbar"><div><h3>收藏之間的線索</h3><p>① 點主題或標籤　② 下方閱讀展開的收藏　③ 點收藏開啟內容。滾輪縮放、拖曳空白處移動。</p></div><button type="button" className="secondary" disabled={busy} onClick={()=>void reload(true)}>更新關係圖</button></div>
    <div className="graph-legend"><span>⬡ 主題</span><span>● 標籤</span><span>▰ 收藏</span><span>◇ 未分類</span></div>
    <p className="field-note">連線表示共同出現在收藏中，線越粗代表共同收藏越多。這不是因果、知識驗證或語意相似關係。</p>
    {changed&&<p className="notice warning" role="status">關係資料已更新。按「更新關係圖」查看新結果，目前視角會保留到你更新為止。</p>}
    {error&&<p className="notice error" role="alert">{error}<button className="text-button" onClick={()=>void reload(true)}>重新取得關係資料</button></p>}
    {notice&&<p className="notice warning" role="status">{notice}</p>}
    <div className="graph-stage"><div ref={container} className="graph-canvas" role="img" aria-label="主題、標籤與收藏的共現關係圖；可使用下方節點清單操作"/><div className="graph-controls"><button type="button" aria-label="放大關係圖" onClick={()=>{const cy=core.current;if(cy)cy.zoom({level:cy.zoom()*1.25,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});}}>＋</button><button type="button" aria-label="縮小關係圖" onClick={()=>{const cy=core.current;if(cy)cy.zoom({level:cy.zoom()/1.25,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});}}>−</button><button type="button" onClick={()=>core.current?.fit(undefined,45)}>重設視角</button></div>{busy&&<p className="graph-loading" role="status">正在整理關係圖…</p>}{graph&&!graph.nodes.length&&<p className="graph-loading">目前條件沒有可展示的收藏。</p>}</div>
    {graph&&<p className="field-note">顯示 {graph.nodes.filter(node=>node.kind==="topic").length} 個主題、{graph.nodes.filter(node=>node.kind==="tag").length} 個標籤、{collections.size} 筆收藏。概覽上限 20 個主題、40 個標籤及 120 條共現連線，展開收藏上限 150 筆。{graph.truncated.topics||graph.truncated.tags||graph.truncated.edges?"部分節點或連線未展示，可先用主題或標籤縮小範圍。":""}</p>}
    {currentNode&&<div className="graph-selection"><strong>{currentNode.label}</strong><span>{branches[currentNode.id]?`已展開 ${branches[currentNode.id].items.length}／${currentNode.count} 筆，見下方收藏分支`:"正在讀取收藏…"}</span>{currentNode.kind!=="unclassified"&&<button type="button" className="text-button" onClick={()=>{if(currentNode.kind!=="unclassified")onFilter(currentNode.kind,currentNode.id);}}>用此分類篩選</button>}{branches[currentNode.id]&&<button type="button" className="text-button" onClick={()=>collapse(currentNode.id)}>收合分支</button>}</div>}

    {Object.keys(branches).length>0&&<div className="branch-tabs" aria-label="已展開分類">{Object.keys(branches).map(id=><button type="button" key={id} aria-pressed={selected===id} onClick={()=>{setSelected(id);branchPanels.current.get(id)?.scrollIntoView({behavior:"smooth",block:"nearest"});}}>{graph?.nodes.find(node=>node.id===id)?.label} · {branches[id].items.length} 筆</button>)}</div>}
    {Object.entries(branches).map(([id,branch])=><div ref={element=>{if(element)branchPanels.current.set(id,element);else branchPanels.current.delete(id);}} className={`graph-branch ${selected===id?"active-branch":""}`} key={id}><div className="graph-branch-heading"><h4>{graph?.nodes.find(node=>node.id===id)?.label} · 已展開 {branch.items.length}／{branch.total} 筆收藏</h4><button className="text-button" onClick={()=>collapse(id)}>收合分支</button></div><ul>{branch.items.map(item=><li key={item.id}><button className="text-button" onClick={()=>opening.current(item.id)}>{item.title||"尚未命名的收藏"}</button></li>)}</ul>{branch.next_cursor&&<button className="secondary" disabled={busy} onClick={()=>{const node=graph?.nodes.find(node=>node.id===id);if(node)void expand(node);}}>＋ 再顯示 30 筆收藏</button>}</div>)}
    <details className="graph-accessible" open><summary>選一個分類展開收藏（亦支援鍵盤操作）</summary><div className="graph-node-list">{graph?.nodes.map(node=><div className={selected===node.id?"selected":""} key={node.id}><button type="button" className="text-button" disabled={busy} onClick={()=>{setSelected(node.id);if(!branches[node.id])void expand(node);}}>{node.kind==="topic"?"⬡":node.kind==="tag"?"●":"◇"} {node.label} <span>{node.count}</span></button>{branches[node.id]&&<button type="button" className="text-button" onClick={()=>collapse(node.id)}>收合</button>}</div>)}</div></details>
  </section>;
}
