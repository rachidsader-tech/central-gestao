function depsCard(list){
  if(!list?.length)return '<div class="card empty">Nenhuma pendência externa.</div>';
  return `<div class="card"><table class="dep-table"><thead><tr><th>Projeto</th><th>Assunto</th><th>Diretor</th><th>Prazo</th><th>Status</th><th></th></tr></thead><tbody>${list.map(d=>`
    <tr class="clickable" onclick="openDependency('${d.id}')">
      <td>${esc(d.projectName||project(d.projectId)?.name||d.projectId)}</td>
      <td><b>${esc(d.subject)}</b><br><span class="muted">${esc(d.requester)}</span></td>
      <td>${esc(d.director)}</td><td>${esc(d.deadline||'—')}</td><td>${badge(d.status)}</td><td>›</td>
    </tr>`).join('')}</tbody></table></div>`
}
function renderDependencies(){
  const list=isDirection?(state.dependencies||[]):(state.dependencies||[]).filter(d=>d.projectId===USER.project_id);
  $('#dependenciesView').innerHTML=`
    <div class="hero"><div><h1>Pendências externas</h1><p>${isDirection?'Todas as pendências dos projetos.':'Pendências do seu projeto e respostas da Diretoria.'}</p></div>${USER.project_id?'<button class="btn blue" onclick="openDependencyModal()">＋ Nova pendência</button>':''}</div>
    ${depsCard(list)}
  `
}
function renderDirector(){
  if(!isDirection){showView('home');return}
  const ds=state.dependencies||[];
  $('#directorView').innerHTML=`
    <div class="hero"><div><h1>Pendências da Diretoria</h1><p>Caixa de entrada executiva. Cada pendência tem um diretor responsável, mas os quatro diretores podem analisar e responder.</p></div></div>
    <div class="grid-kpi">
      <div class="kpi"><strong>${ds.filter(d=>d.status==='Aberta').length}</strong><span>Abertas</span></div>
      <div class="kpi"><strong>${ds.filter(d=>d.status==='Em análise').length}</strong><span>Em análise</span></div>
      <div class="kpi"><strong>${ds.filter(d=>d.status==='Respondida').length}</strong><span>Respondidas</span></div>
      <div class="kpi"><strong>${ds.filter(d=>d.status==='Resolvida').length}</strong><span>Resolvidas</span></div>
    </div>
    ${depsCard(ds)}
  `
}
function openDependencyModal(){
  const pid=currentProjectId&&canEdit(currentProjectId)?currentProjectId:USER.project_id;
  if(!pid&&!isDirection)return;
  const projects=isDirection?(state.projects||[]):[project(pid)];
  modal(`<h2>Nova pendência externa</h2>
    <div class="form-grid">
      <div class="field"><label>Projeto de origem</label><select id="depProject">${projects.map(p=>`<option value="${p.id}" ${p.id===pid?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div>
      <div class="field"><label>Diretor responsável</label><select id="depDirector">${DIRECTORS.map(d=>`<option>${esc(d)}</option>`).join('')}</select></div>
      <div class="field full"><label>Assunto</label><input id="depSubject" placeholder="Ex.: Política de desconto para carteiras"></div>
      <div class="field full"><label>O que você precisa da Diretoria?</label><textarea id="depDescription"></textarea></div>
      <div class="field"><label>Prazo</label><input id="depDeadline" type="date"></div>
    </div>
    <div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn" onclick="saveDependency()">Abrir pendência</button></div>`)
}
async function saveDependency(){
  try{
    await api('/api/dependencies','POST',{projectId:$('#depProject').value,director:$('#depDirector').value,subject:$('#depSubject').value,description:$('#depDescription').value,deadline:$('#depDeadline').value});
    closeModal();await refresh();if(currentProjectId){currentTab='dependencies';renderProject()}else renderDependencies()
  }catch(e){alert(e.message)}
}
function openDependency(id){
  const d=dep(id),p=project(d.projectId),own=USER.project_id===d.projectId,assigned=USER.display_name===d.director;
  const canResolve=isDirection||own;
  modal(`
    <div class="flex"><div><div class="muted small">${esc(p?.name||'')} · ${esc(d.requester)}</div><h2 style="margin:3px 0">${esc(d.subject)}</h2></div><div class="right">${badge(d.status)}</div></div>
    <div class="three" style="margin:14px 0">
      <div class="kpi"><span>Diretor responsável</span><strong style="font-size:16px">${esc(d.director)}</strong></div>
      <div class="kpi"><span>Prazo</span><strong style="font-size:16px">${esc(d.deadline||'—')}</strong></div>
      <div class="kpi"><span>Projeto</span><strong style="font-size:16px">${esc(p?.name||'')}</strong></div>
    </div>
    <div class="card"><div class="card-h"><h3>Solicitação</h3></div><div class="pad objective">${esc(d.description)}</div></div>
    <div class="section-title"><h2>Conversa</h2></div>
    ${(d.messages||[]).length?(d.messages||[]).map(m=>`<div class="message ${m.type==='director'?'dir':''}"><strong>${esc(m.actor)} · ${fmtDate(m.at)}</strong><p>${esc(m.text)}</p></div>`).join(''):'<div class="card empty">Ainda não há respostas ou complementos.</div>'}
    <div class="section-title"><h2>Histórico</h2></div>
    <div class="timeline">${(d.history||[]).map(h=>`<div class="event"><b class="small">${esc(h.action)}</b><div class="small">${esc(h.actor)} · ${fmtDate(h.at)}</div>${h.detail?`<small>${esc(h.detail)}</small>`:''}</div>`).join('')}</div>
    <div class="actions">
      ${isDirection&&assigned&&d.status!=='Resolvida'?`<button class="btn light" onclick="depAction('${d.id}','assume')">Assumir</button>`:''}
      ${isDirection&&d.status!=='Resolvida'?`<button class="btn blue" onclick="respondDependency('${d.id}')">Responder</button>`:''}
      ${(isDirection||own)&&d.status!=='Resolvida'?`<button class="btn light" onclick="commentDependency('${d.id}')">Adicionar informação</button>`:''}
      ${canResolve&&d.status!=='Resolvida'?`<button class="btn green" onclick="resolveDependency('${d.id}')">Marcar resolvida</button>`:''}
      ${canResolve&&d.status==='Resolvida'?`<button class="btn light" onclick="reopenDependency('${d.id}')">Reabrir</button>`:''}
      ${isDirection?`<button class="btn light" onclick="reassignDependency('${d.id}')">Trocar diretor</button>`:''}
      <button class="btn light" onclick="closeModal()">Fechar</button>
    </div>
  `)
}
async function depAction(id,action,extra={}){
  try{await api(`/api/dependencies/${id}/action`,'POST',{action,...extra});closeModal();await refresh();renderCurrent()}catch(e){alert(e.message)}
}
function respondDependency(id){const text=prompt('Resposta da Diretoria:');if(text?.trim())depAction(id,'respond',{text})}
function commentDependency(id){const text=prompt('Adicionar informação/comentário:');if(text?.trim())depAction(id,'comment',{text})}
function resolveDependency(id){const note=prompt('Conclusão da resolução (opcional):')||'';if(confirm('Marcar esta pendência como Resolvida?'))depAction(id,'resolve',{note})}
function reopenDependency(id){const reason=prompt('Motivo obrigatório da reabertura:');if(reason?.trim())depAction(id,'reopen',{reason})}
function reassignDependency(id){
  const d=dep(id),director=prompt('Novo diretor responsável: Rachid, Leo, Márcio ou Marcinho',d.director);
  if(director===null)return;
  if(!DIRECTORS.includes(director)){alert('Diretor inválido.');return}
  const reason=prompt('Motivo da alteração (opcional):')||'';
  depAction(id,'reassign',{director,reason})
}
