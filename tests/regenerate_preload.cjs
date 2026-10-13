const {contextBridge}=require('electron');
const fs=require('fs'),path=require('path');
let deletionCalls=0;
contextBridge.exposeInMainWorld('fxDesktop',{
  onDragError:()=>{},
  deletionTestState:()=>deletionCalls,
  deleteProject:async id=>{deletionCalls++;if(deletionCalls===1)return {cancelled:true};const headers={'X-FX-Token':process.env.FX_SESSION_TOKEN};const plan=await (await fetch(process.env.FX_UI_TEST_URL+'/api/project-deletion?project_id='+id,{headers})).json();const r=await fetch(process.env.FX_UI_TEST_URL+'/api/project-delete',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({project_id:id,confirm_name:plan.name,revision:plan.revision})});const data=await r.json();if(!r.ok)throw new Error(data.error);return data;},
  exportAudio:async(id,format)=>{const r=await fetch(process.env.FX_UI_TEST_URL+'/api/export/'+id+'?format='+format,{headers:{'X-FX-Token':process.env.FX_SESSION_TOKEN}});if(!r.ok)throw new Error((await r.json()).error);const target=path.join(process.env.FX_UI_TEST_OUTPUT,'ui-export.'+format);fs.writeFileSync(target,Buffer.from(await r.arrayBuffer()));return {path:target};},
  prepareDrag:async id=>{const r=await fetch(process.env.FX_UI_TEST_URL+'/api/prepare-drag/'+id,{method:'POST',headers:{'X-FX-Token':process.env.FX_SESSION_TOKEN,'Content-Type':'application/json'},body:'{}'});const data=await r.json();if(!r.ok)throw new Error(data.error);return {ticket:data.path,format:data.format};}
});
