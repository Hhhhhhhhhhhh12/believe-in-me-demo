'use strict';
(() => {
  const base=new URL('./',document.currentScript.src);
  const storageKey='bim-private-browser-preview-v1';
  const nativeFetch=window.fetch.bind(window);
  let art={},commands=[],sequence=0,workerFailed=null;
  try{const saved=JSON.parse(sessionStorage.getItem(storageKey)||'[]');if(Array.isArray(saved)&&saved.length<=2000)commands=saved;}catch{}
  const worker=new Worker(new URL('worker.mjs',base),{type:'module'});
  const pending=new Map();
  function failAll(error){for(const item of pending.values()){clearTimeout(item.timer);item.reject(error);}pending.clear();}
  worker.onerror=event=>{workerFailed=new Error(event.message||'The browser engine could not start.');failAll(workerFailed);};
  worker.onmessage=event=>{
    const {id,result,error}=event.data;const item=pending.get(id);if(!item)return;
    clearTimeout(item.timer);pending.delete(id);
    if(error)item.reject(new Error(error));else item.resolve(result);
  };
  function request(kind,payload={}) {
    if(workerFailed)return Promise.reject(workerFailed);
    return new Promise((resolve,reject)=>{
      const id=++sequence;
      const timer=setTimeout(()=>{pending.delete(id);reject(new Error('The browser engine timed out.'));},150000);
      pending.set(id,{resolve,reject,timer});worker.postMessage({id,kind,payload});
    });
  }
  const mini=new URLSearchParams(location.search).get('mini')==='1';
  const ready=(async()=>{
    const response=await nativeFetch(new URL('art-map.json',base));
    if(!response.ok)throw new Error('The original artwork map could not be loaded.');
    art=await response.json();
    const state=await request('initialize',{commands,mini});
    if(!commands.length&&mini)commands=[{action:'start_mini',revision:0,starting_believers:6}];
    save();return state;
  })();
  function save(){try{sessionStorage.setItem(storageKey,JSON.stringify(commands));}catch{}}
  window.BimBrowser={base,art:key=>new URL(art[key]||`art/${key}`,base).href};
  window.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string' ? input : input.url||input,location.href);
    if(url.origin!==location.origin)return nativeFetch(input,options);
    if(!['/api/state','/api/action','/logout'].includes(url.pathname))return nativeFetch(input,options);
    try {
      await ready;
      if(url.pathname==='/logout'){commands=[];save();return Response.json({});}
      if(url.pathname==='/api/state')return Response.json(await request('state'));
      const payload=JSON.parse(options.body||'{}');
      if(payload.action==='start_mini')payload.starting_believers=6;
      const result=await request('action',payload);
      commands.push(payload);save();return Response.json(result);
    } catch(error){return Response.json({error:error.message||String(error)},{status:400});}
  };
})();
