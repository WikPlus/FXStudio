const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('fxDesktop', {
  copyAgentSkill:()=>ipcRenderer.invoke('copy-agent-skill'),
  agentAction:(action)=>ipcRenderer.invoke('agent-action',action),
  exportAudio:(id,format,name)=>ipcRenderer.invoke('export-audio',{id,format,name}),
  reveal:(id)=>ipcRenderer.invoke('reveal-audio',id),
  openLicense:(id)=>ipcRenderer.invoke('open-license',id),
  openBundledLicenses:()=>ipcRenderer.invoke('open-bundled-licenses'),
  openLink:(url)=>ipcRenderer.invoke('open-link',url),
  prepareDrag:(id)=>ipcRenderer.invoke('prepare-drag',id),
  startDrag:(ticket)=>ipcRenderer.send('start-drag',ticket),
  onDragError:(callback)=>{const listener=(_event,message)=>callback(message);ipcRenderer.on('drag-error',listener);return ()=>ipcRenderer.removeListener('drag-error',listener)}
});
