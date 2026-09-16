// Central unificada V8. Minha Gestão continua fisicamente separada do estado
// da Transformação KAZ, mas agora usa a mesma leitura: Visão Geral, Marcos,
// Pendências e Registros.
let personalState={projects:[],is_owner:false};
let personalProjectId=null;
let personalCurrentTab='overview';
let personalUsersCache=null;

async function personalApi(url,method='GET',body=null){
  const opt={method,headers:{'X-CSRF-Token':CSRF}};
  if(body!==null){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(body)}
  const r=await fetch(url,opt); let j={}; try{j=await r.json()}catch{}
  if(!r.ok)throw new Error(j.error||`Erro ${r.status}`); return j;
}
async function refreshPersonal(){personalState=await personalApi('/api/minha-gestao/state')}
function personalProject(id){return personalState.projects.find(p=>p.id===id)}
function personalBadge(s){return badge(s)}
function personalCount(p){const ms=p.milestones||[];return {total:ms.length,done:ms.filter(m=>m.status==='Concluído').length,risk:ms.filter(m=>m.status==='Em risco').length,progress:ms.filter(m=>m.status==='Em andamento').length}}
function personalNavVisible(){return personalState.is_owner||personalState.projects.length>0}
function personalResponsible(p){return p.owner||'A definir'}
function personalHealthBadge(health){
  const tone=health==='Crítico'?'s-risco':health==='Saudável'?'s-conc':health==='Oportunidade'?'s-analise':'s-nao';
  return `<span class="pill ${tone}">${esc(health||'Sem classificação')}</span>`;
}
function showPersonalView(name){
  $$('.view').forEach(v=>v.classList.add('hidden'));
  $('#'+name+'View').classList.remove('hidden');
  $$('.nav-btn[data-nav]').forEach(b=>b.classList.remove('active'));
  window.scrollTo({top:0,behavior:'smooth'});
}
function openMyManagement(id=null,tab='overview'){
  personalCurrentTab=tab||'overview';
  personalProjectId=id;showPersonalView('myManagement');renderMyManagement();
}
function personalTab(tab){personalCurrentTab=tab;renderMyManagement()}
function openIntegratedView(){showPersonalView('integrated');renderIntegrated()}

function personalRows(list){
  if(!list.length)return '<div class="card empty">Nenhum projeto visível.</div>';
  return `<div class="card"><table class="project-table"><thead><tr><th>Projeto</th><th>Responsável</th><th>Fase</th><th>Status</th><th>Marcos</th><th>Próximo passo</th></tr></thead><tbody>${list.map(p=>{const c=personalCount(p);return `<tr class="clickable" onclick="openMyManagement('${p.id}')"><td><b>${esc(p.name)}</b>${p.restricted?'<div class="small muted">Acesso delegado</div>':''}</td><td>${esc(personalResponsible(p))}</td><td>${esc(p.phase||'—')}</td><td>${personalBadge(p.status)}</td><td>${c.done} de ${c.total}</td><td>${esc(p.next||'—')}</td></tr>`}).join('')}</tbody></table></div>`;
}

function personalExecutiveSummary(p){
  const c=personalCount(p),categories=[...new Set((p.milestones||[]).map(m=>m.category).filter(Boolean))];
  const risk=c.risk?`${c.risk} em risco`:'nenhum marco em risco';
  return `O projeto tem ${c.total} marcos distribuídos em ${categories.length} categorias: ${c.done} concluídos, ${c.progress} em andamento e ${risk}. A relação completa, com prazo, responsável, próximo avanço e observações, está na aba Marcos.`;
}

function renderMyManagement(){
  const root=$('#myManagementView'),p=personalProject(personalProjectId);
  if(!p){
    root.innerHTML=`<div class="hero"><div><h1>Minha Gestão</h1><p>Mesma estrutura de gestão, com dados separados da Transformação KAZ.</p></div><div class="pill s-nao">${personalState.projects.length} projetos</div></div>${personalRows(personalState.projects)}`;
    return;
  }
  const c=personalCount(p),tasks=p.tasks||[];
  root.innerHTML=`<button class="btn light small" onclick="openMyManagement()">← Minha Gestão</button>
  <div class="detail-head" style="margin-top:15px"><div><div class="muted small" style="text-transform:uppercase">Minha Gestão · ${esc(p.visibility)}</div><h1>${esc(p.name)}</h1><div class="muted small">Responsável: <b>${esc(personalResponsible(p))}</b> · ${p.restricted?'Acesso ao escopo atribuído':'Visão completa do projeto'}</div></div><div class="flex wrap">${personalBadge(p.status)} ${personalHealthBadge(p.health)}</div></div>
  <div class="tabs">
    <button class="tab ${personalCurrentTab==='overview'?'active':''}" onclick="personalTab('overview')">Visão Geral</button>
    <button class="tab ${personalCurrentTab==='milestones'?'active':''}" onclick="personalTab('milestones')">Marcos (${c.total})</button>
    <button class="tab ${personalCurrentTab==='tasks'?'active':''}" onclick="personalTab('tasks')">Pendências (${tasks.filter(t=>t.status!=='Concluída').length})</button>
    <button class="tab ${personalCurrentTab==='records'?'active':''}" onclick="personalTab('records')">Registros</button>
  </div><div id="personalProjectPanel"></div>`;
  renderPersonalPanel(p);
}

