'use strict';
const $=selector=>document.querySelector(selector);
const icons={projects:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',generate:'<path d="M4 8v8m4-12v16m4-9v2m4-9v16m4-12v8"/>',history:'<path d="M3 11a9 9 0 1 1 2.5 7M3 4v7h7m2-5v6l4 2"/>',favorites:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z"/>',library:'<path d="M4 5h4v15H4zm7 0h4v15h-4zm7-1 3 15"/>',setup:'<path d="M4 7h16M4 17h16M8 4v6m8 4v6"/>',play:'<path d="m8 5 11 7-11 7Z"/>',pause:'<path d="M8 5v14m8-14v14"/>'};
const svg=name=>`<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name]}</svg>`;
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Follow Stability's SFX guide: source, action, then recording/production character.
// These are original prompts using that structure; the backend adds TrackType: SFX.
const examples={
 camera:{prompt:'A DSLR camera shutter firing once, a sharp mechanical snap followed by a tiny spring click. Close-miked in a dead room, with a tight midrange body and a very fast decay.',seconds:1},
 click:{prompt:'A computer mouse button pressed and released once. Two closely spaced, crisp plastic clicks with a small midrange body. Recorded close to the button in a dead room, dry, with an immediate decay.',seconds:1},
 knob:{prompt:'A small wooden control knob rotating through one detent. A short rounded knock with a faint mechanical tick, warm low-mid body and a quick decay. Close-miked in a dead room.',seconds:1},
 pop:{prompt:'A small air bubble popping once. A rounded, soft plop with a tiny bright attack and a very short tail. Close-miked and dry, isolated against a quiet background.',seconds:1},
 swish:{prompt:'A thin strip of fabric flicked quickly past a microphone. A light, smooth air swish that rises briefly and fades immediately. Recorded close in a dead room, with a soft high-frequency texture.',seconds:1},
 whoosh:{prompt:'A single synthesized transition whoosh. A smooth, rising air sweep that moves quickly into a tight, soft impact, followed by a fast decay. Dry and isolated, with an airy high end and a compact low-mid finish.',seconds:2},
 impact:{prompt:'A small padded mallet striking a solid wooden block once. A compact, warm thud with a crisp initial knock and a fast decay. Close-miked in a dead room, with a tight low-mid body.',seconds:1},
 paper:{prompt:'One page of a paper book being turned slowly. A delicate papery rustle builds as the sheet bends, ending in a light flutter as it settles. Close-miked in a quiet, dry room, preserving the fine paper texture.',seconds:2},
 drawer:{prompt:'A wooden desk drawer pushed shut once. A solid wooden knock followed by a short low-mid thud as it closes. Close-miked in a dry room, with a natural, quick decay.',seconds:1},
 boost:{prompt:'A futuristic spacecraft engine firing a single short boost. A rising electric whine accelerates into a sharp air burst and a compact bass punch, then quickly fades. Dry, isolated sound design with a bright attack and a tight low-frequency tail.',seconds:3},
 rain:{prompt:'Light rain falling steadily on broad leaves. Small individual droplets patter gently across the leaves, with a soft, continuous rain bed underneath. Recorded outdoors at close range, with a natural stereo perspective and an even level throughout.',seconds:8},
 cave:{prompt:'Wind flowing slowly through a deep stone cave. A soft, sustained air rush swells gently over a distant low rumble. Recorded from inside the cave, with a wide, dark room character and long natural reverberation.',seconds:8}
};
let view='generate',status=null,items=[],shown=30,currentJob=null,lastMediaSignature='',lastQueueSignature='',refreshSequence=0,selected=null,noticeTimer,searchTimer;
let reference=null;
let projectId='',projectJobs=[],projectFormId=null,projectsSignature='',pendingGenerationProject='';
try{projectId=localStorage.getItem('fx-project')||''}catch{}
const baseFields=['project_id','model','prompt','seconds','variants','seed','steps','cfg','negative_prompt'];
const editingFields=['mode','strength','start','end'];
function selectedModel(){return status?.models.find(model=>model.id===$('#model').value);}
// Names and source links remain available for saved sounds from removed models.
function modelName(id='sm-sfx'){return status?.models.find(model=>model.id===id)?.model || ({'sm-sfx':'Stable Audio 3 Small SFX',medium:'Stable Audio 3 Medium',unite:'UNITE-AUDIO'}[id]);}
const modelSources={'sm-sfx':'https://huggingface.co/stabilityai/stable-audio-3-small-sfx',medium:'https://huggingface.co/stabilityai/stable-audio-3-medium',unite:'https://huggingface.co/RunwuShi/UNITE-AUDIO'};
function normalizeModelSettings(settings){
 if(settings.model==='medium')return {...settings};
 return {...settings,model:'medium',steps:8,cfg:1};
}
const waves=new Map(),waveZoom=new Map();
const audio=$('#audio');
const trimDrafts=new Map(),savingTrims=new Set(),dragPreparations=new Map();
let trimDrag=null,selectedAudioSignature='';
const clock=seconds=>{seconds=Math.max(0,Number(seconds)||0);return `${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`};
const playerTime=(seconds,total)=>total<10?`${seconds.toFixed(2)} / ${total.toFixed(2)} s`:`${clock(seconds)} / ${clock(total)}`;
const duration=seconds=>new Intl.NumberFormat('en-US',{maximumFractionDigits:1}).format(seconds)+' s';
const categoryLabels={'01_Natur_Wetter':'Nature & weather','02_Wasser_Feuer':'Water & fire','03_Orte_Atmosphaeren':'Places & ambience','04_Schritte_Kleidung':'Footsteps & clothing','05_Tueren_Schloesser_Mechanik':'Doors, locks & mechanisms','06_Alltag_Papier_Gegenstaende':'Everyday objects & paper','07_Fahrzeuge_Verkehr':'Vehicles & traffic','08_Maschinen_Elektronik':'Machines & electronics','09_Menschen_Stimmen':'People & voices','10_Tiere_Kreaturen':'Animals & creatures','11_UI_Comic_Infografik':'UI, cartoons & infographics','12_Uebergaenge_Whooshes_Impacts':'Transitions, whooshes & impacts','13_Horror_Magie_SciFi':'Horror, magic & sci-fi','14_Kampf_Waffen_Explosionen':'Combat, weapons & explosions','15_Musik_Instrumente_Glocken':'Music, instruments & bells'};
const categoryName=value=>categoryLabels[value]||value.replace(/^\d+_/,'').replaceAll('_',' · ');
function notice(message,error=false){clearTimeout(noticeTimer);$('#notice').textContent=message;$('#notice').classList.toggle('error',error);$('#notice').hidden=false;if(!error)noticeTimer=setTimeout(()=>{$('#notice').hidden=true},9000);}
async function api(path,body){
 const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw new Error(data.error||'Action failed.');return data;
}
function showView(next){
 view=next;shown=30;lastMediaSignature='';refreshSequence++;$('#search').value='';$('#category').value='';
 document.querySelectorAll('.nav-button').forEach(button=>{button.classList.toggle('active',button.dataset.view===view);if(button.dataset.view===view)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current')});
 const titles={generate:['Generate sound','Describe, generate, listen.'],projects:['Projects','Keep each game or edit’s sounds together.'],history:['History','Your generated sounds and their settings.'],favorites:['Favorites','Saved sounds from your history and library.'],library:['Sound library','Browse sounds in your local collection.'],setup:['Setup','Models, storage and licenses at a glance.']};
 $('#page-title').textContent=titles[view][0];$('#page-subtitle').textContent=titles[view][1];$('#generator').hidden=view!=='generate';$('#projects').hidden=view!=='projects';$('#setup').hidden=view!=='setup';$('#media-section').hidden=view==='setup';$('#search-toolbar').hidden=['generate','setup'].includes(view);$('#category').hidden=view!=='library';$('#results-title').textContent=view==='generate'?'Your sounds':'Sounds';
 renderQueue();if(view==='setup')renderSetup();else refreshMedia().catch(error=>notice(error.message,true));window.scrollTo({top:0});
}
function syncProjects(){
 const projects=status.projects||[],signature=JSON.stringify(projects);
 if(signature===projectsSignature)return;projectsSignature=signature;
 const generation=$('#project_id').value||pendingGenerationProject;
 const options=projects.map(p=>`<option value="${p.id}">${escape(p.name)} · ${p.sound_count} sounds</option>`).join('');
 $('#project_id').innerHTML='<option value="">No project</option>'+options;
 $('#project_id').value=projects.some(p=>p.id===generation)?generation:'';pendingGenerationProject='';
 $('#project-picker').innerHTML='<option value="">Choose a project</option>'+options;
 if(!projects.some(p=>p.id===projectId))projectId=projects[0]?.id||'';
 $('#project-picker').value=projectId;renderProjectDetail();
}
function renderProjectDetail(){
 const project=status?.projects.find(p=>p.id===projectId);$('#project-detail').hidden=!project;
 if(project){$('#project-title').textContent=project.name;$('#project-description-text').textContent=project.description;$('#project-description-text').hidden=!project.description;$('#project-count').textContent=`${project.sound_count} ${project.sound_count===1?'sound':'sounds'}${project.active_jobs?' · '+project.active_jobs+' active '+(project.active_jobs===1?'job':'jobs'):''}`;}
}
function selectProject(id){
 projectId=id;$('#project-picker').value=id;projectJobs=[];shown=30;lastMediaSignature='';refreshSequence++;
 try{localStorage.setItem('fx-project',id)}catch{}renderProjectDetail();renderQueue();
 refreshMedia().catch(error=>notice(error.message,true));
}
function openProjectForm(edit){
 const project=edit?status?.projects.find(p=>p.id===projectId):null;projectFormId=project?.id||null;
 $('#project-form-title').textContent=project?'Edit project':'New project';$('#save-project').textContent=project?'Save changes':'Create project';
 $('#project-name').value=project?.name||'';$('#project-description').value=project?.description||'';$('#project-form').hidden=false;$('#project-name').focus();
}
$('#project-picker').addEventListener('change',event=>{audio.pause();$('#project-form').hidden=true;selectProject(event.target.value)});
$('#new-project').addEventListener('click',()=>openProjectForm(false));
$('#create-generation-project').addEventListener('click',()=>{showView('projects');openProjectForm(false)});
$('#edit-project').addEventListener('click',()=>openProjectForm(true));
$('#cancel-project-form').addEventListener('click',()=>{$('#project-form').hidden=true});
$('#project-form').addEventListener('submit',async event=>{
 event.preventDefault();const button=$('#save-project');button.disabled=true;
 const data={name:$('#project-name').value,description:$('#project-description').value};
 try{const project=await api(projectFormId?'project-update':'projects',projectFormId?{...data,project_id:projectFormId}:data);await poll();$('#project-form').hidden=true;selectProject(project.id);$('#project_id').value=project.id;saveDraft();notice(project.created_new===false?'Opened existing project.':projectFormId?'Project updated.':'Project created.');}
 catch(error){notice(error.message,true)}finally{button.disabled=false;}
});
$('#generate-in-project').addEventListener('click',()=>{$('#project_id').value=projectId;currentJob=null;saveDraft();showView('generate');$('#prompt').focus();notice('New sounds will be saved in '+status.projects.find(p=>p.id===projectId).name+'.')});
$('#project_id').addEventListener('change',()=>{currentJob=null;lastMediaSignature='';refreshMedia().catch(error=>notice(error.message,true))});
function syncProjectReview(){
 const index=items.findIndex(item=>item.id===selected),available=items.some(item=>!item.missing);
 $('#previous-sound').disabled=view!=='projects'||!available||index<=0;
 $('#next-sound').disabled=view!=='projects'||!available||index>=items.length-1;
}
async function reviewSound(direction){
 const current=items.findIndex(item=>item.id===selected);let next=current+direction;
 if(current<0)next=direction>0?0:items.length-1;
 while(next>=0&&next<items.length&&items[next].missing)next+=direction;
 if(next<0||next>=items.length)return;const sound=items[next];
 if(next>=shown){shown=Math.ceil((next+1)/30)*30;renderMedia()}
 try{loadAudio(sound);audio.currentTime=0;await audio.play();syncPlayer();rowFor(sound.id)?.scrollIntoView({block:'nearest',behavior:'smooth'});}catch(error){notice(error.message,true)}
}
$('#previous-sound').addEventListener('click',()=>reviewSound(-1));$('#next-sound').addEventListener('click',()=>reviewSound(1));
$('#media-list').addEventListener('change',async event=>{
 const input=event.target.closest('[data-project-membership]');if(!input)return;input.disabled=true;
 try{await api('project-sound',{project_id:input.dataset.projectMembership,sound_id:input.closest('.sound').dataset.id,included:input.checked});await poll();}
 catch(error){input.checked=!input.checked;notice(error.message,true)}finally{input.disabled=false;}
});
async function refreshMedia(){
 const request=++refreshSequence,query=new URLSearchParams({q:$('#search').value});
 if(view==='setup')return;
 const requestedView=view;
 let data;
 if(view==='library'){query.set('category',$('#category').value);data=await api('library?'+query);if(request!==refreshSequence)return;
  if($('#category').options.length===1)$('#category').insertAdjacentHTML('beforeend',data.categories.map(value=>`<option value="${escape(value)}">${escape(categoryName(value))}</option>`).join(''));
 }else if(view==='projects'){
  data=projectId?await api('projects/'+projectId+'?'+query):{items:[],jobs:[]};
  if(request!==refreshSequence || requestedView!==view)return;projectJobs=data.jobs;renderQueue();
 }else if(view==='favorites'){
  query.set('favorites','1');const [generated,library]=await Promise.all([api('history?'+query),api('library?'+query)]);data={items:[...generated.items,...library.items]};
 }else{if(view==='generate' && currentJob)query.set('job',currentJob);data=view==='generate'&&!currentJob&&$('#project_id').value?await api('projects/'+$('#project_id').value+'?'+query):await api('history?'+query);}
 if(request!==refreshSequence || requestedView!==view || trimDrag || savingTrims.size)return;items=data.items;
 const signature=JSON.stringify([view,shown,items,status?.export_mp3,$('#model').value]);if(signature===lastMediaSignature)return;lastMediaSignature=signature;renderMedia();
}
function renderMedia(){
 $('#results-count').textContent=items.length?`${items.length} ${items.length===1?'Sound':'Sounds'}`:'';
 const visible=items.slice(0,view==='generate'?8:shown);
 const empty=view==='projects'?(projectId?['No sounds in this project yet','Generate for this project, or add existing sounds using each sound’s Projects menu.']:['Your projects live here','Create a project for your game or edit, then generate its sounds together.']):view==='library'?['No results','Try another search term or category.']:view==='favorites'?['Your favorites live here','Star a sound to find it here later.']:view==='generate' && currentJob?['Your sound will appear here','Finished variants appear here as generation completes.']:view==='generate'?['Your first sound starts with an idea','Describe a sound or choose an example above.']:['No matching sounds yet','Generate a sound or change your search term.'];
 $('#media-list').innerHTML=visible.length?visible.map(sound=>{
  const library=sound.kind==='library',undocumented=library && sound.license.status!=='documented_bundle';
  const meta=library?`${duration(sound.duration)} · ${categoryName(sound.category)} · ${sound.source.supplier||'Unknown source'}`:`${duration(sound.duration)} · Seed ${sound.seed} · ${new Date(sound.created*1000).toLocaleString('en-US',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}`;
  const info=library?`<p>${escape(sound.source.original_filename)}<br>${escape(sound.source.collection||'Collection not documented')}<br><span class="${undocumented?'license-unknown':''}">${undocumented?'Source and usage rights are not documented.':'Sonniss bundle license documented · commercial use allowed · no attribution required.'}</span></p>${sound.license.document?'<button data-action="license">Open license document</button>':''}`:`<p>${escape(sound.prompt)}</p><p>${sound.settings.steps} sampling steps · CFG ${sound.settings.cfg}${sound.settings.negative_prompt?' · Negative prompt: '+escape(sound.settings.negative_prompt):''}${sound.settings.mode!=='text'?'<br>'+escape(sound.settings.mode==='inpaint'?'Section '+duration(sound.settings.start)+' to '+duration(sound.settings.end):'Variation')+' · Strength '+sound.settings.strength:''}${sound.reference?'<br>Reference: '+escape(sound.reference.title)+(sound.reference.kind==='library'?' · '+(sound.reference.license.status==='documented_bundle'?'Sonniss license documented':'Source and usage rights not documented'):''):''}<br>${escape(modelName(sound.settings.model))}${sound.settings.model!=='medium'?' · Model removed':''}</p><button data-action="model-license">Original model &amp; license</button>`;
  return `<article class="sound" data-id="${sound.id}"><div class="sound-heading"><div><h3 class="sound-title">${escape(sound.title)}</h3><p class="sound-meta">${escape(meta)}${sound.projects?.length?' · '+escape(sound.projects.map(p=>p.name).join(', ')):''}</p></div><button class="icon-button ${sound.favorite?'favorite':''}" data-action="favorite" aria-label="${sound.favorite?'Remove from favorites':'Add to favorites'}" aria-pressed="${Boolean(sound.favorite)}">${svg('favorites')}</button></div>
  ${sound.missing?'<p class="job-error">The file is missing from its saved location. You can generate the sound again.</p>':`<div class="player"><button class="play-button" data-action="play" aria-label="Play sound">${svg('play')}</button><div class="wave-viewport"><div class="wave"><canvas aria-hidden="true"></canvas><input class="seek" type="range" min="0" max="1000" step="1" value="0" aria-label="Playback position" disabled><div class="trim-selection" aria-hidden="true"></div><button type="button" class="trim-handle" data-trim-edge="start" role="slider" aria-label="Trim start" aria-valuemin="0" aria-valuemax="${sound.source_duration||sound.duration}" aria-valuenow="0" title="Drag the left edge to trim the start. Arrow keys adjust by 10 ms; Shift adjusts by 1 ms." disabled></button><button type="button" class="trim-handle" data-trim-edge="end" role="slider" aria-label="Trim end" aria-valuemin="0" aria-valuemax="${sound.source_duration||sound.duration}" aria-valuenow="${sound.source_duration||sound.duration}" title="Drag the right edge to trim the end. Arrow keys adjust by 10 ms; Shift adjusts by 1 ms." disabled></button></div></div><span class="time">${playerTime(0,sound.duration)}</span></div><div class="trim-info"><span class="trim-summary">Drag the edges to trim · automatic 5 ms fades</span><button data-action="reset-trim" hidden>Reset trim</button><div class="wave-zoom" role="group" aria-label="Waveform zoom"><button data-action="zoom-out" aria-label="Zoom out waveform" title="Zoom out">−</button><span class="zoom-level">1×</span><button data-action="zoom-in" aria-label="Zoom in waveform" title="Zoom in">+</button><button data-action="zoom-fit" title="Show the complete sound">Fit</button></div><span class="trim-state" role="status"></span></div>`}
  <div class="sound-actions"><details class="sound-projects"><summary>Projects${sound.projects?.length?' ('+sound.projects.length+')':''}</summary><div class="project-memberships">${(status?.projects||[]).map(p=>`<label><input type="checkbox" data-project-membership="${p.id}" ${sound.projects?.some(assigned=>assigned.id===p.id)?'checked':''}> ${escape(p.name)}</label>`).join('')||'<p>Create a project to organize your sounds.</p>'}<button type="button" data-action="new-project">New project</button></div></details>${library?'':'<button data-action="reuse">Generate again</button>'}${!sound.missing?`<button data-action="reference" ${sound.duration<.5||sound.duration>30?'hidden':''} ${selectedModel()?.editing===false?'disabled title="Select Stable Audio to edit a reference."':''}>Use as reference</button>`:''}<details><summary>${library?(undocumented?'Unknown source':'Source & license'):'Description & settings'}</summary>${info}</details><span class="spacer"></span>${sound.missing?'':'<button class="drag-audio" data-action="drag-audio" draggable="false" title="Preparing audio for dragging…" disabled>Drag audio</button>'}<button data-action="wav" ${sound.missing?'disabled':''}>Save WAV</button><button data-action="mp3" ${sound.missing||!status?.export_mp3?'disabled title="FFmpeg is missing; check Setup"':''}>Save MP3</button><button data-action="reveal">Show in Finder</button></div></article>`;
 }).join(''):`<div class="empty"><strong>${empty[0]}</strong><p>${empty[1]}</p></div>`;
 $('#more').hidden=items.length<=visible.length || view==='generate';
 document.querySelectorAll('.sound').forEach((row,index)=>{if(row.querySelector('canvas')){updateTrimRow(row);if(index<5)loadWave(row);else observer.observe(row);}});syncPlayer();
}
const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(entry.isIntersecting){loadWave(entry.target);observer.unobserve(entry.target)}}},{rootMargin:'100px'});
async function loadWave(row,bins=700*(waveZoom.get(row.dataset.id)?.factor||1)){
 const id=row.dataset.id;
 try{let wave=waves.get(id);if(!wave||(wave.bins||700)<bins){wave=await api('waveform/'+id+'?bins='+bins);if((waves.get(id)?.bins||0)<wave.bins)waves.set(id,wave);else wave=waves.get(id);}
  if(!row.isConnected)return;row.querySelector('.wave input').disabled=false;row.querySelectorAll('.trim-handle').forEach(handle=>handle.disabled=false);applyZoom(row);updateTrimRow(row);drawWave(row,wave);syncPlayer();primeDrag(row);
 }catch(error){const player=row.querySelector('.player');player.insertAdjacentHTML('afterend',`<p class="job-error">Waveform unavailable: ${escape(error.message)}</p>`);}
}
function drawWave(row,wave){
 const canvas=row.querySelector('canvas'),sound=items.find(item=>item.id===row.dataset.id);if(!canvas||!sound)return;const width=canvas.clientWidth,height=44,scale=window.devicePixelRatio||1;canvas.width=width*scale;canvas.height=height*scale;const context=canvas.getContext('2d');context.scale(scale,scale);const trim=trimRange(sound),progress=selected===row.dataset.id?(trim.start+audio.currentTime)/wave.duration:0;
 const accent=getComputedStyle(row).getPropertyValue('--accent').trim(),bars=Math.max(1,Math.floor(width/4));for(let i=0;i<bars;i++){const start=Math.floor(i*wave.peaks.length/bars),end=Math.max(start+1,Math.floor((i+1)*wave.peaks.length/bars));const peak=Math.max(0,...wave.peaks.slice(start,end)),h=Math.max(2,peak*36),time=i/bars*wave.duration,inside=time>=trim.start&&time<=trim.end;context.globalAlpha=inside?1:.25;context.fillStyle=inside&&i/bars<=progress&&selected===row.dataset.id?accent:'#77808b';context.fillRect(i*4,(height-h)/2,2,h)}context.globalAlpha=1;
}
function syncPlayer(){
 syncProjectReview();
 if(reference)$('#play-reference').textContent=selected===reference.id&&!audio.paused?'Pause reference':'Play reference';
 document.querySelectorAll('.sound').forEach(row=>{const button=row.querySelector('.play-button');if(!button)return;const active=row.dataset.id===selected,playing=active&&!audio.paused;button.classList.toggle('playing',playing);button.innerHTML=svg(playing?'pause':'play');button.setAttribute('aria-label',playing?'Pause playback':'Play sound');const sound=items.find(x=>x.id===row.dataset.id),trim=trimRange(sound),seconds=active?audio.currentTime:0;row.querySelector('.time').textContent=playerTime(seconds,trim.end-trim.start);row.querySelector('.wave input').value=Math.round(1000*(trim.start+seconds)/sourceDuration(sound));if(waves.has(row.dataset.id))drawWave(row,waves.get(row.dataset.id));});
}
function sourceDuration(sound){return waves.get(sound.id)?.duration||sound.source_duration||sound.duration;}
function trimRange(sound){return trimDrafts.get(sound.id)||sound.trim||{start:0,end:sourceDuration(sound)};}
function audioSignature(sound){return sound.id+'|'+(sound.trim?.updated||'original');}
function rowFor(id){return document.querySelector(`.sound[data-id="${id}"]`);}
function applyZoom(row){
 const viewport=row.querySelector('.wave-viewport');if(!viewport)return;
 const state=waveZoom.get(row.dataset.id)||{factor:1,scroll:0},track=row.querySelector('.wave');
 track.style.width=100*state.factor+'%';viewport.dataset.zoomed=String(state.factor>1);viewport.scrollLeft=state.scroll*track.clientWidth;
 row.querySelector('.zoom-level').textContent=state.factor+'×';row.querySelector('[data-action="zoom-out"]').disabled=state.factor===1;row.querySelector('[data-action="zoom-in"]').disabled=state.factor===16;row.querySelector('[data-action="zoom-fit"]').disabled=state.factor===1;
}
function changeZoom(row,factor,clientX){
 const viewport=row.querySelector('.wave-viewport'),track=row.querySelector('.wave');if(!viewport)return;
 factor=Math.max(1,Math.min(16,factor));const state=waveZoom.get(row.dataset.id)||{factor:1,scroll:0};if(factor===state.factor)return;
 const center=clientX===undefined?viewport.clientWidth*.2:Math.max(0,Math.min(viewport.clientWidth,clientX-viewport.getBoundingClientRect().left));
 const sound=items.find(item=>item.id===row.dataset.id),anchor=clientX===undefined?trimRange(sound).start/sourceDuration(sound):(viewport.scrollLeft+center)/track.clientWidth;
 waveZoom.set(row.dataset.id,{factor,scroll:factor===1?0:Math.max(0,anchor-center/(viewport.clientWidth*factor))});
 applyZoom(row);updateTrimRow(row);loadWave(row,700*factor);
}
$('#media-list').addEventListener('scroll',event=>{
 const viewport=event.target;if(!viewport.matches?.('.wave-viewport'))return;
 const id=viewport.closest('.sound').dataset.id,state=waveZoom.get(id);if(state)state.scroll=viewport.scrollLeft/viewport.querySelector('.wave').clientWidth;
},{capture:true});
$('#media-list').addEventListener('wheel',event=>{
 const viewport=event.target.closest('.wave-viewport');if(!viewport||(!event.altKey&&!event.ctrlKey)||trimDrag)return;
 event.preventDefault();const row=viewport.closest('.sound'),factor=waveZoom.get(row.dataset.id)?.factor||1;
 changeZoom(row,event.deltaY<0?factor*2:factor/2,event.clientX);
},{passive:false});
function updateTrimRow(row){
 const sound=items.find(item=>item.id===row.dataset.id);if(!sound||!row.querySelector('.wave'))return;
 const trim=trimRange(sound),total=sourceDuration(sound),minimum=Math.min(.01,total),edited=trim.start>.00001||trim.end<total-.00001,busy=savingTrims.has(sound.id)||trimDrag?.id===sound.id;
 const track=row.querySelector('.wave'),selection=row.querySelector('.trim-selection');
 track.dataset.trimmed=String(edited);selection.style.left=100*trim.start/total+'%';selection.style.width=100*(trim.end-trim.start)/total+'%';
 for(const handle of row.querySelectorAll('.trim-handle')){
  const edge=handle.dataset.trimEdge;handle.style.left=100*trim[edge]/total+'%';handle.setAttribute('aria-valuenow',trim[edge].toFixed(3));handle.setAttribute('aria-valuemin',edge==='start'?0:trim.start+minimum);handle.setAttribute('aria-valuemax',edge==='start'?trim.end-minimum:total);handle.setAttribute('aria-valuetext',trim[edge].toFixed(3)+' seconds');
 }
 row.querySelector('.trim-summary').textContent=edited?`${trim.start.toFixed(3)}–${trim.end.toFixed(3)} s · ${(trim.end-trim.start).toFixed(3)} s selected · 5 ms fades`:'Drag the edges to trim · automatic 5 ms fades';
 row.querySelector('[data-action="reset-trim"]').hidden=!edited;row.querySelector('.trim-state').textContent=savingTrims.has(sound.id)?'Saving…':'';
 for(const action of ['play','wav','mp3','drag-audio']){const button=row.querySelector(`[data-action="${action}"]`);if(button)button.disabled=busy||(action==='mp3'&&!status?.export_mp3)||(action==='drag-audio'&&!button.dataset.dragTicket);}
 const referenceButton=row.querySelector('[data-action="reference"]');if(referenceButton)referenceButton.hidden=trim.end-trim.start<.5||trim.end-trim.start>30;
 if(waves.has(sound.id))drawWave(row,waves.get(sound.id));
}
function invalidateDrag(id){dragPreparations.delete(id);const button=rowFor(id)?.querySelector('.drag-audio');if(button){delete button.dataset.dragTicket;button.draggable=false;button.disabled=true;button.title='Preparing audio for dragging…';}}
async function primeDrag(row){
 const id=row.dataset.id,sound=items.find(item=>item.id===id),button=row.querySelector('.drag-audio');if(!sound||!button||savingTrims.has(id)||trimDrag?.id===id)return;
 const revision=audioSignature(sound);let entry=dragPreparations.get(id);
 if(!entry||entry.revision!==revision){entry={revision,promise:window.fxDesktop.prepareDrag(id)};dragPreparations.set(id,entry);}
 try{
  const result=await entry.promise;
  if(!row.isConnected||dragPreparations.get(id)!==entry||savingTrims.has(id)||trimDrag?.id===id)return;
  button.dataset.dragTicket=result.ticket;button.draggable=true;button.disabled=false;button.title=`Drag the ${result.format.toUpperCase()} file into your editor or Finder.`;button.setAttribute('aria-label',`Drag ${result.format.toUpperCase()} audio file into your editor or Finder`);
 }catch(error){
  if(dragPreparations.get(id)===entry)dragPreparations.delete(id);
  if(row.isConnected){button.disabled=false;button.draggable=false;button.title='Click to prepare audio again.';row.querySelector('.trim-state').textContent=error.message;}
 }
}
function changeTrim(id,edge,value){
 const sound=items.find(item=>item.id===id),total=sourceDuration(sound),minimum=Math.min(.01,total),previous=trimRange(sound);
 const next={start:previous.start,end:previous.end};next[edge]=edge==='start'?Math.max(0,Math.min(value,next.end-minimum)):Math.max(next.start+minimum,Math.min(value,total));
 trimDrafts.set(id,next);const row=rowFor(id);if(row)updateTrimRow(row);syncPlayer();
}
function pauseForTrim(id){if(selected===id){audio.pause();audio.currentTime=0;selectedAudioSignature='';}}
async function persistTrim(id){
 if(savingTrims.has(id))return;savingTrims.add(id);invalidateDrag(id);const firstRow=rowFor(id);if(firstRow)updateTrimRow(firstRow);
 try{
  while(trimDrafts.has(id)){
   const sent=trimDrafts.get(id),result=await api('trim/'+id,{start:sent.start,end:sent.end}),index=items.findIndex(item=>item.id===id);
   if(index>=0)items[index]=result.item;
   if(reference?.id===id){reference=result.item;syncMode();}
   if(trimDrafts.get(id)===sent){trimDrafts.delete(id);break;}
  }
 }catch(error){
  trimDrafts.delete(id);notice('Trim could not be saved: '+error.message,true);
  try{const recovered=await api('item/'+id),index=items.findIndex(item=>item.id===id);if(index>=0)items[index]=recovered;}catch{}
 }finally{
  savingTrims.delete(id);if(selected===id)selectedAudioSignature='';
  const row=rowFor(id),sound=items.find(item=>item.id===id);
  if(row){updateTrimRow(row);const meta=row.querySelector('.sound-meta');if(sound&&meta){const separator=meta.textContent.indexOf(' ·');if(separator>=0)meta.textContent=duration(sound.duration)+meta.textContent.slice(separator);}primeDrag(row);}
  // Keep keyboard focus and handle positions; avoid rebuilding a row just saved in place.
  lastMediaSignature=JSON.stringify([view,shown,items,status?.export_mp3,$('#model').value]);syncPlayer();
 }
}
$('#media-list').addEventListener('pointerdown',event=>{
 const handle=event.target.closest('.trim-handle');if(!handle||handle.disabled||event.button!==0)return;
 event.preventDefault();const row=handle.closest('.sound'),id=row.dataset.id;pauseForTrim(id);
 trimDrag={id,edge:handle.dataset.trimEdge,pointer:event.pointerId,handle,initialDraft:trimDrafts.get(id),moved:false};handle.focus();handle.setPointerCapture(event.pointerId);
});
document.addEventListener('pointermove',event=>{
 if(!trimDrag||event.pointerId!==trimDrag.pointer)return;event.preventDefault();const row=rowFor(trimDrag.id);if(!row)return;
 const viewport=row.querySelector('.wave-viewport'),visible=viewport.getBoundingClientRect();if(event.clientX<visible.left+20)viewport.scrollLeft-=15;else if(event.clientX>visible.right-20)viewport.scrollLeft+=15;
 const bounds=row.querySelector('.wave').getBoundingClientRect(),sound=items.find(item=>item.id===trimDrag.id);trimDrag.moved=true;changeTrim(trimDrag.id,trimDrag.edge,(event.clientX-bounds.left)/Math.max(1,bounds.width)*sourceDuration(sound));
});
function finishTrim(event,cancelled=false){
 if(!trimDrag||event.pointerId!==trimDrag.pointer)return;const drag=trimDrag;trimDrag=null;
 if(drag.handle.hasPointerCapture(drag.pointer))drag.handle.releasePointerCapture(drag.pointer);
 if(cancelled){if(drag.initialDraft)trimDrafts.set(drag.id,drag.initialDraft);else trimDrafts.delete(drag.id);const row=rowFor(drag.id);if(row){updateTrimRow(row);primeDrag(row);}syncPlayer();}
 else if(drag.moved)persistTrim(drag.id);else{const row=rowFor(drag.id);if(row)updateTrimRow(row);}
}
document.addEventListener('pointerup',event=>finishTrim(event));document.addEventListener('pointercancel',event=>finishTrim(event,true));
$('#media-list').addEventListener('keydown',event=>{
 const handle=event.target.closest('.trim-handle');if(!handle||handle.disabled||!['ArrowLeft','ArrowRight','ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
 event.preventDefault();const id=handle.closest('.sound').dataset.id,edge=handle.dataset.trimEdge,sound=items.find(item=>item.id===id),trim=trimRange(sound),total=sourceDuration(sound),minimum=Math.min(.01,total),step=event.shiftKey ? .001 : .01;
 let value=trim[edge]+(['ArrowRight','ArrowUp'].includes(event.key)?step:-step);
 if(event.key==='Home')value=edge==='start'?0:trim.start+minimum;
 if(event.key==='End')value=edge==='start'?trim.end-minimum:total;
 pauseForTrim(id);changeTrim(id,edge,value);persistTrim(id);
});
$('#media-list').addEventListener('dragstart',event=>{
 const button=event.target.closest('.drag-audio');if(!button)return;event.preventDefault();const id=button.closest('.sound').dataset.id;
 if(button.dataset.dragTicket&&!savingTrims.has(id)&&trimDrag?.id!==id)window.fxDesktop.startDrag(button.dataset.dragTicket);
});
$('#media-list').addEventListener('pointerover',event=>{const button=event.target.closest('.drag-audio');if(button&&!button.dataset.dragTicket)primeDrag(button.closest('.sound'));});
window.fxDesktop.onDragError(message=>notice(message,true));
function loadAudio(sound){const signature=audioSignature(sound);if(selected!==sound.id||selectedAudioSignature!==signature){audio.pause();selected=sound.id;selectedAudioSignature=signature;audio.src='/api/audio/'+sound.id+'?revision='+encodeURIComponent(signature);audio.load();}}
async function play(id){if(savingTrims.has(id)||trimDrag?.id===id){notice('Wait for the trim to finish saving.');return}if(selected===id&&!audio.paused){audio.pause();return}const sound=items.find(item=>item.id===id)||(reference?.id===id?reference:await api('item/'+id));loadAudio(sound);await audio.play();syncPlayer();}
for(const event of ['timeupdate','play','pause','ended','loadedmetadata'])audio.addEventListener(event,syncPlayer);
audio.addEventListener('error',()=>notice('The audio file could not be played. Check its location using “Show in Finder”.',true));
$('#media-list').addEventListener('input',event=>{if(event.target.matches('.wave input')){const id=event.target.closest('.sound').dataset.id,sound=items.find(x=>x.id===id),trim=trimRange(sound),revision=audioSignature(sound);if(savingTrims.has(id)||trimDrag?.id===id)return;const value=Math.max(0,Math.min(trim.end-trim.start,Number(event.target.value)/1000*sourceDuration(sound)-trim.start));const seek=()=>{if(selected===id&&selectedAudioSignature===revision){audio.currentTime=Math.min(value,audio.duration||value);syncPlayer()}};if(selected!==id||selectedAudioSignature!==revision){loadAudio(sound);audio.addEventListener('loadedmetadata',seek,{once:true});}else seek();}});
$('#media-list').addEventListener('click',async event=>{
 const button=event.target.closest('button[data-action]'),row=button?.closest('.sound');if(!row)return;const sound=items.find(x=>x.id===row.dataset.id),action=button.dataset.action;
 try{
  if(action==='play')await play(sound.id);
  else if(action==='favorite'){await api('favorite/'+sound.id,{favorite:!sound.favorite});await refreshMedia();}
  else if(action==='new-project'){showView('projects');openProjectForm(false);}
  else if(action==='reuse')await reuse(sound.settings);
  else if(action==='reference'){reference=sound;if($('#mode').value==='text')$('#mode').value='variation';showView('generate');syncMode();saveDraft();}
  else if(action==='reveal')await window.fxDesktop.reveal(sound.id);
  else if(action==='license')await window.fxDesktop.openLicense(sound.id);
  else if(action==='model-license')await window.fxDesktop.openLink(modelSources[sound.settings.model||'sm-sfx']);
  else if(action==='reset-trim'){pauseForTrim(sound.id);trimDrafts.set(sound.id,{start:0,end:sourceDuration(sound)});await persistTrim(sound.id);}
  else if(action.startsWith('zoom-'))changeZoom(row,action==='zoom-fit'?1:(waveZoom.get(sound.id)?.factor||1)*(action==='zoom-in'?2:.5));
  else if(action==='drag-audio'&&!button.dataset.dragTicket)await primeDrag(row);
  else if(['wav','mp3'].includes(action)){button.disabled=true;const result=await window.fxDesktop.exportAudio(sound.id,action,sound.title);if(!result.cancelled)notice('Sound saved: '+result.path);}
 }catch(error){notice(error.message,true)}finally{if(button.isConnected&&['wav','mp3'].includes(action)){button.disabled=false;updateTrimRow(row);}}
});
async function reuse(saved){
 const changed=saved.model!=='medium',settings=normalizeModelSettings(saved);
 showView('generate');for(const key of baseFields)$('#'+key).value=settings[key]??'';
 for(const key of editingFields)if(settings[key]!==undefined)$('#'+key).value=settings[key];
 $('#mode').value=settings.mode||'text';reference=null;
 if(settings.reference_id)reference=await api('item/'+settings.reference_id);
 syncModelControls(false);renderModelState();saveDraft();$('#prompt').focus();
 notice(changed?'The original model was removed. Medium is selected with 8 steps and CFG 1. Your prompt, seed and duration are restored.':'Settings restored. Start the job with “'+$('#generate-button').textContent+'”.');
}
function syncForm(){$('#character-count').textContent=`${$('#prompt').value.length.toLocaleString('en-US')} / 2,000`;$('#negative_prompt').disabled=selectedModel()?.negative_prompt===false||Number($('#cfg').value)===1;}
$('#prompt').addEventListener('input',syncForm);$('#cfg').addEventListener('input',syncForm);
$('#generate-form').addEventListener('submit',async event=>{
 event.preventDefault();const button=$('#generate-button');button.disabled=true;
 const settings={};for(const key of [...baseFields,...editingFields])settings[key]=$('#'+key).value;if(reference)settings.reference_id=reference.id;if(selectedModel()?.negative_prompt===false)settings.negative_prompt='';
 try{const data=await api('generate',settings);currentJob=data.id;shown=30;lastMediaSignature='';$('#notice').hidden=true;await poll();await refreshMedia();}catch(error){notice(error.message,true)}finally{updateGenerateButton();}
});
document.addEventListener('click',event=>{const button=event.target.closest('[data-view]');if(button)showView(button.dataset.view);const example=event.target.closest('[data-example]');if(example){const data=examples[example.dataset.example];$('#prompt').value=data.prompt;if($('#mode').value==='text')$('#seconds').value=data.seconds;syncForm();saveDraft();$('#prompt').focus();}});
$('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{shown=30;refreshMedia().catch(error=>notice(error.message,true))},180)});
$('#category').addEventListener('change',()=>{shown=30;refreshMedia().catch(error=>notice(error.message,true))});$('#more').addEventListener('click',()=>{shown+=30;renderMedia()});
function renderQueue(){
 if(!status)return;const jobs=(view==='projects'?projectJobs:status.jobs).filter(job=>['queued','running','cancelling'].includes(job.state) || (job.state==='cancelled' && job.id===currentJob) || ['failed','interrupted'].includes(job.state) && Date.now()/1000-job.created<3600);
 const signature=JSON.stringify([view,jobs,status.projects]);if(signature===lastQueueSignature)return;lastQueueSignature=signature;$('#queue-section').hidden=!jobs.length||!['generate','projects'].includes(view);
 const labels={queued:'Queued',running:'Generating',cancelling:'Cancelling',cancelled:'Cancelled',failed:'Failed',interrupted:'Interrupted'};
 $('#queue').innerHTML=jobs.slice().reverse().map(job=>{
 const active=['queued','running','cancelling'].includes(job.state),running=job.state==='running',percent=job.stage===3&&job.total?Math.round(job.step/job.total*100):0;
 return `<div class="job" data-job="${job.id}"><div class="job-top"><div><p class="job-title">${escape(job.settings.prompt)}</p><p class="job-info">${job.settings.origin==='agent'?'Agent · ':''}${job.settings.project_id?escape(status.projects.find(p=>p.id===job.settings.project_id)?.name||'Project')+' · ':''}${escape(modelName(job.settings.model))} · ${labels[job.state]} · ${duration(job.elapsed)}${running?' · '+escape(job.message):''}</p></div><button data-job-action="${active?'cancel':'retry'}" ${job.state==='cancelling'?'disabled':''}>${active?'Cancel':'Retry'}</button></div>${running?`<div class="job-progress ${percent?'':'indeterminate'}" role="progressbar" aria-label="Sound generation" ${percent?`aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100"`:''}><span data-progress="${percent||28}"></span></div>`:''}${job.error?`<p class="job-error">${escape(job.error)}</p>`:''}</div>`;
 }).join('');
 $('#queue').querySelectorAll('[data-progress]').forEach(span=>{span.style.width=span.dataset.progress+'%'});
}
$('#queue').addEventListener('click',async event=>{const button=event.target.closest('[data-job-action]');if(!button)return;const job=(view==='projects'?projectJobs:status.jobs).find(job=>job.id===button.closest('.job').dataset.job);try{if(button.dataset.jobAction==='cancel'){button.disabled=true;await api('cancel/'+job.id,{});await poll()}else await reuse(job.settings);}catch(error){notice(error.message,true)}});
function renderSetup(){
 if(!status)return;
 const downloading=['running','cancelling'].includes(status.setup.state);
 const repair=status.packaged?'The bundled runtime is incomplete. Reinstall FX Studio; your saved sounds are retained.':'The runtime is incomplete. Run '+(status.platform==='win32'?'Build-Windows.ps1':'Einrichten.command')+' in the project folder.';
 const models=status.models.map(model=>`<section class="setup-section"><h2>${escape(model.model)}</h2><p>${model.ready?'The required model files and runtime are installed.':'Setup is incomplete.'} ${escape(model.engine)}.</p>${model.missing.length?`<p>Missing files: ${escape(model.missing.join(', '))}</p>`:''}${model.dependencies.length||model.runtime_ready===false?`<p>${repair}</p>`:''}${!model.ready&&!model.dependencies.length&&model.runtime_ready!==false?`<button data-download-model="${model.id}" class="primary" ${downloading?'disabled':''}>${downloading?'Downloading weights …':model.setup.state==='paused'?'Resume download':model.setup.state==='failed'?'Retry download':'Install '+escape(model.model)}</button><p>About ${model.download_gib.toLocaleString('en-US')} GiB remaining. Existing files are reused.</p>`:''}<p>${escape(model.setup.message)}</p><button data-link="${escape(model.model_url)}">Model card</button></section>`).join('');
 const agents=status.agents;
 const agentSection=`<section class="setup-section"><h2>Local agents</h2><p>${agents.enabled?'Agent access is on.':'Agent access is off.'} Create sounds and asset packs from a local agent. Jobs appear here and use the same model and queue.</p><button data-agent-action="${agents.enabled?'disable':'enable'}" class="${agents.enabled?'':'primary'}">${agents.enabled?'Disable agent access':'Enable agent access'}</button><button data-agent-action="install-skill">Install skill…</button><button data-agent-action="save-kit">Save agent kit…</button><p>Install the English skill in your agent’s skills folder, then start a new conversation. The skill works through MCP or the app’s bundled command-line tools.</p><dl><dt>Agent export folder</dt><dd>${escape(agents.export_root)}</dd><dt>Connection</dt><dd>MCP · standard input/output · local only</dd></dl><button data-agent-action="export-folder">Choose export folder…</button><button data-agent-action="copy-config">Copy MCP config</button><button data-agent-action="copy-codex">Copy Codex config</button><details><summary>Local HTTP API</summary><p>${escape(agents.api_url)} · Authorization: Bearer &lt;local key&gt;. The skill and MCP client read the private key automatically. No key is included in the agent kit.</p><button data-agent-action="copy-key">Copy API key</button><button data-agent-action="rotate-key">Reset API key</button><p>Resetting the key invalidates copied keys. MCP and the skill read the new key on their next call.</p></details></section>`;
 $('#setup').innerHTML=models+agentSection+`<section class="setup-section"><h2>Storage & export</h2><p>Only one model is loaded for generation. The current process exits before the next model loads. Model weights stay on disk.</p><dl><dt>Sounds and history</dt><dd>${escape(status.data_dir)}</dd><dt>Model weights</dt><dd>Shared Hugging Face cache; ${status.packaged?'links are stored in the FX Studio data folder listed above.':'the app links to it from its runtime folder.'}</dd><dt>Free disk space</dt><dd>${status.free_gb.toLocaleString('en-US')} GiB</dd><dt>MP3 export</dt><dd>${status.export_mp3?(status.packaged?'FFmpeg bundled · 320 kbit/s':'FFmpeg installed · 320 kbit/s'):(status.packaged?'The bundled exporter is missing. Reinstall FX Studio. WAV export is available.':'FFmpeg is missing. WAV export is available. Install FFmpeg and restart the app.')}</dd><dt>Sound library</dt><dd>${status.library_count} sounds · read-only access${status.library_error?'<br>'+escape(status.library_error):''}</dd></dl></section><section class="setup-section"><h2>Models & licenses</h2><p>FX Studio is open source under the MIT license.</p><button data-open-bundled-licenses>Open bundled licenses</button><p>Powered by Stability AI</p><p>Stable Audio weights use the Stable Audio Community License. T5Gemma uses the Gemma terms. The official model runtimes use the MIT license. Commercial use is subject to the model license registration and revenue limits. The app does not accept agreements on your behalf.</p><button data-link="https://stability.ai/license">Stability license</button><button data-link="https://ai.google.dev/gemma/terms">Gemma terms</button><button data-link="https://github.com/Stability-AI/stable-audio-3">Official runtime</button><p>Generation and playback run locally. Medium downloads automatically on first launch when missing. Downloads and opened source links need the internet. You can pause or resume the download.</p></section>`;
}
$('#setup').addEventListener('click',async event=>{const button=event.target.closest('button');if(!button)return;try{if(button.dataset.agentAction){button.disabled=true;const result=await window.fxDesktop.agentAction(button.dataset.agentAction);if(result.copied)notice('Copied to clipboard');else if(result.path)notice('Saved to '+result.path);if(!result.cancelled){await poll();renderSetup()}else button.disabled=false;}else if(button.hasAttribute('data-open-bundled-licenses'))await window.fxDesktop.openBundledLicenses();else if(button.dataset.link)await window.fxDesktop.openLink(button.dataset.link);else if(button.dataset.downloadModel){button.disabled=true;await api('setup',{model:button.dataset.downloadModel});await poll();renderSetup()}}catch(error){button.disabled=false;notice(error.message,true)}});
$('.profile-links').addEventListener('click',async event=>{const button=event.target.closest('button[data-link]');if(!button)return;try{await window.fxDesktop.openLink(button.dataset.link)}catch(error){notice(error.message,true)}});
$('#buy-coffee').addEventListener('click',async event=>{const button=event.currentTarget;try{await window.fxDesktop.openLink(button.dataset.link)}catch(error){notice(error.message,true)}});
let skillCopyTimer;
$('#copy-agent-skill').addEventListener('click',async()=>{
 const button=$('#copy-agent-skill'),label=$('#agent-skill-label');clearTimeout(skillCopyTimer);button.disabled=true;
 try{await window.fxDesktop.copyAgentSkill();label.textContent='Skill copied';button.classList.add('copied');}
 catch(error){label.textContent='Copy failed';notice('The agent skill could not be copied: '+error.message,true);}
 finally{button.disabled=false;skillCopyTimer=setTimeout(()=>{label.textContent='Copy agent skill';button.classList.remove('copied')},3500);}
});
function renderDownload(){
 const model=selectedModel(),box=$('#model-download');if(!model)return;
 box.hidden=model.ready;if(model.ready)return;
 const state=status.setup.state,active=['running','cancelling'].includes(state),progress=status.setup.progress;
 const percent=progress?.total?Math.min(100,Math.floor(100*progress.bytes/progress.total)):null;
 const title=state==='running'?(progress?.phase==='verifying'?'Verifying Medium':'Downloading Medium')+(percent===null?'':` · ${percent}%`):state==='cancelling'?'Stopping download…':state==='paused'?'Medium download paused':state==='failed'?'Medium download needs attention':'Medium is not installed';
 $('#download-title').textContent=title;
 $('#download-message').textContent=status.setup.message||`About ${model.download_gib.toLocaleString('en-US')} GiB of model files are needed. Existing files are reused.`;
 const button=$('#download-action');button.textContent=active?'Pause download':state==='paused'?'Resume download':state==='failed'?'Retry download':'Download Medium';
 button.disabled=state==='cancelling';button.dataset.action=active?'pause':'resume';
 if(model.dependencies.length||model.runtime_ready===false){button.textContent='Open Setup';button.disabled=false;button.dataset.action='setup';}
 box.classList.toggle('error',state==='failed');
 const bar=$('#download-progress');bar.hidden=!active;bar.classList.toggle('indeterminate',percent===null);
 const span=bar.querySelector('span');span.style.width=(percent===null?28:percent)+'%';
 if(percent===null)bar.removeAttribute('aria-valuenow');else{bar.setAttribute('aria-valuenow',percent);bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');}
}
$('#download-action').addEventListener('click',async()=>{
 const button=$('#download-action');if(button.dataset.action==='setup'){showView('setup');return;}button.disabled=true;
 try{await api(button.dataset.action==='pause'?'cancel-setup':'setup',{});await poll();}catch(error){notice(error.message,true);renderDownload();}
});
function renderModelState(){
 const model=selectedModel();if(!model)return;
 const label='Medium';
 $('#sidebar-family').textContent='Stable Audio 3';
 $('#sidebar-model').textContent=label+' · '+model.runtime;
 $('#model-badge').textContent=model.ready?label+' ready · local':status.setup.state==='running'?label+' · downloading':label+' · setup required';
 $('#model-badge').classList.toggle('ready',model.ready);$('#model-badge').classList.toggle('problem',!model.ready);
 updateGenerateButton();
 $('#generate-hint').textContent=model.ready?'One model in memory. Jobs run one at a time.':status.setup.state==='running'?'Medium is downloading. Generation becomes available when it is ready.':'Resume the model download or open Setup.';
 if(appliedModel!==model.id){syncModelControls(false);appliedModel=model.id;}
}
let appliedModel=null;
function syncModelControls(resetDefaults){
 const model=selectedModel();if(!model)return;
 $('#seconds').max=model.max_seconds;$('#steps').max=model.max_steps;
 for(const option of $('#mode').options)option.disabled=option.value!=='text'&&!model.editing;
 if(!model.editing)$('#mode').value='text';
 if(resetDefaults||Number($('#steps').value)>model.max_steps)$('#steps').value=model.default_steps;
 if(resetDefaults)$('#cfg').value=model.default_cfg;
 if(Number($('#seconds').value)>model.max_seconds)$('#seconds').value=model.max_seconds;
 $('#sampling-help').textContent='Stable Audio defaults: 8 steps and CFG 1. The negative prompt applies when CFG differs from 1. Keep the same seed to compare settings.';
 syncMode();syncForm();
}
$('#model').addEventListener('change',()=>{syncModelControls(true);renderModelState();saveDraft()});
let setupSignature='';
async function poll(){
 status=await api('status');syncProjects();renderModelState();renderDownload();renderQueue();
 $('.local-label').textContent=status.platform==='win32'?'Local on your PC':'Local on your Mac';
 if(view==='setup'){const signature=JSON.stringify([status.models,status.setup,status.free_gb,status.export_mp3,status.agents?.enabled,status.agents?.export_root]);if(signature!==setupSignature){setupSignature=signature;renderSetup();}}
 if(view!=='setup')await refreshMedia();
}
async function heartbeat(){try{await poll()}catch(error){$('#model-badge').textContent='Service unavailable';$('#model-badge').classList.add('problem');$('#generate-button').disabled=true;notice('The local service is unavailable. Restart FX Studio. '+error.message,true)}finally{setTimeout(heartbeat,1000)}}
window.addEventListener('resize',()=>{document.querySelectorAll('.sound').forEach(row=>{if(waves.has(row.dataset.id)){applyZoom(row);drawWave(row,waves.get(row.dataset.id));}})});
for(const button of document.querySelectorAll('.nav-button'))button.insertAdjacentHTML('afterbegin',svg(button.dataset.view));
function saveDraft(){const draft={};for(const key of [...baseFields,...editingFields])draft[key]=$('#'+key).value;if(reference)draft.reference_id=reference.id;try{localStorage.setItem('fx-draft',JSON.stringify(draft))}catch{}}
$('#generate-form').addEventListener('input',saveDraft);$('#generate-form').addEventListener('change',saveDraft);
try{
 const saved=JSON.parse(localStorage.getItem('fx-draft')||'null');
 if(saved){
  const draft=normalizeModelSettings(saved);
  for(const key of [...baseFields,...editingFields])if(draft[key]!==undefined){if(key==='project_id')pendingGenerationProject=draft[key];else $('#'+key).value=draft[key];}
  if(draft.reference_id)api('item/'+draft.reference_id).then(item=>{reference=item;syncMode()}).catch(()=>{$('#mode').value='text';syncMode()});
  if(saved.model!=='medium'){
   localStorage.setItem('fx-draft',JSON.stringify(draft));
   notice('Medium is selected. Your saved description is restored; sampling steps and CFG use the Medium defaults.');
  }
 }
}catch{}


function updateGenerateButton(){const editing=$('#mode').value!=='text';$('#generate-button').disabled=!selectedModel()?.ready||['running','cancelling'].includes(status?.setup.state)||editing&&!reference;$('#generate-button').textContent={text:'Generate sound',variation:'Generate variation',inpaint:'Edit section'}[$('#mode').value];}
function syncMode(){
 const mode=$('#mode').value,editing=mode!=='text';$('#reference-panel').hidden=!editing;$('#inpaint-fields').hidden=mode!=='inpaint';$('#inpaint-note').hidden=mode!=='inpaint';$('#seconds').readOnly=editing;
 for(const key of ['strength','start','end'])$('#'+key).disabled=!editing||(key!=='strength'&&mode!=='inpaint');
 $('#reference-title').textContent=reference?reference.title+' · '+duration(reference.duration):'Choose a sound from History or the library using “Use as reference”. References must be 0.5–30 seconds long.';
 $('#play-reference').hidden=!reference;
 $('#reference-license').textContent=reference?.kind==='library'?(reference.license.status==='documented_bundle'?'Sonniss bundle license documented.':'The reference source and usage rights are not documented.'):'';
 if(editing&&reference){$('#seconds').value=reference.duration;$('#start').max=reference.duration;$('#end').max=reference.duration;if(Number($('#end').value)>reference.duration)$('#end').value=reference.duration;}
 updateGenerateButton();
}
$('#mode').addEventListener('change',syncMode);$('#choose-reference').addEventListener('click',()=>showView('history'));$('#play-reference').addEventListener('click',async()=>{try{await play(reference.id)}catch(error){notice(error.message,true)}});

syncForm();syncMode();heartbeat();
