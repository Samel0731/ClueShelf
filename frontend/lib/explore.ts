import { z } from "zod";
import { ApiError, platformSchema, saveSchema, searchModeSchema, type Platform, type SearchMode } from "./api";

export type BrowseFilters={q:string;mode:SearchMode;platform:Platform|"all";topics:string[];tags:string[]};
export const briefSaveSchema=z.object({id:z.string(),platform:platformSchema,title:z.string(),excerpt:z.string(),summary:z.string(),effective_topics:z.array(z.string()),effective_tags:z.array(z.string()),topic_ids:z.array(z.string()),tag_ids:z.array(z.string()),created_at:z.number(),updated_at:z.number(),version:z.number(),status:saveSchema.shape.status,extraction_status:saveSchema.shape.extraction_status,ai_status:saveSchema.shape.ai_status,duplicate_of:z.string().nullable(),url:z.string(),match_field:z.string(),match_text:z.string()});
export type BriefSave=z.infer<typeof briefSaveSchema>;
const facetSchema=z.object({id:z.string(),name:z.string(),count:z.number()});
export type TaxonFacet=z.infer<typeof facetSchema>;
const indexSchema=z.object({pending:z.number(),failed:z.number(),ready:z.number(),model_ready:z.boolean()});
export const browseSchema=z.object({items:z.array(briefSaveSchema),total:z.number(),next_cursor:z.string().nullable(),snapshot_id:z.string(),topics:z.array(facetSchema),tags:z.array(facetSchema),catalog_revision:z.string(),data_revision:z.string(),index:indexSchema,requested_mode:searchModeSchema,used_mode:searchModeSchema,notice:z.string().nullable()});
export type BrowseResponse=z.infer<typeof browseSchema>;
export function browseParams(filters:BrowseFilters){const params=new URLSearchParams({q:filters.q,mode:filters.mode,limit:"30"});if(filters.platform!=="all")params.set("platform",filters.platform);filters.topics.forEach(id=>params.append("topic",id));filters.tags.forEach(id=>params.append("tag",id));return params;}
export async function exploreRequest(path:string):Promise<unknown>{
  let response:Response;
  try{response=await fetch(`/api/v1${path}`,{cache:"no-store"});}catch{throw new ApiError("無法連線，請確認本機服務已啟動。",0);}
  const value:unknown=await response.json().catch(()=>null);
  if(!response.ok){const error=z.object({detail:z.string()}).safeParse(value);throw new ApiError(error.success?error.data.detail:"無法讀取收藏。",response.status);}
  return value;
}
export async function browseSaves(filters:BrowseFilters,options:{cursor?:string;snapshot_id?:string}={}){const params=browseParams(filters);if(options.cursor)params.set("cursor",options.cursor);if(options.snapshot_id)params.set("snapshot_id",options.snapshot_id);return browseSchema.parse(await exploreRequest(`/browse?${params}`));}
const updatesSchema=z.object({items:z.array(briefSaveSchema),deleted_ids:z.array(z.string()),total:z.number(),data_revision:z.string(),index:indexSchema});
export async function browseUpdates(ids:string[]){const params=new URLSearchParams();ids.forEach(id=>params.append("ids",id));return updatesSchema.parse(await exploreRequest(`/browse/status?${params}`));}
const scopedFacetsSchema=browseSchema.pick({topics:true,tags:true,total:true,catalog_revision:true,data_revision:true,index:true});
export async function browseFacets(snapshot_id:string){return scopedFacetsSchema.parse(await exploreRequest(`/browse/facets?${new URLSearchParams({snapshot_id})}`));}