function renderPersonalPanel(p){
  const root=$('#personalProjectPanel'),c=personalCount(p);
  if(personalCurrentTab==='overview'){
    root.innerHTML=`<div class="grid-kpi"><div class="kpi"><strong>${c.total}</strong><span>marcos estruturados</span></div><div class="kpi"><strong>${c.done}</strong><span>concluídos</span></div><div class="kpi"><strong>${c.progress}</strong><span>em andamento</span></div><div class="kpi"><strong>${c.risk}</strong><span>em risco</span></div></div>
    <div class="two"><div class="card"><div class="card-h"><h3>Objetivo do projeto</h3>${p.canEdit?'<button class="btn light small" onclick="editPersonalProject()">Editar</button>':''}</div><div class="pad objective">${esc(p.objective||'—')}</div></div>
    <div class="card"><div class="card-h"><h3>Responsabilidade e andamento</h3>${p.canAssign?`<button class="btn light small" onclick="assignPersonalResponsibility('project','${p.id}')">Definir responsável</button>`:''}</div><div class="pad"><div class="profile-row"><b>Responsável</b><span>${esc(personalResponsible(p))}</span></div><div class="profile-row"><b>Fase</b><span>${esc(p.phase||'—')}</span></div><div class="profile-row"><b>Último avanço</b><span>${esc(p.lastAdvance||'—')}</span></div><div class="profile-row"><b>Próximo passo</b><span>${esc(p.next||'—')}</span></div><div class="profile-row"><b>Prazo</b><span>${esc(p.deadline||'—')}</span></div></div></div></div>
    <div class="section-title"><h2>Leitura executiva dos marcos</h2><button class="btn light small" onclick="personalTab('milestones')">Ver todos os ${c.total} marcos →</button></div><div class="card"><div class="pad"><p class="smart-text" style="margin:0">${esc(personalExecutiveSummary(p))}</p></div></div>`;
    return;
  }
  if(personalCurrentTab==='milestones'){
    root.innerHTML=`<div class="section-title"><div><h2>Marcos do projeto</h2><div class="small muted">Estrutura completa recuperada das etapas originais.</div></div><span class="pill s-nao">${c.total} marcos</span></div>
    <div class="personal-milestone-list">${(p.milestones||[]).map((m,i)=>personalMilestoneCard(m,i,p)).join('')||'<div class="card empty">Nenhum marco visível.</div>'}</div>`;
    return;
  }
  if(personalCurrentTab==='tasks'){
    root.innerHTML=`<div class="section-title"><div><h2>Pendências</h2><div class="small muted">Ações operacionais separadas dos marcos.</div></div></div><div class="card"><div class="pad">${(p.tasks||[]).map(t=>`<div class="message"><div class="flex"><strong>${esc(t.title)}</strong><span class="right">${personalBadge(t.status)}</span></div><div class="muted small">${t.milestoneName?`Marco: ${esc(t.milestoneName)} · `:''}Responsável: ${esc(t.owner||'A definir')} · Prazo: ${esc(t.due||'—')} · Prioridade: ${esc(t.priority||'—')}</div>${t.canEdit?`<div class="actions"><button class="btn light small" onclick="editPersonalTask('${t.id}')">Atualizar</button></div>`:''}</div>`).join('')||'<div class="empty">Nenhuma pendência.</div>'}</div></div>`;
    return;
  }
  const journal=p.journal||[],history=p.history||[];
  root.innerHTML=`<div class="section-title"><div><h2>Registros do projeto</h2><div class="small muted">Atualizações, decisões e alterações de responsabilidade.</div></div>${p.canEdit?'<button class="btn blue small" onclick="addPersonalJournal()">＋ Novo registro</button>':''}</div>
  <div class="two"><div class="card"><div class="card-h"><h3>Registros</h3></div><div class="pad">${journal.map(j=>`<div class="message"><strong>${esc(j.title)} · ${esc(j.author)}</strong><p>${esc(j.body)}</p>${j.next?`<p class="small"><b>Próximo:</b> ${esc(j.next)}</p>`:''}</div>`).join('')||'<div class="empty">Nenhum registro.</div>'}</div></div>
  <div class="card"><div class="card-h"><h3>Histórico</h3></div><div class="pad">${history.map(h=>`<div class="message"><strong>${esc(h.action)} · ${esc(h.author)}</strong>${h.detail?`<p>${esc(h.detail)}</p>`:''}</div>`).join('')||'<div class="empty">Nenhum histórico.</div>'}</div></div></div>`;
}

