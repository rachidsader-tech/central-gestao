// Projetos Unificados V10
window.KAZ_PROJECTS_V10=true;
(function(){
var baseRenderHomeV10=renderHome;
var baseRenderProjectsV10=renderProjects;
var baseRenderProjectV10=renderProject;
var baseRenderSettingsV10=renderSettings;
var baseOpenProjectV10=openProject;
var baseRenderCurrentV10=renderCurrent;
var organizationCacheV10=null;
var isRachidV10=String(USER.username||'').toLowerCase()==='rachid';

function workgroupsV10(){
  var rows=(state.workgroups||[]).slice();
  if(!rows.some(function(g){return g.id==='sem-grupo'})) rows.push({id:'sem-grupo',name:'Sem grupo',order:999,active:true});
  rows.sort(function(a,b){return (Number(a.order||999)-Number(b.order||999))||String(a.name||'').localeCompare(String(b.name||''))});
  return rows;
}
function workgroupV10(id){
  return workgroupsV10().find(function(g){return g.id===(id||'sem-grupo')})||{id:'sem-grupo',name:'Sem grupo',order:999,active:true};
}
function responsibleUsernameV10(p){return String((p&&p.responsibleUsername)||'').trim().toLowerCase()}
function responsibleNameV10(p){
  return responsibleUsernameV10(p)?String((p&&p.responsibleName)||(p&&p.owner)||'').trim():'Minha Gestão';
}
function isAssignedToMeV10(p){
  return !!(p&&(responsibleUsernameV10(p)===String(USER.username||'').toLowerCase()||(!responsibleUsernameV10(p)&&USER.project_id===p.id)));
}
function assignedProjectsV10(){return (state.projects||[]).filter(isAssignedToMeV10)}
function visibleProjectsV10(){if(isRachidV10)return state.projects||[];if(isDirection||USER.role==='viewer')return (state.projects||[]).filter(function(p){return (p.workgroupId||'sem-grupo')==='transformacao-kaz'});return assignedProjectsV10()}
function unassignedProjectsV10(){return (state.projects||[]).filter(function(p){return !responsibleUsernameV10(p)})}
function openDependenciesCountV10(p){return (state.dependencies||[]).filter(function(d){return d.projectId===p.id&&d.status!=='Resolvida'}).length}

canEdit=function(pid){
  var p=project(pid);
  return !!(isDirection||(p&&USER.role!=='viewer'&&isAssignedToMeV10(p)));
};

function projectRowsV10(list){
  if(!list.length)return '<div class="card empty">Nenhum projeto neste grupo.</div>';
  var rows=list.map(function(p){
    var c=counts(p),resp=responsibleNameV10(p);
    var respHtml=resp==='Minha Gestão'?'<span class="pill v10-mine-pill">Minha Gestão</span>':esc(resp);
    return '<tr class="clickable" onclick="openProject(\''+p.id+'\')">'+
      '<td><b>'+esc(p.name)+'</b></td>'+
      '<td>'+respHtml+'</td>'+
      '<td>'+badge(p.status)+'</td>'+
      '<td>'+c.done+' de '+c.total+'</td>'+
      '<td>'+openDependenciesCountV10(p)+'</td>'+
      '<td>'+fmtDate(p.lastUpdate)+'</td></tr>';
  }).join('');
  return '<div class="card v10-project-table-wrap"><table class="project-table"><thead><tr><th>Projeto</th><th>Responsável</th><th>Status</th><th>Roadmap</th><th>Pendências</th><th>Última atualização</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}
function groupedProjectsV10(list){
  var groups=workgroupsV10(),ids=new Set(groups.map(function(g){return g.id})),html=[];
  groups.forEach(function(g){
    var rows=list.filter(function(p){var id=ids.has(p.workgroupId)?p.workgroupId:'sem-grupo';return id===g.id});
    if(!rows.length)return;
    html.push('<section class="v10-workgroup-section"><div class="section-title v10-workgroup-title"><div><h2>'+esc(g.name)+'</h2><div class="muted small">'+rows.length+' '+(rows.length===1?'projeto':'projetos')+'</div></div></div>'+projectRowsV10(rows)+'</section>');
  });
  return html.join('')||'<div class="card empty">Nenhum projeto disponível.</div>';
}

renderHome=function(){
  var root=$('#homeView'),list=visibleProjectsV10();
  var total=list.reduce(function(a,p){return a+(p.milestones?p.milestones.length:0)},0);
  var done=list.reduce(function(a,p){return a+counts(p).done},0);
  var open=(state.dependencies||[]).filter(function(d){return list.some(function(p){return p.id===d.projectId})&&d.status!=='Resolvida'}).length;
  if(isDirection){
    root.innerHTML='<div class="hero"><div><h1>Visão dos projetos</h1><p>Todos os projetos organizados por grupo de trabalho e responsabilidade.</p></div><div class="flex wrap">'+(isRachidV10?'<button class="btn light" onclick="openMyManagement()">Minha Gestão</button>':'')+'<button class="btn blue" onclick="openNewProjectV10()">＋ Novo projeto</button></div></div>'+
    '<div class="grid-kpi"><div class="kpi"><strong>'+list.length+'</strong><span>Projetos</span></div><div class="kpi"><strong>'+done+'/'+total+'</strong><span>Roadmap concluído</span></div><div class="kpi"><strong>'+open+'</strong><span>Pendências ativas</span></div>'+(isRachidV10?'<div class="kpi"><strong>'+unassignedProjectsV10().length+'</strong><span>Minha Gestão</span></div>':'')+'</div>'+
    groupedProjectsV10(list);
    return;
  }
  root.innerHTML='<div class="hero"><div><h1>Olá, '+esc(USER.display_name.split(' ')[0])+'</h1><p>Seus projetos, organizados pelos respectivos grupos de trabalho.</p></div><div class="pill s-nao">'+list.length+' '+(list.length===1?'projeto':'projetos')+'</div></div>'+groupedProjectsV10(list);
};

renderProjects=function(){
  var list=visibleProjectsV10();
  var actions=isDirection?'<div class="flex wrap">'+(isRachidV10?'<button class="btn light" onclick="openMyManagement()">Minha Gestão</button>':'')+'<button class="btn blue" onclick="openNewProjectV10()">＋ Novo projeto</button></div>':'';
  $('#projectsView').innerHTML='<div class="hero"><div><h1>Todos os projetos</h1><p>'+(isDirection?'Visão geral por grupo de trabalho. Projetos sem responsável aparecem como Minha Gestão.':'Projetos sob sua responsabilidade, separados por grupo de trabalho.')+'</p></div>'+actions+'</div>'+groupedProjectsV10(list);
};

openMyProject=function(){
  var list=assignedProjectsV10();
  if(list.length===1){openProject(list[0].id);return}
  $$('.view').forEach(function(v){v.classList.add('hidden')});
  $('#projectsView').classList.remove('hidden');
  navActive('myproject');setTitle('Meus projetos');
  $('#projectsView').innerHTML='<div class="hero"><div><h1>Meus projetos</h1><p>Projetos atribuídos a você, organizados por grupo de trabalho.</p></div><div class="pill s-nao">'+list.length+' '+(list.length===1?'projeto':'projetos')+'</div></div>'+groupedProjectsV10(list);
};
openProject=function(id,tab){
  baseOpenProjectV10(id,tab||'overview');
  if(!isDirection&&isAssignedToMeV10(project(id)))navActive('myproject');
};

function renderMyManagementV10(){
  if(!isRachidV10){showView('home');return}
  var root=$('#myManagementView'),list=unassignedProjectsV10();
  setTitle('Minha Gestão');
  root.innerHTML='<div class="hero"><div><h1>Minha Gestão</h1><p>Projetos ainda sem responsável atribuído. O grupo de trabalho é preservado independentemente da alocação.</p></div><div class="pill s-nao">'+list.length+' '+(list.length===1?'projeto':'projetos')+'</div></div>'+groupedProjectsV10(list);
}
openMyManagement=function(){
  $$('.view').forEach(function(v){v.classList.add('hidden')});
  $('#myManagementView').classList.remove('hidden');
  $$('.nav-btn').forEach(function(b){b.classList.remove('active')});
  if($('#myManagementNav'))$('#myManagementNav').classList.add('active');
  renderMyManagementV10();
};
openIntegratedView=function(){showView('projects')};
renderCurrent=function(){
  var visible=$$('.view').find(function(v){return !v.classList.contains('hidden')});
  if(visible&&visible.id==='myManagementView'){renderMyManagementV10();return}
  baseRenderCurrentV10();
};

function enhanceProjectHeaderV10(){
  var p=project(currentProjectId),head=$('#projectView .detail-head');
  if(!p||!head)return;
  var group=workgroupV10(p.workgroupId),resp=responsibleNameV10(p);
  var muted=[].slice.call(head.querySelectorAll('.muted.small'));
  if(muted[0])muted[0].textContent=group.name+(resp==='Minha Gestão'?' · Minha Gestão':'');
  if(muted[1])muted[1].innerHTML='Responsável: <b>'+esc(resp)+'</b> · '+(canEdit(p.id)?'Edição habilitada':'Modo consulta');
  if(isDirection&&!head.querySelector('[data-v10-organize]')){
    var actions=head.querySelector('.flex.wrap')||head.lastElementChild;
    var btn=document.createElement('button');
    btn.className='btn light small';btn.setAttribute('data-v10-organize','1');btn.textContent='Organizar projeto';
    btn.onclick=function(){openProjectOrganizationV10(p.id)};
    if(actions)actions.appendChild(btn);
  }
}
renderProject=function(){baseRenderProjectV10();enhanceProjectHeaderV10()};

async function organizationV10(force){
  if(organizationCacheV10&&!force)return organizationCacheV10;
  organizationCacheV10=await api('/api/project-organization');
  return organizationCacheV10;
}
window.openProjectOrganizationV10=async function(id){
  try{
    var p=project(id),org=await organizationV10(true);if(!p)return;
    var groupOptions=(org.workgroups||[]).filter(function(g){return g.active!==false||g.id===p.workgroupId}).map(function(g){return '<option value="'+esc(g.id)+'" '+(g.id===(p.workgroupId||'sem-grupo')?'selected':'')+'>'+esc(g.name)+'</option>'}).join('');
    var userOptions=(org.users||[]).map(function(u){return '<option value="'+esc(u.username)+'" '+(u.username===responsibleUsernameV10(p)?'selected':'')+'>'+esc(u.display_name)+'</option>'}).join('');
    modal('<h2>Organizar projeto</h2><div class="field"><label>Projeto</label><input disabled value="'+esc(p.name)+'"></div><div class="field"><label>Grupo de trabalho</label><select id="v10ProjectGroup">'+groupOptions+'</select></div><div class="field"><label>Responsável</label><select id="v10ProjectResponsible"><option value="">Minha Gestão · sem responsável</option>'+userOptions+'</select></div><div class="info" style="margin-top:12px">Grupo e responsável são independentes. Remover o responsável coloca o projeto em Minha Gestão sem alterar seu grupo.</div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="saveProjectOrganizationV10(\''+id+'\')">Salvar</button></div>');
  }catch(e){alert(e.message)}
};
window.saveProjectOrganizationV10=async function(id){
  try{
    await api('/api/projects/'+encodeURIComponent(id)+'/organization','POST',{workgroupId:$('#v10ProjectGroup').value,responsibleUsername:$('#v10ProjectResponsible').value});
    organizationCacheV10=null;closeModal();await refresh();
  }catch(e){alert(e.message)}
};

window.openNewProjectV10=async function(){
  try{
    var org=await organizationV10(true);
    var groupOptions=(org.workgroups||[]).filter(function(g){return g.active!==false}).map(function(g){return '<option value="'+esc(g.id)+'">'+esc(g.name)+'</option>'}).join('');
    var userOptions=(org.users||[]).map(function(u){return '<option value="'+esc(u.username)+'">'+esc(u.display_name)+'</option>'}).join('');
    modal('<h2>Novo projeto</h2><div class="field"><label>Nome do projeto</label><input id="v10NewProjectName"></div><div class="field"><label>Grupo de trabalho</label><select id="v10NewProjectGroup">'+groupOptions+'</select></div><div class="field"><label>Responsável</label><select id="v10NewProjectResponsible"><option value="">Minha Gestão · sem responsável</option>'+userOptions+'</select></div><div class="field"><label>Objetivo</label><textarea id="v10NewProjectObjective"></textarea></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="saveNewProjectV10()">Criar projeto</button></div>');
  }catch(e){alert(e.message)}
};
window.saveNewProjectV10=async function(){
  var name=$('#v10NewProjectName').value.trim();if(!name){alert('Informe o nome do projeto.');return}
  try{
    var result=await api('/api/projects-v10','POST',{name:name,workgroupId:$('#v10NewProjectGroup').value,responsibleUsername:$('#v10NewProjectResponsible').value,objective:$('#v10NewProjectObjective').value});
    organizationCacheV10=null;closeModal();await refresh();openProject(result.project.id);
  }catch(e){alert(e.message)}
};

function groupsSettingsHtmlV10(org){
  return '<div class="v10-group-list">'+(org.workgroups||[]).map(function(g){
    var action=g.id==='sem-grupo'?'<span class="pill s-nao">Sistema</span>':'<button class="btn light small" onclick="editWorkgroupV10(\''+g.id+'\')">Editar</button>';
    return '<div class="v10-group-row"><div><b>'+esc(g.name)+'</b><div class="muted small">'+(g.id==='sem-grupo'?'Destino de projetos ainda não classificados':(g.active===false?'Inativo':'Ativo'))+'</div></div>'+action+'</div>';
  }).join('')+'</div>';
}
async function loadGroupsSettingsV10(){
  var box=$('#v10GroupsSettings');if(!box)return;
  try{var org=await organizationV10(true);box.innerHTML=groupsSettingsHtmlV10(org)}catch(e){box.innerHTML='<div class="empty">'+esc(e.message)+'</div>'}
}
renderSettings=function(){
  baseRenderSettingsV10();
  if(!isRachidV10)return;
  $('#settingsView').insertAdjacentHTML('beforeend','<div class="card settings-card" style="margin-top:14px"><div class="card-h"><div><h3>Grupos de trabalho</h3><div class="muted small">Organizam os projetos sem alterar responsabilidade ou estrutura.</div></div><button class="btn blue small" onclick="newWorkgroupV10()">＋ Criar grupo</button></div><div class="pad" id="v10GroupsSettings"><div class="empty">Carregando grupos…</div></div></div>');
  loadGroupsSettingsV10();
};
window.newWorkgroupV10=function(){modal('<h2>Novo grupo de trabalho</h2><div class="field"><label>Nome</label><input id="v10GroupName"></div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="saveNewWorkgroupV10()">Criar grupo</button></div>')};
window.saveNewWorkgroupV10=async function(){
  var name=$('#v10GroupName').value.trim();if(!name){alert('Informe o nome do grupo.');return}
  try{await api('/api/workgroups','POST',{name:name});organizationCacheV10=null;closeModal();await refresh();showView('settings')}catch(e){alert(e.message)}
};
window.editWorkgroupV10=async function(id){
  try{
    var org=await organizationV10(true),g=(org.workgroups||[]).find(function(x){return x.id===id});if(!g)return;
    var status=g.system?'':'<div class="field"><label>Status</label><select id="v10EditGroupActive"><option value="1" '+(g.active!==false?'selected':'')+'>Ativo</option><option value="0" '+(g.active===false?'selected':'')+'>Inativo</option></select></div>';
    modal('<h2>Editar grupo</h2><div class="field"><label>Nome</label><input id="v10EditGroupName" value="'+esc(g.name)+'"></div>'+status+'<div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="saveWorkgroupV10(\''+id+'\','+(g.system?'true':'false')+')">Salvar</button></div>');
  }catch(e){alert(e.message)}
};
window.saveWorkgroupV10=async function(id,system){
  try{
    var body={name:$('#v10EditGroupName').value};
    if(!system)body.active=$('#v10EditGroupActive').value==='1';
    await api('/api/workgroups/'+encodeURIComponent(id),'POST',body);
    organizationCacheV10=null;closeModal();await refresh();showView('settings');
  }catch(e){alert(e.message)}
};

if(window.generateV9MeetingSummary){
  var baseGenerateV10=window.generateV9MeetingSummary;
  window.generateV9MeetingSummary=function(){
    var btn=document.querySelector('.kaz-meeting-top-actions .btn.blue');
    if(btn&&/reprocessar/i.test(btn.textContent||'')){
      if(!confirm('Reprocessar registro executivo?\n\nO resumo atual será preservado no histórico e uma nova versão será gerada pela IA.'))return;
    }
    return baseGenerateV10();
  };
}

function applyNavigationV10(){
  var section=$('#personalNavSection');if(section)section.textContent='Organização';
  var mine=$('#myManagementNav');if(mine){mine.innerHTML='◉ Minha Gestão';mine.classList.toggle('hidden',!isRachidV10)}
  var integrated=$('#integratedNav');if(integrated)integrated.classList.add('hidden');
  var my=$('#myProjectNav');if(my){my.innerHTML='◎ Meus projetos';my.classList.toggle('hidden',isDirection||assignedProjectsV10().length===0)}
}
applyNavigationV10();
setTimeout(applyNavigationV10,500);
setTimeout(applyNavigationV10,1600);
renderHome();
})();