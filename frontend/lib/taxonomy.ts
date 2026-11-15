import { z } from "zod";
import { ApiError } from "./api";

export const templateSchema = z.enum(["generic", "recipe", "restaurant", "travel", "music", "resources", "event"]);
export const taxonSchema = z.object({id:z.string(),kind:z.enum(["topic","tag"]),name:z.string(),description:z.string(),template:templateSchema,archived:z.boolean(),merged_into:z.string().nullable(),version:z.number().int(),count:z.number().int(),aliases:z.array(z.string())});
export type Taxon = z.infer<typeof taxonSchema>;
export type Template = z.infer<typeof templateSchema>;
const catalogSchema=z.object({items:z.array(taxonSchema),version:z.string()});
export type Catalog=z.infer<typeof catalogSchema>;
const previewSchema=z.object({count:z.number(),saves:z.array(z.object({id:z.string(),title:z.string()})),source:taxonSchema,target:taxonSchema.nullable().optional()});
export type TaxonomyPreview=z.infer<typeof previewSchema>;
const proposalSchema=z.object({kind:z.enum(["new_topic","merge"]),name:z.string(),description:z.string(),source_ids:z.array(z.string()),target_id:z.string().nullable(),save_ids:z.array(z.string()),reason:z.string()});
const suggestionSchema=z.object({id:z.string(),state:z.string(),error:z.string().nullable(),result:z.array(proposalSchema).nullable(),applied:z.array(z.number()).default([])});
export type Suggestion=z.infer<typeof suggestionSchema>;
export const templateNames:Record<Template,string>={generic:"通用卡片",recipe:"食譜卡",restaurant:"店家收藏卡",travel:"旅行卡",music:"音樂清單",resources:"資源清單",event:"活動卡"};

async function request(path:string,body?:unknown,method="POST"):Promise<unknown>{
  let response:Response;
  try{response=await fetch(`/api/v1/taxonomy${path}`,{method:body===undefined?"GET":method,cache:"no-store",headers:{"Content-Type":"application/json"},...(body===undefined?{}:{body:JSON.stringify(body)})});}
  catch{throw new ApiError("無法連線，請確認本機服務已啟動。",0);}
  const value:unknown=await response.json().catch(()=>null);
  if(!response.ok){const error=z.object({detail:z.string()}).safeParse(value);throw new ApiError(error.success?error.data.detail:"分類操作未完成。",response.status);}
  return value;
}
export async function getCatalog(){return catalogSchema.parse(await request(""));}
export async function createTaxon(input:{kind:Taxon["kind"];name:string;description?:string;template?:Template}){return taxonSchema.parse(await request("",input));}
export async function updateTaxon(id:string,input:{version:number;name?:string;description?:string;template?:Template;archived?:boolean}){return taxonSchema.parse(await request(`/${encodeURIComponent(id)}`,input,"PATCH"));}
export async function previewTaxon(id:string,input:{name?:string;target_id?:string}){return previewSchema.parse(await request(`/${encodeURIComponent(id)}/preview`,input));}
export async function mergeTaxon(source:Taxon,target:Taxon){return taxonSchema.parse(await request(`/${encodeURIComponent(source.id)}/merge`,{version:source.version,target_id:target.id,target_version:target.version}));}
export async function startSuggestions(){return suggestionSchema.parse(await request("/suggestions",{}));}
export async function readSuggestions(){return suggestionSchema.nullable().parse(await request("/suggestions"));}
export async function applySuggestion(id:string,proposal_index:number,save_ids:string[]){return z.object({applied:z.number(),taxon:taxonSchema}).parse(await request(`/suggestions/${encodeURIComponent(id)}/apply`,{proposal_index,save_ids}));}