function personalMilestoneCard(m,index,p){
  const responsible=m.effectiveOwner||'A definir',inherit=m.inheritsProjectOwner&&p.owner;
  return `<details class="card personal-milestone"><summary><div><div class="small muted">${esc(m.category||'Geral')} · MARCO ${index+1}</div><div class="m-name">${esc(m.name)}</div><div class="small muted">Responsável: ${esc(responsible)}${inherit?' (herdado do projeto)':''} · Prazo: ${esc(m.deadline||'A definir')}</div></div><div class="flex wrap">${personalBadge(m.status)} ${personalHealthBadge(m.health)}</div></summary><div class="personal-milestone-body"><div><b>Próximo avanço</b><p>${esc(m.next||'—')}</p></div><div><b>Observações</b><p>${esc(m.notes||'—')}</p></div>${m.canEdit||m.canAssign?`<div class="actions">${m.canEdit?`<button class="btn light small" onclick="editPersonalMilestone('${m.id}')">Atualizar marco</button>`:''}${m.canAssign?`<button class="btn light small" onclick="assignPersonalResponsibility('milestone','${m.id}')">Definir responsável</button>`:''}</div>`:''}</div></details>`;
}

function renderIntegrated(){
  const root=$('#integratedView'),all=state.projects||[];
  root.innerHTML=`<div class="hero"><div><h1>Visão Integrada</h1><p>Consolidação visual. Os dois conjuntos de dados permanecem independentes.</p></div></div><div class="section-title"><h2>Minha Gestão</h2><button class="btn light small" onclick="openMyManagement()">Abrir</button></div>${personalRows(personalState.projects)}<div class="section-title"><h2>Transformação KAZ</h2><button class="btn light small" onclick="showView('projects')">Abrir</button></div>${projectsCard(all)}`;
}

