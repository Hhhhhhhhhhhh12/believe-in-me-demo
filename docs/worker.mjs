import {loadPyodide} from './vendor/pyodide/pyodide.mjs';

let runtime;
let queue=Promise.resolve();
async function initialize(payload) {
  runtime=await loadPyodide({indexURL:new URL('./vendor/pyodide/',import.meta.url).href});
  const response=await fetch(new URL('./engine-bundle.json',import.meta.url));
  if(!response.ok)throw new Error('The local engine bundle could not be loaded.');
  const bundle=await response.json();
  for(const file of bundle.files) {
    if(!/^(engine\/|ui\/|data\/|bridge\.py$)/.test(file.path)||file.path.split('/').includes('..'))throw new Error('Invalid engine bundle path.');
    const target='/bim/'+file.path;
    runtime.FS.mkdirTree(target.slice(0,target.lastIndexOf('/')));
    runtime.FS.writeFile(target,Uint8Array.from(atob(file.content),char=>char.charCodeAt(0)));
  }
  runtime.FS.chdir('/bim');
  runtime.runPython('import sys\nsys.path.insert(0, "/bim")\nfrom bridge import browser_initialize, browser_action, browser_view\nimport json');
  const initialize=runtime.globals.get('browser_initialize');
  try{return JSON.parse(initialize(JSON.stringify(payload)));}finally{initialize.destroy();}
}
self.onmessage=event=>{
  const {id,kind,payload}=event.data;
  queue=queue.then(async()=>{
    try {
      let result;
      if(kind==='initialize')result=await initialize(payload);
      else if(kind==='state')result=JSON.parse(runtime.runPython('json.dumps(browser_view(), ensure_ascii=False)'));
      else if(kind==='action') {
        const action=runtime.globals.get('browser_action');
        try{result=JSON.parse(action(JSON.stringify(payload)));}finally{action.destroy();}
      } else throw new Error('Unknown local request.');
      self.postMessage({id,result});
    } catch(error){self.postMessage({id,error:String(error.message||error)});}
  });
};
