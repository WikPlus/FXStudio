const {app,BrowserWindow,ipcMain,dialog,shell,session,Menu,systemPreferences,nativeImage,clipboard}=require('electron');
const {spawn}=require('child_process');
const {join,resolve,relative,isAbsolute,sep}=require('path');
const fs=require('fs');
const crypto=require('crypto');
const root=join(__dirname,'..');
const bundledPython=join(root,process.platform==='win32'?'python/python.exe':'python/bin/python3');
const standalone=fs.existsSync(bundledPython);
const agentPython=standalone?bundledPython:join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
const base='http://127.0.0.1:3921';
let service,win,quitting=false;
const token=crypto.randomBytes(32).toString('hex');
app.setName('FX Studio');
if(process.env.FX_DATA_DIR)app.setPath('userData',resolve(process.env.FX_DATA_DIR));
// App-specific language, including native save panels; no global macOS change.
if(process.platform==='darwin')systemPreferences.setUserDefault('AppleLanguages','array',['en']);
app.commandLine.appendSwitch('lang','en-US');
app.commandLine.appendSwitch('force-renderer-accessibility');
const isPrimary=app.requestSingleInstanceLock();
if(!isPrimary) app.quit();
app.on('second-instance',()=>{if(win){win.show();win.focus()}});
async function boot(){
  const python=standalone?bundledPython:join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
  if(!fs.existsSync(python))throw new Error(standalone?'The bundled Python runtime is missing. Reinstall FX Studio; your saved sounds are retained.':'The Python runtime is missing. Run '+(process.platform==='win32'?'Build-Windows.ps1':'Einrichten.command')+' in the FX Studio folder.');
  if(process.env.FX_PORT && process.env.FX_PORT!=='3921')throw new Error('The desktop app uses local port 3921. Remove FX_PORT from the launch environment.');
  const logDir=process.env.FX_DATA_DIR?resolve(process.env.FX_DATA_DIR):join(process.platform==='win32'?(process.env.LOCALAPPDATA||app.getPath('appData')):app.getPath('appData'),'FX Studio');fs.mkdirSync(logDir,{recursive:true});
  const log=fs.openSync(join(logDir,'service.log'),'a');
  let spawnError;
  const serviceEnv={...process.env,FX_PORT:'3921',FX_SESSION_TOKEN:token,FX_DATA_DIR:logDir,FX_AUTO_SETUP:'1',HF_HUB_DISABLE_TELEMETRY:'1',DO_NOT_TRACK:'1',PYTHONDONTWRITEBYTECODE:'1',PYTHONNOUSERSITE:'1'};
  if(standalone){
    delete serviceEnv.PYTHONHOME;delete serviceEnv.PYTHONPATH;delete serviceEnv.PYTHONPYCACHEPREFIX;
    serviceEnv.FX_PACKAGED_RUNTIME='1';
    serviceEnv.FX_MODEL_DIR=join(logDir,process.platform==='win32'?'models/tflite':'models/mlx');
    serviceEnv.FX_FFMPEG_PATH=join(root,process.platform==='win32'?'tools/ffmpeg.exe':'tools/ffmpeg');
  }
  service=spawn(python,['-s','-B',join(root,'backend/server.py')],{cwd:root,env:serviceEnv,stdio:['ignore',log,log],windowsHide:true});
  fs.closeSync(log);
  service.on('error',error=>{spawnError=error});
  let ready=false;
  const deadline=Date.now()+20000;
  while(Date.now()<deadline){
    if(spawnError)throw spawnError;
    if(service.exitCode!==null || service.signalCode!==null)throw new Error('The local service could not start. Port 3921 may be in use. Details: '+join(logDir,'service.log'));
    try{
      const r=await fetch(base+'/api/status',{headers:{'X-FX-Token':token},signal:AbortSignal.timeout(1000)});
      if(r.ok){const data=await r.json();if(data.service==='fx-studio' && data.ready===true){ready=true;break;}}
    }catch{}
    await new Promise(r=>setTimeout(r,150));
  }
  if(!ready)throw new Error('The local service did not become ready within 20 seconds. Check '+join(logDir,'service.log')+' and restart FX Studio.');
  await session.defaultSession.cookies.set({url:base,name:'fx_session',value:token,httpOnly:true,sameSite:'strict'});
  session.defaultSession.setPermissionRequestHandler((_,__,callback)=>callback(false));
  win=new BrowserWindow({width:1260,height:920,minWidth:920,minHeight:700,title:'FX Studio',backgroundColor:'#181a1d',...(process.platform==='darwin'?{titleBarStyle:'hiddenInset',trafficLightPosition:{x:18,y:17}}:{}),webPreferences:{preload:join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:false}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',(e,url)=>{if(!url.startsWith(base+'/'))e.preventDefault()});
  await win.loadURL(base+'/');
}
function safeId(id){if(typeof id!=='string'||!/^([a-f0-9]{12}|SFX\d+)$/.test(id))throw new Error('Invalid audio selection');return id;}
function trusted(event){if(event.sender!==win?.webContents || new URL(event.senderFrame.url).origin!==base)throw new Error('Request not authorized');}
ipcMain.handle('copy-agent-skill',event=>{
  trusted(event);
  let skill;
  try{skill=fs.readFileSync(join(root,'ui/skills/fx-studio/SKILL.md'),'utf8')}catch{throw new Error('The agent skill could not be read. Reinstall or rebuild FX Studio.');}
  if(!skill.trim())throw new Error('The agent skill file is empty. Reinstall or rebuild FX Studio.');
  clipboard.writeText(skill);
  return {characters:skill.length};
});
async function agentSettings(values){
  const response=await fetch(base+'/api/agents',{method:values?'POST':'GET',headers:{'X-FX-Token':token,'Content-Type':'application/json'},...(values?{body:JSON.stringify(values)}:{})});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Agent settings could not be updated.');return data;
}
ipcMain.handle('agent-action',async(event,action)=>{
  trusted(event);
  if(action==='enable'||action==='disable')return agentSettings({enabled:action==='enable'});
  if(action==='export-folder'){
    const settings=await agentSettings();
    const pick=await dialog.showOpenDialog(win,{title:'Choose the folder for agent exports',defaultPath:fs.existsSync(settings.export_root)?settings.export_root:app.getPath('documents'),properties:['openDirectory','createDirectory']});
    if(pick.canceled)return {cancelled:true};return agentSettings({export_root:pick.filePaths[0]});
  }
  if(action==='copy-config'||action==='copy-codex'){
    const config={command:agentPython,args:['-s','-B',join(root,'backend/mcp_server.py')]};
    const text=action==='copy-codex'?'[mcp_servers.fx_studio]\ncommand = '+JSON.stringify(config.command)+'\nargs = '+JSON.stringify(config.args)+'\nstartup_timeout_sec = 20\ntool_timeout_sec = 120\n':JSON.stringify({mcpServers:{fx_studio:config}},null,2);
    clipboard.writeText(text);return {copied:true};
  }
  if(action==='copy-key'){
    const response=await fetch(base+'/api/agent-credentials',{headers:{'X-FX-Token':token}});
    if(!response.ok)throw new Error('The local API key is unavailable.');
    const data=await response.json();clipboard.writeText(data.token);return {copied:true};
  }
  if(action==='rotate-key')return agentSettings({rotate:true});
  if(action==='install-skill'){
    const choice=await dialog.showMessageBox(win,{type:'question',title:'Install FX Studio skill',message:'Choose your local agent',detail:'Install directly for Codex, or choose another agent’s skills folder. Start a new agent conversation after installation.',buttons:['Codex','Choose skills folder…','Cancel'],defaultId:0,cancelId:2});
    if(choice.response===2)return {cancelled:true};
    let folder=join(app.getPath('home'),'.codex/skills');
    if(choice.response===1){
      const pick=await dialog.showOpenDialog(win,{title:'Choose your local agent’s skills folder',defaultPath:app.getPath('home'),properties:['openDirectory','createDirectory','showHiddenFiles']});
      if(pick.canceled)return {cancelled:true};folder=pick.filePaths[0];
    }
    fs.mkdirSync(folder,{recursive:true});
    const target=join(folder,'fx-studio'),source=join(root,'ui/skills/fx-studio');
    if(fs.existsSync(target)){
      if(fs.lstatSync(target).isSymbolicLink())throw new Error('The installed skill is a symbolic link. Choose a different skills folder.');
      const same=fs.existsSync(join(target,'SKILL.md'))&&fs.readFileSync(join(target,'SKILL.md')).equals(fs.readFileSync(join(source,'SKILL.md')))&&fs.existsSync(join(target,'scripts/fxstudio.py'))&&fs.readFileSync(join(target,'scripts/fxstudio.py')).equals(fs.readFileSync(join(source,'scripts/fxstudio.py')));
      if(same)return {path:target};
      const backup=join(process.platform==='win32'?(process.env.LOCALAPPDATA||app.getPath('appData')):app.getPath('appData'),'FX Studio','skill-backups',String(Date.now()));
      fs.mkdirSync(backup,{recursive:true});fs.cpSync(target,backup,{recursive:true});
    }
    fs.cpSync(source,target,{recursive:true,force:true});
    return {path:target};
  }
  if(action==='save-kit'){
    const pick=await dialog.showSaveDialog(win,{title:'Save the local agent kit',defaultPath:join(app.getPath('downloads'),'FX-Studio-Agent-Kit.zip'),filters:[{name:'Agent kit',extensions:['zip']}]});
    if(pick.canceled)return {cancelled:true};
    await new Promise((done,reject)=>{const child=spawn(agentPython,['-s','-B',join(root,'backend/agent_kit.py'),pick.filePath],{stdio:'ignore',windowsHide:true});child.on('error',reject);child.on('exit',code=>code===0?done():reject(new Error('The agent kit could not be saved.')))});
    return {path:pick.filePath};
  }
  throw new Error('Unknown agent action.');
});
async function getItem(id){const r=await fetch(base+'/api/item/'+safeId(id),{headers:{'X-FX-Token':token}});if(!r.ok)throw new Error('File not found');return r.json();}
ipcMain.handle('export-audio',async(event,data)=>{
  trusted(event);
  const id=safeId(data.id),format=data.format;
  if(!['wav','mp3'].includes(format))throw new Error('Invalid format');
  const name=String(data.name||'FX Studio Sound').replace(/[\/:\x00-\x1f]/g,'-').slice(0,120);
  const pick=await dialog.showSaveDialog(win,{title:'Export sound',buttonLabel:'Save',defaultPath:join(app.getPath('downloads'),name+'.'+format),filters:[{name:format.toUpperCase(),extensions:[format]}]});
  if(pick.canceled)return {cancelled:true};
  const response=await fetch(base+'/api/export/'+id+'?format='+format,{headers:{'X-FX-Token':token}});
  if(!response.ok)throw new Error((await response.json()).error||'Export failed');
  fs.writeFileSync(pick.filePath,Buffer.from(await response.arrayBuffer()));
  return {path:pick.filePath};
});
ipcMain.handle('reveal-audio',async(event,raw)=>{trusted(event);const data=await getItem(raw);shell.showItemInFolder(data.path);});
const dragTickets=new Map();
ipcMain.handle('prepare-drag',async(event,raw)=>{
  trusted(event);
  const id=safeId(raw);
  const response=await fetch(base+'/api/prepare-drag/'+id,{method:'POST',headers:{'X-FX-Token':token,'Content-Type':'application/json'},body:'{}'});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'The audio file could not be prepared for dragging.');
  if(!['wav','mp3'].includes(data.format)||!fs.existsSync(data.path))throw new Error('The prepared audio file is unavailable.');
  let icon;
  try{icon=await app.getFileIcon(data.path,{size:'small'})}catch{}
  if(!icon||icon.isEmpty())icon=nativeImage.createFromPath(join(root,'ui/assets/wik-dev.png')).resize({width:64});
  if(icon.isEmpty())throw new Error('The drag icon is unavailable.');
  for(const [key,value] of dragTickets)if(value.id===id)dragTickets.delete(key);
  const ticket=crypto.randomBytes(24).toString('hex');
  dragTickets.set(ticket,{id,file:data.path,icon,created:Date.now()});
  return {ticket,format:data.format};
});
ipcMain.on('start-drag',(event,ticket)=>{
  try{
    trusted(event);
    const item=typeof ticket==='string'&&dragTickets.get(ticket);
    if(!item||!fs.existsSync(item.file))throw new Error('The audio file changed. Move over “Drag audio” to prepare it again.');
    event.sender.startDrag({file:item.file,icon:item.icon});
  }catch(error){if(event.sender===win?.webContents)event.sender.send('drag-error',error.message)}
});
ipcMain.handle('open-license',async(event,raw)=>{
  trusted(event);const data=await getItem(raw);
  const statusResponse=await fetch(base+'/api/status',{headers:{'X-FX-Token':token}});
  if(!statusResponse.ok)throw new Error('The sound library is unavailable.');
  const status=await statusResponse.json();
  if(!status.library_root)throw new Error('The sound library is unavailable.');
  const library=resolve(status.library_root);
  const document=data.kind==='library' && data.license?.document;
  if(!document)throw new Error('No license document is available for this sound.');
  const path=resolve(library,document);
  const within=relative(library,path);
  if(!within || within==='..' || within.startsWith('..'+sep) || isAbsolute(within) || !fs.existsSync(path))throw new Error('The license document is unavailable.');
  const error=await shell.openPath(path);if(error)throw new Error(error);
});
ipcMain.handle('open-bundled-licenses',async(event)=>{
  trusted(event);
  const folder=join(root,'ui/licenses');
  if(!fs.existsSync(folder))throw new Error('The bundled license documents are missing. Reinstall FX Studio.');
  const error=await shell.openPath(folder);if(error)throw new Error(error);
});
ipcMain.handle('open-link',async(event,url)=>{
  trusted(event);
  if(!['https://x.com/wik_plus','https://github.com/WikPlus','https://wikplus.dev/','https://buymeacoffee.com/wikplus','https://huggingface.co/stabilityai/stable-audio-3-optimized','https://huggingface.co/stabilityai/stable-audio-3-small-sfx','https://huggingface.co/stabilityai/stable-audio-3-medium','https://huggingface.co/mispeech/Dasheng-AudioGen','https://huggingface.co/mispeech/Dasheng-AudioGen-Multilingual','https://github.com/audiohacking/audiogen.cpp','https://stability.ai/license','https://ai.google.dev/gemma/terms','https://github.com/Stability-AI/stable-audio-3','https://huggingface.co/RunwuShi/UNITE-AUDIO','https://github.com/RunwuShi/Unite-Audio','https://huggingface.co/google/flan-t5-large'].includes(url))throw new Error('Link not allowed');
  await shell.openExternal(url);
});
if(isPrimary)app.whenReady().then(boot).catch(e=>{dialog.showErrorBox('FX Studio could not start',e.message);app.quit()});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',event=>{
  if(quitting || !service || service.exitCode!==null || service.signalCode!==null)return;
  event.preventDefault();quitting=true;
  const fallback=setTimeout(()=>{service.kill('SIGKILL');app.quit()},8000);
  service.once('exit',()=>{clearTimeout(fallback);app.quit()});
  if(process.platform==='win32')spawn('taskkill',['/PID',String(service.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
  else service.kill('SIGTERM');
});
Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'FX Studio',submenu:[{label:'About FX Studio',role:'about'},{type:'separator'},{label:'Quit FX Studio',role:'quit'}]},{label:'Edit',submenu:[{label:'Undo',role:'undo'},{label:'Redo',role:'redo'},{type:'separator'},{label:'Cut',role:'cut'},{label:'Copy',role:'copy'},{label:'Paste',role:'paste'},{label:'Select All',role:'selectAll'}]},{label:'Window',submenu:[{label:'Minimize',role:'minimize'},{label:'Zoom',role:'zoom'}]}]));
