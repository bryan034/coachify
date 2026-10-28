/** Only saved, public HTTP URLs may become citations. No inferred source domains. */
export function sourceLink(value:string){
 try{const url=new URL(value);if(!['https:','http:'].includes(url.protocol)||url.username||url.password)return null;
  return {url:url.href,domain:url.hostname.replace(/^www\./i,'')};
 }catch{return null;}
}
export function sourceCitations(ids:string[],sources:{source_id:string;url:string}[]){
 const urls=new Set<string>();
 for(const id of ids){const source=sources.find(item=>item.source_id===id),link=source&&sourceLink(source.url);if(link)urls.add(link.url);}
 return [...urls].map(url=>`[${sourceLink(url)!.domain}](<${url}>)`).join(' ');
}
