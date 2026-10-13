// Real Electron renderer and HTTP service, isolated synthetic test catalogue.
const {app,BrowserWindow,session}=require('electron');
const fs=require('fs'),path=require('path');
app.setName('FX Studio UI Test');
app.setPath('userData',process.env.FX_DATA_DIR+'/electron-test');
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
app.whenReady().then(async()=>{
 let win;
 try{
  await session.defaultSession.cookies.set({url:process.env.FX_UI_TEST_URL,name:'fx_session',value:process.env.FX_SESSION_TOKEN,httpOnly:true,sameSite:'strict'});
  win=new BrowserWindow({show:false,width:1260,height:920,webPreferences:{preload:path.join(__dirname,'regenerate_preload.cjs'),contextIsolation:true,sandbox:false}});
  await win.loadURL(process.env.FX_UI_TEST_URL);
  const result=await win.webContents.executeJavaScript(`(async()=>{
   const assert=(value,message)=>{if(!value)throw new Error(message)};
   const wait=async predicate=>{const end=Date.now()+15000;while(!predicate()){if(Date.now()>end)throw new Error('UI timeout');await new Promise(r=>setTimeout(r,50));}};
   await wait(()=>document.querySelectorAll('.sound').length===8);
   document.querySelector('[data-view="projects"]').click();
   await wait(()=>document.querySelectorAll('.sound').length===30);
   document.querySelector('#more').click();
   await wait(()=>document.querySelectorAll('.sound').length===45);
   const row=document.querySelectorAll('.sound')[35],id=row.dataset.id,neighbor=row.previousElementSibling;
   const order=[...document.querySelectorAll('.sound')].map(row=>row.dataset.id);
   const before=await (await fetch('/api/item/'+id)).json();
   const button=row.querySelector('[data-action="regenerate"]');
   row.querySelector('.wave-zoom [data-action="zoom-in"]').click();
   row.scrollIntoView({block:'center'});button.focus({preventScroll:true});
   await new Promise(r=>requestAnimationFrame(r));const scroll=window.scrollY,top=row.getBoundingClientRect().top;
   button.click();
   await wait(()=>button.disabled);
   assert(document.querySelector('#queue-section').hidden,'Regenerate moved progress into the main queue');
   await wait(()=>row.querySelector('.regeneration-status').textContent.includes('New take ready'));
   const after=await (await fetch('/api/item/'+id)).json();
   assert(after.path.endsWith('.ogg'),'Regenerate did not store OGG');
   assert(after.path!==before.path&&after.seed!==before.seed,'Take/seed were not replaced');
   assert(document.querySelector('.nav-button.active').dataset.view==='projects','View changed');
   assert(JSON.stringify(order)===JSON.stringify([...document.querySelectorAll('.sound')].map(row=>row.dataset.id)),'Order or expanded list changed');
   assert(Math.abs(window.scrollY-scroll)<=1&&Math.abs(row.getBoundingClientRect().top-top)<=1,'Scroll position changed');
   assert(row.previousElementSibling===neighbor,'Neighbor was rebuilt');
   assert(row.querySelector('.zoom-level').textContent==='2×','Waveform zoom reset');
   assert(document.activeElement===row.querySelector('[data-action="regenerate"]'),'Keyboard focus lost');
   row.querySelector('[data-action="play"]').click();
   await wait(()=>!document.querySelector('#audio').paused&&document.querySelector('#audio').readyState>=2);
   assert(document.querySelector('#audio').currentSrc.includes(encodeURIComponent(after.path)),'Player reused the old audio revision');
   document.querySelector('#audio').pause();
   await wait(()=>row.querySelector('.drag-audio').dataset.dragTicket);
   assert(row.querySelector('.drag-audio').dataset.dragTicket.includes(after.path.split('/').pop().split('.')[0]),'Drag reused the old take');
   const ogg=row.querySelector('[data-action="ogg"]');assert(ogg&&!ogg.disabled,'Save OGG unavailable');
   ogg.click();await wait(()=>document.body.textContent.includes('Sound saved:')&&!ogg.disabled);
   return {passed:true,synthetic_fixture:true,expanded_project_sounds:45,scroll_preserved:true,row_order_preserved:true,focus_preserved:true,zoom_preserved:true,fresh_seed:true,playback_revision:true,drag_revision:true};
  })()`);
  if(fs.readFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'ui-export.ogg')).subarray(0,4).toString()!=='OggS')throw new Error('UI export is not OGG');
  result.ogg_storage=true;result.ogg_save_button=true;
  fs.writeFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'regeneration-ui.json'),JSON.stringify(result,null,2));
  const formats=await win.webContents.executeJavaScript(`(async()=>{
   const assert=(value,message)=>{if(!value)throw new Error(message)};
   const wait=async predicate=>{const end=Date.now()+15000;while(!await predicate()){if(Date.now()>end)throw new Error('Format UI timeout');await new Promise(r=>setTimeout(r,50));}};
   document.querySelector('[data-view="generate"]').click();window.scrollTo({top:0});
   const picker=document.querySelector('#format'),sounds=[];
   assert([...picker.options].map(o=>o.value).join(',')==='ogg,wav,mp3','Wrong format choices');
   for(const format of ['ogg','wav','mp3']){
    picker.value=format;picker.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>!picker.disabled&&!document.querySelector('#generate-button').disabled);
    assert(JSON.parse(localStorage.getItem('fx-draft')).format===format,'Format missing from draft');
    assert((await (await fetch('/api/status')).json()).generation_format===format,'Agent default did not change');
    document.querySelector('#project_id').value='';document.querySelector('#variants').value='1';
    document.querySelector('#seconds').value='.5';document.querySelector('#prompt').value='Format '+format+' fixture';
    document.querySelector('#generate-form').requestSubmit();
    let job;
    await wait(async()=>{job=(await (await fetch('/api/status')).json()).jobs.find(j=>j.settings.prompt==='Format '+format+' fixture');if(job?.state==='failed')throw new Error(job.error);return job?.state==='completed';});
    const sound=(await (await fetch('/api/history?job='+job.id)).json()).items[0];sounds.push(sound);
    assert(sound.settings.format===format&&sound.path.endsWith('.'+format),'Selected format was not stored');
    await wait(()=>document.querySelector('[data-id="'+sound.id+'"] [data-action="play"]'));
    document.querySelector('[data-id="'+sound.id+'"] [data-action="play"]').click();
    await wait(()=>!document.querySelector('#audio').paused&&document.querySelector('#audio').readyState>=2);
    document.querySelector('#audio').pause();
    await wait(()=>document.querySelector('[data-id="'+sound.id+'"] .drag-audio').dataset.dragTicket);
    assert(document.querySelector('[data-id="'+sound.id+'"] .drag-audio').dataset.dragTicket.endsWith('.'+format),'Drag format changed');
   }
   return {passed:true,formats:['ogg','wav','mp3'],storage_and_playback:true,drag_formats:true,sounds};
  })()`);
  await win.loadURL(process.env.FX_UI_TEST_URL);
  const restored=await win.webContents.executeJavaScript(`(async()=>{
   const wait=async predicate=>{const end=Date.now()+15000;while(!predicate()){if(Date.now()>end)throw new Error('Format reload timeout');await new Promise(r=>setTimeout(r,50));}};
   await wait(()=>!document.querySelector('#generate-button').disabled);
   if(document.querySelector('#format').value!=='mp3')throw new Error('Format lost on reload');
   const wavId=${JSON.stringify(formats.sounds.find(s=>s.settings.format==='wav').id)};
   await wait(()=>document.querySelector('[data-id="'+wavId+'"] [data-action="reuse"]'));
   document.querySelector('[data-id="'+wavId+'"] [data-action="reuse"]').click();
   await wait(()=>document.querySelector('#format').value==='wav'&&!document.querySelector('#format').disabled);
   if((await (await fetch('/api/status')).json()).generation_format!=='wav')throw new Error('Reuse did not preserve format');
   window.scrollTo({top:0});return {persisted_after_reload:true,reuse_preserves_format:true};
  })()`);
  Object.assign(formats,restored);delete formats.sounds;
  for(const width of [1260,920]){
   win.setSize(width,920);await win.webContents.executeJavaScript('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
   const layout=await win.webContents.executeJavaScript(`(()=>{const fields=[...document.querySelectorAll('.generation-parameters>label')].map(e=>e.getBoundingClientRect());return fields.every((b,i)=>!i||b.left>=fields[i-1].right)&&document.documentElement.scrollWidth<=innerWidth;})()`);
   if(!layout)throw new Error('Format controls overlap or overflow');
   fs.writeFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'format-'+width+'.png'),(await win.webContents.capturePage()).toPNG());
  }
  fs.writeFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'generation-formats-ui.json'),JSON.stringify(formats,null,2));
  await win.webContents.executeJavaScript(`document.querySelector('[data-view="projects"]').click()`);
  const deletion=await win.webContents.executeJavaScript(`(async()=>{
   const wait=async predicate=>{const end=Date.now()+15000;while(!predicate()){if(Date.now()>end)throw new Error('Deletion UI timeout');await new Promise(r=>setTimeout(r,50));}};
   window.scrollTo({top:0});const button=document.querySelector('#delete-project'),id=document.querySelector('#project-picker').value;
   button.click();await wait(()=>!button.disabled);
   const before=await (await fetch('/api/projects/'+id)).json();if(before.items.length!==45)throw new Error('Cancel deleted sounds');
   button.click();await wait(()=>document.body.textContent.includes('Project deleted ·'));
   if(document.querySelectorAll('.sound').length||!document.querySelector('#project-detail').hidden)throw new Error('Deleted project remained visible');
   if(document.querySelector('#audio').getAttribute('src'))throw new Error('Deleted sound remained in the player');
   const projects=await (await fetch('/api/projects')).json();if(projects.projects.some(p=>p.id===id))throw new Error('Project still exists');
   return {passed:true,cancel_preserves_project:true,project_and_sounds_deleted:true,player_cleared:true};
  })()`);
  fs.writeFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'project-deletion-ui.json'),JSON.stringify(deletion,null,2));
  await win.webContents.executeJavaScript('window.scrollTo({top:0})');
  fs.writeFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'project-deleted.png'),(await win.webContents.capturePage()).toPNG());
  console.log(JSON.stringify(result));app.exit(0);
 }catch(error){console.error(error.stack);if(win){fs.writeFileSync(path.join(process.env.FX_UI_TEST_OUTPUT,'regenerate-failure.png'),(await win.webContents.capturePage()).toPNG());}app.exit(1);}
});
