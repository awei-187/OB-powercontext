export function splitText(text,source) {
  const clean=text.replace(/\r\n/g,'\n').trim(), out=[];
  // Conservative character limit keeps Chinese segments below the 256 token budget, with 24 char overlap.
  for(let i=0;i<clean.length;i+=196) {
    const part=clean.slice(i,i+220).trim(); if(part) out.push({text:part,source,chunk:out.length});
    if(i+220>=clean.length) break;
  }
  return out;
}
export async function docId(d) {
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(d.source+'\0'+d.chunk+'\0'+d.text));
  return Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
}
export function quality(ids,relevance,k=5) {
  const relevant=Object.entries(relevance).filter(([,g])=>g>0);
  const top=ids.slice(0,k), hits=top.filter(x=>(relevance[x]||0)>0).length;
  const dcg=top.reduce((s,x,i)=>s+(2**(relevance[x]||0)-1)/Math.log2(i+2),0);
  const ideal=relevant.map(([,g])=>g).sort((a,b)=>b-a).slice(0,k).reduce((s,g,i)=>s+(2**g-1)/Math.log2(i+2),0);
  return {recall:hits/(relevant.length||1),ndcg:ideal?dcg/ideal:0};
}
