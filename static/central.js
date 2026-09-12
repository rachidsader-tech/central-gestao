// Central unificada V6. Mantém a interface KAZ e adiciona Minha Gestão sem
// misturar seus registros com state.projects (que é exclusivamente KAZ).
let personalState={projects:[],is_owner:false};
let personalProjectId=null;

async function personalApi(url,method='GET',body=null){
  const opt={method,headers:{'X-CSRF-Token':CSRF}};
  if(body!==null){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(body)}
  const r=await fetch(url,opt); let j={}; try{j=await r.json()}catch{}
  if(!r.ok)throw new Error(j.error||`Erro ${r.status}`); return j;
}
async function refreshPersonal(){personalState=await personalApi('/api/minha-gestao/state')}
function personalProject(id){return personalState.projects.find(p=>p.id===id)}
function personalBadge(s){return badge(s)}
function personalCount(p){const ms=p.milestones||[];return {total:ms.length,done:ms.filter(m=>m.status==='Concluído').length,risk:ms.filter(m=>m.status==='Em risco').length}}
function personalNavVisible(){return personalState.is_owner||personalState.projects.length>0}
function showPersonalView(name){
  $$('.view').forEach(v=>v.classList.add('hidden'));
  $('#'+name+'View').classList.remove('hidden');
  $$('.nav-btn[data-nav]').forEach(b=>b.classList.remove('active'));
  window.scrollTo({top:0,behavior:'smooth'});
}
function openMyManagement(id=null){personalProjectId=id;showPersonalView('myManagement');renderMyManagement()}
function openIntegratedView(){showPersonalView('integrated');renderIntegrated()}
function personalRows(list,open){
  if(!list.length)return '<div class="card empty">Nenhum projeto visível.</div>';
  return `<div class="card"><table class="project-table"><thead><tr><th>Projeto</th><th>Dono</th><th>Fase</th><th>Status</th><th>Marcos</th><th>Próximo passo</th></tr></thead><tbody>${list.map(p=>{const c=personalCount(p);return `<tr class="clickable" onclick="openMyManagement('${p.id}')"><td><b>${esc(p.name)}</b>${p.restricted?'<div class="small muted">Acesso delegado</div>':''}</td><td>${esc(p.owner)}</td><td>${esc(p.phase||'—')}</td><td>${personalBadge(p.status)}</td><td>${c.done} de ${c.total}</td><td>${esc(p.next||'—')}</td></tr>`}).join('')}</tbody></table></div>`
}
function renderMyManagement(){
  const root=$('#myManagementView'); const p=personalProject(personalProjectId);
  if(!p){
    root.innerHTML=`<div class="hero"><div><h1>Minha Gestão</h1><p>Projetos pessoais, separados da Transformação KAZ.</p></div><div class="pill s-nao">${personalState.projects.length} projetos</div></div>${personalRows(personalState.projects)}`;
    return;
  }
  const c=personalCount(p), editable=p.canEdit;
  root.innerHTML=`<button class="btn light small" onclick="openMyManagement()">← Minha Gestão</button>
  <div class="detail-head" style="margin-top:15px"><div><div class="muted small" style="text-transform:uppercase">Minha Gestão · ${esc(p.visibility)}</div><h1>${esc(p.name)}</h1><div class="muted small">Dono: <b>${esc(p.owner)}</b> · ${p.restricted?'Acesso somente ao conteúdo delegado':'Projeto pessoal'}</div></div><div>${personalBadge(p.status)}</div></div>
  <div class="tabs"><button class="tab active" onclick="renderMyManagement()">Visão geral</button></div>
  <div class="two"><div class="card"><div class="card-h"><h3>Objetivo</h3>${editable?'<button class="btn light small" onclick="editPersonalProject()">Editar</button>':''}</div><div class="pad objective">${esc(p.objective)}</div></div><div class="card"><div class="card-h"><h3>Andamento</h3></div><div class="pad"><div class="profile-row"><b>Fase</b><span>${esc(p.phase||'—')}</span></div><div class="profile-row"><b>Último avanço</b><span>${esc(p.lastAdvance||'—')}</span></div><div class="profile-row"><b>Próximo passo</b><span>${esc(p.next||'—')}</span></div><div class="profile-row"><b>Prazo</b><span>${esc(p.deadline||'—')}</span></div></div></div></div>
  <div class="section-title"><h2>Marcos / frentes</h2>${editable?`<button class="btn light small" onclick="delegatePersonal('project','${p.id}')">Delegar projeto</button>`:''}</div>
  <div class="card"><div class="pad">${(p.milestones||[]).map((m,i)=>`<div class="milestone"><div class="m-row"><div><div class="m-name">${i+1}. ${esc(m.name)}</div><div class="muted small">Responsável: ${esc(m.owner||'—')} · ${esc(m.next||'')}</div></div><div>${personalBadge(m.status)}</div>${editable?`<button class="btn light small" onclick="editPersonalMilestone('${m.id}')">Atualizar</button><button class="btn light small" onclick="delegatePersonal('milestone','${m.id}')">Delegar</button>`:''}</div></div>`).join('')||'<div class="empty">Nenhum marco.</div>'}</div></div>
  <div class="section-title"><h2>Pendências / tarefas</h2></div>
  <div class="card"><div class="pad">${(p.tasks||[]).map(t=>`<div class="message"><div class="flex"><strong>${esc(t.title)}</strong><span class="right">${personalBadge(t.status)}</span></div><div class="muted small">Responsável: ${esc(t.owner||'—')} · Prazo: ${esc(t.due||'—')} · Prioridade: ${esc(t.priority||'—')}</div>${editable?`<div class="actions"><button class="btn light small" onclick="editPersonalTask('${t.id}')">Atualizar</button><button class="btn light small" onclick="delegatePersonal('task','${t.id}')">Delegar</button></div>`:''}</div>`).join('')||'<div class="empty">Nenhuma pendência.</div>'}</div></div>
  ${p.restricted?'':`<div class="section-title"><h2>Diário</h2>${editable?'<button class="btn light small" onclick="addPersonalJournal()">Registrar</button>':''}</div><div class="card"><div class="pad">${(p.journal||[]).map(j=>`<div class="message"><strong>${esc(j.title)} · ${esc(j.author)}</strong><p>${esc(j.body)}</p>${j.next?`<p class="small"><b>Próximo:</b> ${esc(j.next)}</p>`:''}</div>`).join('')||'<div class="empty">Nenhum registro no diário.</div>'}</div></div>
  <div class="section-title"><h2>Histórico</h2></div><div class="card"><div class="pad">${(p.history||[]).map(h=>`<div class="message"><strong>${esc(h.action)} · ${esc(h.author)}</strong><p>${esc(h.detail||'')}</p></div>`).join('')||'<div class="empty">Nenhum histórico.</div>'}</div></div>`}`;
}
function renderIntegrated(){
  const root=$('#integratedView'); const all=state.projects||[];
  root.innerHTML=`<div class="hero"><div><h1>Visão Integrada</h1><p>Consolidação visual. Os registros de Minha Gestão e Transformação KAZ continuam independentes.</p></div></div>
  <div class="section-title"><h2>Minha Gestão</h2><button class="btn light small" onclick="openMyManagement()">Abrir</button></div>${personalRows(personalState.projects)}
  <div class="section-title"><h2>Transformação KAZ</h2><button class="btn light small" onclick="showView('projects')">Abrir</button></div>${projectsCard(all)}`;
}
function editPersonalProject(){const p=personalProject(personalProjectId); modal(`<h2>Atualizar projeto</h2><div class="form-grid"><div class="field"><label>Status</label><select id="ppStatus">${['Não iniciado','Em andamento','Em risco','Concluído','Estruturação','Em desenvolvimento','Conceituação','Pré-operação','Implantação'].map(x=>`<option ${p.status===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Fase</label><input id="ppPhase" value="${esc(p.phase)}"></div><div class="field full"><label>Objetivo</label><textarea id="ppObjective">${esc(p.objective)}</textarea></div><div class="field full"><label>Andamento atual</label><textarea id="ppCurrent">${esc(p.current)}</textarea></div><div class="field full"><label>Último avanço</label><textarea id="ppLast">${esc(p.lastAdvance)}</textarea></div><div class="field full"><label>Próximo passo</label><textarea id="ppNext">${esc(p.next)}</textarea></div><div class="field"><label>Visibilidade</label><select id="ppVisibility">${['Privado','Delegado','Projeto/Compartilhado','KAZ'].map(x=>`<option ${p.visibility===x?'selected':''}>${x}</option>`).join('')}</select></div></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalProject()">Salvar</button></div>`) }
async function savePersonalProject(){try{await personalApi(`/api/minha-gestao/projects/${personalProjectId}`,'POST',{action:'update',status:$('#ppStatus').value,phase:$('#ppPhase').value,objective:$('#ppObjective').value,current:$('#ppCurrent').value,lastAdvance:$('#ppLast').value,next:$('#ppNext').value,visibility:$('#ppVisibility').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}
function editPersonalMilestone(id){const p=personalProject(personalProjectId),m=p.milestones.find(x=>x.id===id);modal(`<h2>Atualizar marco</h2><div class="field"><label>Status</label><select id="pmStatus">${['Não iniciado','Em andamento','Em risco','Concluído'].map(x=>`<option ${m.status===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Responsável</label><input id="pmOwner" value="${esc(m.owner)}"></div><div class="field"><label>Próximo passo</label><textarea id="pmNext">${esc(m.next)}</textarea></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalMilestone('${id}')">Salvar</button></div>`) }
async function savePersonalMilestone(id){try{await personalApi(`/api/minha-gestao/milestones/${id}`,'POST',{status:$('#pmStatus').value,owner:$('#pmOwner').value,next:$('#pmNext').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}
function editPersonalTask(id){const p=personalProject(personalProjectId),t=p.tasks.find(x=>x.id===id);modal(`<h2>Atualizar pendência</h2><div class="field"><label>Status</label><select id="ptStatus">${['Pendente','Em andamento','Concluída','Bloqueada'].map(x=>`<option ${t.status===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Responsável</label><input id="ptOwner" value="${esc(t.owner)}"></div><div class="field"><label>Prazo</label><input id="ptDue" value="${esc(t.due)}"></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalTask('${id}')">Salvar</button></div>`) }
async function savePersonalTask(id){try{await personalApi(`/api/minha-gestao/tasks/${id}`,'POST',{status:$('#ptStatus').value,owner:$('#ptOwner').value,due:$('#ptDue').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}
function addPersonalJournal(){modal(`<h2>Novo registro no diário</h2><div class="field"><label>Título</label><input id="pjTitle"></div><div class="field"><label>Andamento / decisão</label><textarea id="pjBody"></textarea></div><div class="field"><label>Próximo passo</label><textarea id="pjNext"></textarea></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalJournal()">Registrar</button></div>`) }
async function savePersonalJournal(){try{await personalApi(`/api/minha-gestao/projects/${personalProjectId}`,'POST',{action:'journal',title:$('#pjTitle').value,body:$('#pjBody').value,next:$('#pjNext').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}
async function delegatePersonal(level,targetId){const username=prompt('Usuário para delegar (ex.: ricardo):');if(!username?.trim())return;const permission=(prompt('Permissão: edit ou view','edit')||'').trim();if(!['edit','view'].includes(permission)){alert('Use edit ou view.');return}try{await personalApi('/api/minha-gestao/delegate','POST',{level,targetId,username,permission});await refreshPersonal();renderMyManagement();alert('Delegação registrada. O acesso fica restrito ao escopo delegado.')}catch(e){alert(e.message)}}

(async function bootUnifiedCentral(){
  try{await refreshPersonal(); const visible=personalNavVisible(); $$('.personal-nav').forEach(x=>x.classList.toggle('hidden',!visible));
    if(!personalState.is_owner)$('#integratedNav')?.classList.add('hidden');
  }catch(e){console.error('Falha ao carregar Minha Gestão',e);$$('.personal-nav').forEach(x=>x.classList.add('hidden'))}
})();