function editPersonalProject(){
  const p=personalProject(personalProjectId);
  modal(`<h2>Atualizar projeto</h2><div class="form-grid"><div class="field"><label>Status</label><select id="ppStatus">${['Não iniciado','Em andamento','Em risco','Concluído','Estruturação','Em desenvolvimento','Conceituação','Pré-operação','Implantação'].map(x=>`<option ${p.status===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Fase</label><input id="ppPhase" value="${esc(p.phase)}"></div><div class="field full"><label>Objetivo</label><textarea id="ppObjective">${esc(p.objective)}</textarea></div><div class="field full"><label>Andamento atual</label><textarea id="ppCurrent">${esc(p.current)}</textarea></div><div class="field full"><label>Último avanço</label><textarea id="ppLast">${esc(p.lastAdvance)}</textarea></div><div class="field full"><label>Próximo passo</label><textarea id="ppNext">${esc(p.next)}</textarea></div><div class="field"><label>Visibilidade</label><select id="ppVisibility">${['Privado','Delegado','Projeto/Compartilhado','KAZ'].map(x=>`<option ${p.visibility===x?'selected':''}>${x}</option>`).join('')}</select></div></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalProject()">Salvar</button></div>`);
}
async function savePersonalProject(){try{await personalApi(`/api/minha-gestao/projects/${personalProjectId}`,'POST',{action:'update',status:$('#ppStatus').value,phase:$('#ppPhase').value,objective:$('#ppObjective').value,current:$('#ppCurrent').value,lastAdvance:$('#ppLast').value,next:$('#ppNext').value,visibility:$('#ppVisibility').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}

function editPersonalMilestone(id){
  const p=personalProject(personalProjectId),m=p.milestones.find(x=>x.id===id);
  modal(`<h2>Atualizar marco</h2><div class="form-grid"><div class="field"><label>Categoria</label><input id="pmCategory" value="${esc(m.category||'')}"></div><div class="field"><label>Status</label><select id="pmStatus">${['Não iniciado','Em andamento','Em risco','Concluído'].map(x=>`<option ${m.status===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Prazo</label><input id="pmDeadline" value="${esc(m.deadline||'')}"></div><div class="field"><label>Responsável efetivo</label><input disabled value="${esc(m.effectiveOwner||'A definir')}"></div><div class="field full"><label>Próximo avanço</label><textarea id="pmNext">${esc(m.next||'')}</textarea></div><div class="field full"><label>Observações</label><textarea id="pmNotes">${esc(m.notes||'')}</textarea></div></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalMilestone('${id}')">Salvar</button></div>`);
}
async function savePersonalMilestone(id){try{await personalApi(`/api/minha-gestao/milestones/${id}`,'POST',{status:$('#pmStatus').value,category:$('#pmCategory').value,deadline:$('#pmDeadline').value,next:$('#pmNext').value,notes:$('#pmNotes').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}

function editPersonalTask(id){const p=personalProject(personalProjectId),t=p.tasks.find(x=>x.id===id);modal(`<h2>Atualizar pendência</h2><div class="field"><label>Status</label><select id="ptStatus">${['Pendente','Em andamento','Concluída','Bloqueada'].map(x=>`<option ${t.status===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Responsável</label><input id="ptOwner" value="${esc(t.owner||'')}"></div><div class="field"><label>Prazo</label><input id="ptDue" value="${esc(t.due||'')}"></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalTask('${id}')">Salvar</button></div>`)}
async function savePersonalTask(id){try{await personalApi(`/api/minha-gestao/tasks/${id}`,'POST',{status:$('#ptStatus').value,owner:$('#ptOwner').value,due:$('#ptDue').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}
function addPersonalJournal(){modal(`<h2>Novo registro</h2><div class="field"><label>Título</label><input id="pjTitle"></div><div class="field"><label>Andamento / decisão</label><textarea id="pjBody"></textarea></div><div class="field"><label>Próximo passo</label><textarea id="pjNext"></textarea></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalJournal()">Registrar</button></div>`)}
async function savePersonalJournal(){try{await personalApi(`/api/minha-gestao/projects/${personalProjectId}`,'POST',{action:'journal',title:$('#pjTitle').value,body:$('#pjBody').value,next:$('#pjNext').value});closeModal();await refreshPersonal();renderMyManagement()}catch(e){alert(e.message)}}

async function personalUsers(){if(personalUsersCache)return personalUsersCache;personalUsersCache=await personalApi('/api/minha-gestao/users');return personalUsersCache}
async function assignPersonalResponsibility(level,targetId){
  try{
    const p=personalProject(personalProjectId),target=level==='project'?p:p.milestones.find(m=>m.id===targetId),users=await personalUsers();
    const selected=target.responsibleUserId||'';
    modal(`<h2>Definir responsável</h2><div class="field"><label>${level==='project'?'Projeto':'Marco'}</label><input disabled value="${esc(target.name)}"></div><div class="field"><label>Responsável</label><select id="personalResponsibleUser"><option value="">${level==='project'?'Sem responsável':'Herdar responsável do projeto'}</option>${users.map(u=>`<option value="${esc(u.username)}" ${String(u.id)===String(selected)?'selected':''}>${esc(u.display_name)}</option>`).join('')}</select></div><div class="info" style="margin-top:12px">Ao assumir o projeto, a pessoa passa a vê-lo e editá-lo. No marco, o acesso fica restrito ao marco; sem responsável próprio, ele herda o responsável do projeto.</div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="savePersonalResponsibility('${level}','${targetId}')">Salvar</button></div>`);
  }catch(e){alert(e.message)}
}
async function savePersonalResponsibility(level,targetId){
  try{
    const username=$('#personalResponsibleUser').value;
    if(level==='project')await personalApi(`/api/minha-gestao/projects/${targetId}`,'POST',{action:'update',responsibleUsername:username});
    else await personalApi(`/api/minha-gestao/milestones/${targetId}`,'POST',{responsibleUsername:username});
    closeModal();await refreshPersonal();renderMyManagement();
  }catch(e){alert(e.message)}
}

(async function bootUnifiedCentral(){
  try{await refreshPersonal();const visible=personalNavVisible();$$('.personal-nav').forEach(x=>x.classList.toggle('hidden',!visible));if(!personalState.is_owner)$('#integratedNav')?.classList.add('hidden')}
  catch(e){console.error('Falha ao carregar Minha Gestão',e);$$('.personal-nav').forEach(x=>x.classList.add('hidden'))}
})();
