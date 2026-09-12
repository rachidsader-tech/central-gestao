// Transformação KAZ V5 — ajustes de compromisso estratégico e perfil Visualizador.
const isViewer = USER.role === 'viewer';

function latestStrategicCommitment(p){
  const list=(p.weeklyCommitments||[]).slice();
  if(!list.length)return null;
  list.sort((a,b)=>String(b.createdAt||'').localeCompare(String(a.createdAt||'')));
  return list.find(c=>c.status==='Aberto') || list[0];
}

function strategicCommitmentCard(p){
  const c=latestStrategicCommitment(p);
  if(!c){
    return `<div class="card empty">Nenhum compromisso estratégico foi registrado em reunião até o momento.</div>`;
  }
  return `<div class="card"><div class="pad">
    <div class="small muted" style="text-transform:uppercase;font-weight:800">Compromisso definido na reunião semanal</div>
    <div class="smart-text" style="font-size:16px;font-weight:750;margin-top:8px">${esc(c.text)}</div>
    <div class="flex wrap" style="margin-top:10px">${badgeCommit(c.status)}<span class="small muted">Não é uma tarefa de agenda; é o resultado estratégico combinado até a reunião seguinte.</span></div>
  </div></div>`;
}

function renderHome(){
  const root=$('#homeView');
  if(isDirection){
    const all=state.projects||[];
    const totalMilestones=all.reduce((a,p)=>a+(p.milestones?.length||0),0);
    const done=all.reduce((a,p)=>a+counts(p).done,0);
    const open=(state.dependencies||[]).filter(d=>d.status!=='Resolvida').length;
    const risks=all.filter(p=>p.status==='Em risco'||counts(p).risk>0).length;
    root.innerHTML=`<div class="hero"><div><h1>Visão da Transformação</h1><p>Radar executivo dos sete projetos estruturantes.</p></div></div>
      <div class="grid-kpi"><div class="kpi"><strong>${all.length}</strong><span>Projetos</span></div><div class="kpi"><strong>${done}/${totalMilestones}</strong><span>Marcos concluídos</span></div><div class="kpi"><strong>${open}</strong><span>Pendências ativas</span></div><div class="kpi"><strong>${risks}</strong><span>Projetos com atenção</span></div></div>
      ${projectsCard(all)}
      <div class="section-title"><h2>Pendências que exigem Diretoria</h2><button class="btn light small" onclick="showView('director')">Ver todas</button></div>
      ${depsCard((state.dependencies||[]).filter(d=>d.status!=='Resolvida').slice(0,8))}`;
    return;
  }

  if(isViewer){
    const all=state.projects||[];
    const totalMilestones=all.reduce((a,p)=>a+(p.milestones?.length||0),0);
    const done=all.reduce((a,p)=>a+counts(p).done,0);
    const open=(state.dependencies||[]).filter(d=>d.status!=='Resolvida').length;
    const risks=all.filter(p=>p.status==='Em risco'||counts(p).risk>0).length;
    root.innerHTML=`<div class="hero"><div><h1>Olá, ${esc(USER.display_name.split(' ')[0])}</h1><p>Visão de acompanhamento da Transformação KAZ.</p></div><div class="pill s-nao">Somente leitura</div></div>
      <div class="info" style="margin-bottom:14px"><b>Perfil Visualizador.</b> Você pode consultar todos os projetos, marcos, pendências e registros, mas não pode alterar informações nem conduzir reuniões.</div>
      <div class="grid-kpi"><div class="kpi"><strong>${all.length}</strong><span>Projetos</span></div><div class="kpi"><strong>${done}/${totalMilestones}</strong><span>Marcos concluídos</span></div><div class="kpi"><strong>${open}</strong><span>Pendências ativas</span></div><div class="kpi"><strong>${risks}</strong><span>Projetos com atenção</span></div></div>
      ${projectsCard(all)}
      <div class="section-title"><h2>Pendências em acompanhamento</h2><button class="btn light small" onclick="showView('dependencies')">Ver todas</button></div>
      ${depsCard((state.dependencies||[]).filter(d=>d.status!=='Resolvida').slice(0,8))}`;
    return;
  }

  const p=project(USER.project_id);
  if(!p){root.innerHTML='<div class="card empty">Você não está alocado a um projeto.</div>';return}
  const c=counts(p);
  const mine=(state.dependencies||[]).filter(d=>d.projectId===p.id&&d.status!=='Resolvida');
  root.innerHTML=`<div class="hero"><div><h1>Olá, ${esc(USER.display_name.split(' ')[0])}</h1><p>Seu painel de acompanhamento da Transformação KAZ.</p></div><div class="pill s-nao">1 projeto · ${c.total} marcos</div></div>
    <div class="card owner-project clickable" onclick="openProject('${p.id}')"><div><div class="muted small">MEU PROJETO</div><h2>${esc(p.name)}</h2><div class="meta">Responsável: ${esc(p.owner)} · ${esc(p.status)}</div><p class="smart-text" style="margin:10px 0 0">${esc(smartMilestoneSummary(p))}</p></div><div class="count"><strong>${c.done}/${c.total}</strong><span class="muted small">marcos concluídos</span><div style="margin-top:9px"><span class="btn light small">Abrir meu projeto →</span></div></div></div>
    <div class="section-title"><h2>Compromisso estratégico da última reunião</h2></div>
    ${strategicCommitmentCard(p)}
    <div class="section-title"><h2>Pendências com a Diretoria</h2><button class="btn light small" onclick="showView('dependencies')">Ver todas</button></div>${depsCard(mine.slice(0,6))}
    <div class="section-title"><h2>Resumo dos marcos</h2><button class="btn light small" onclick="openProject('${p.id}','milestones')">Ver todos os ${c.total} marcos →</button></div>${milestoneSummaryCard(p)}`;
}

function renderProjects(){
  let text='Você pode consultar toda a Transformação KAZ; a edição fica restrita ao seu projeto.';
  if(isDirection)text='Visão consolidada com edição total da Diretoria.';
  if(isViewer)text='Visão completa da Transformação KAZ em modo somente leitura.';
  $('#projectsView').innerHTML=`<div class="hero"><div><h1>Todos os projetos</h1><p>${text}</p></div>${isViewer?'<div class="pill s-nao">Somente leitura</div>':''}</div>${projectsCard(state.projects||[])}`;
}

function renderProject(){
  const p=project(currentProjectId);if(!p)return;
  if(currentTab==='commitments')currentTab='overview';
  const c=counts(p),editable=canEdit(p.id),dps=(state.dependencies||[]).filter(d=>d.projectId===p.id);
  $('#projectView').innerHTML=`<button class="btn light small" onclick="showView('projects')">← Todos os projetos</button>
    <div class="detail-head" style="margin-top:15px"><div><div class="muted small" style="text-transform:uppercase">Projeto de transformação</div><h1>${esc(p.name)}</h1><div class="muted small">Responsável: <b>${esc(p.owner)}</b> · ${editable?'Edição habilitada':'Modo consulta'}</div></div><div class="flex wrap">${badge(p.status)} ${p.validated?'<span class="pill s-conc">✓ Validado pela Direção</span>':''}${isViewer?'<span class="pill s-nao">Somente leitura</span>':''}</div></div>
    <div class="tabs"><button class="tab ${currentTab==='overview'?'active':''}" onclick="projectTab('overview')">Visão geral</button><button class="tab ${currentTab==='milestones'?'active':''}" onclick="projectTab('milestones')">Marcos (${c.total})</button><button class="tab ${currentTab==='dependencies'?'active':''}" onclick="projectTab('dependencies')">Pendências (${dps.filter(d=>d.status!=='Resolvida').length})</button><button class="tab ${currentTab==='history'?'active':''}" onclick="projectTab('history')">Registros</button></div>
    <div id="projectPanel"></div>`;
  renderProjectPanel();
}

function renderDependencies(){
  const list=(isDirection||isViewer)?(state.dependencies||[]):(state.dependencies||[]).filter(d=>d.projectId===USER.project_id);
  let description=isDirection?'Todas as pendências dos projetos.':'Pendências do seu projeto e respostas da Diretoria.';
  if(isViewer)description='Todas as pendências da Transformação KAZ em modo somente leitura.';
  $('#dependenciesView').innerHTML=`<div class="hero"><div><h1>Pendências externas</h1><p>${description}</p></div>${!isViewer&&USER.project_id?'<button class="btn blue" onclick="openDependencyModal()">＋ Nova pendência</button>':''}</div>${isViewer?'<div class="info" style="margin-bottom:14px">Você pode abrir cada pendência para consultar solicitação, conversa e histórico, sem executar ações.</div>':''}${depsCard(list)}`;
}

function tutorialRows(){
  let rows;
  if(isDirection){
    rows=[
      ['Início','Radar executivo dos 7 projetos, marcos, riscos e pendências ativas.'],
      ['Todos os projetos','Abra qualquer projeto para consultar ou alterar objetivo, marcos, pendências e registros.'],
      ['Pendências da Diretoria','Caixa de entrada conjunta da Diretoria, preservando um diretor responsável por pendência.'],
      ['Modo Reunião','Conduza o ritual de quarta-feira. O compromisso estratégico nasce no fechamento da reunião e não funciona como agenda.'],
      ['Configurações','Altere sua própria senha.']
    ];
  }else if(isViewer){
    rows=[
      ['Início','Acompanhe a transformação inteira em modo somente leitura.'],
      ['Todos os projetos','Consulte objetivo, marcos, pendências e registros de qualquer projeto.'],
      ['Pendências','Acompanhe solicitações e respostas sem alterar o conteúdo.'],
      ['Configurações','Altere sua própria senha.'],
      ['Ajuda','Baixe o manual ou reinicie o tutorial quando precisar.']
    ];
  }else{
    rows=[
      ['Início','Sua home mostra o projeto pelo qual você responde e o que exige atenção agora.'],
      ['Meu projeto','Acompanhe objetivo, status, marcos, pendências e registros. Compromissos não formam uma agenda separada.'],
      ['Todos os projetos','Consulte toda a transformação, sem editar áreas de outros responsáveis.'],
      ['Pendências','Peça atuação da Diretoria quando houver uma dependência real.'],
      ['Modo Reunião','Revise Prometido × Realizado e defina o compromisso estratégico até a reunião seguinte.'],
      ['Configurações','Altere sua própria senha.']
    ];
  }
  return rows.map((r,i)=>`<div class="tutorial-row"><div class="n">${i+1}</div><div><b>${r[0]}</b><div class="smart-text">${r[1]}</div></div></div>`).join('');
}

function tutorialSteps(){
  if(isDirection)return [
    {title:'Início — Visão da Transformação',view:'home',text:'Aqui a Diretoria enxerga os sete projetos juntos. Use a tela como radar: situação, evolução dos marcos, riscos e pendências.'},
    {title:'Projetos',view:'projects',text:'Abra qualquer projeto para analisar objetivo, marcos, pendências e registros. A Diretoria pode editar todos.'},
    {title:'Pendências da Diretoria',view:'director',text:'Todas as pendências chegam aqui. Existe um único diretor responsável, mas os quatro podem analisar e responder em conjunto.'},
    {title:'Modo Reunião',view:'meeting',text:'Na quarta-feira, selecione o projeto, revise a semana anterior, ligue o microfone durante a apresentação, revise o resumo e feche com um compromisso estratégico. Isso não é uma agenda de tarefas.'},
    {title:'Configurações',view:'settings',text:'Cada usuário pode alterar a própria senha sem depender do administrador.'},
    {title:'Ajuda',view:'help',text:'O manual completo e este tutorial ficam disponíveis permanentemente nesta área.'}
  ];
  if(isViewer)return [
    {title:'Início — Acompanhamento',view:'home',text:'Você possui acesso de consulta à Transformação KAZ. Enxerga os sete projetos sem editar informações.'},
    {title:'Todos os projetos',view:'projects',text:'Abra qualquer projeto para consultar objetivo, marcos, pendências e registros.'},
    {title:'Pendências',view:'dependencies',text:'Consulte solicitações, respostas e histórico das pendências externas. Seu perfil não executa ações.'},
    {title:'Configurações',view:'settings',text:'Você pode alterar sua própria senha.'},
    {title:'Ajuda',view:'help',text:'Baixe o manual e reinicie este tutorial sempre que quiser.'}
  ];
  return [
    {title:'Início — Seu painel',view:'home',text:'Aqui aparece seu projeto, o compromisso estratégico definido na última reunião, as pendências com a Diretoria e o resumo dos marcos.'},
    {title:'Meu projeto',view:'myproject',text:'Esta é a central da transformação da sua área. A Visão Geral interpreta; a aba Marcos mostra a relação completa. Não existe agenda de compromissos separada.'},
    {title:'Todos os projetos',view:'projects',text:'Você pode acompanhar toda a empresa, mas só altera o projeto pelo qual é responsável.'},
    {title:'Pendências',view:'dependencies',text:'Abra uma pendência apenas quando depender da Diretoria. Escolha um único diretor responsável.'},
    {title:'Modo Reunião',view:'meeting',text:'Na quarta-feira, revise Prometido × Realizado, use o microfone durante sua apresentação e confirme decisões e o compromisso estratégico até a próxima reunião.'},
    {title:'Configurações',view:'settings',text:'Altere sua senha individualmente sempre que precisar.'},
    {title:'Ajuda',view:'help',text:'Baixe o manual e reinicie este tutorial sempre que quiser.'}
  ];
}

function renderSettings(){
  const p=USER.project_id?project(USER.project_id):null;
  const profile=isDirection?'Diretoria':(isViewer?'Visualizador — somente leitura':'Responsável de projeto');
  const projectLabel=isViewer?'Sem projeto associado':(p?.name||'Visão global');
  $('#settingsView').innerHTML=`<div class="hero"><div><h1>Configurações</h1><p>Dados da sua conta e alteração individual de senha.</p></div></div>
    <div class="card settings-card"><div class="card-h"><h3>Minha conta</h3></div><div class="pad">
      <div class="profile-row"><b>Nome</b><span>${esc(USER.display_name)}</span></div>
      <div class="profile-row"><b>Usuário</b><span>${esc(USER.username)}</span></div>
      <div class="profile-row"><b>Perfil</b><span>${profile}</span></div>
      <div class="profile-row"><b>Projeto</b><span>${esc(projectLabel)}</span></div>
    </div></div>
    <div class="card settings-card" style="margin-top:14px"><div class="card-h"><h3>Alterar senha</h3></div><div class="pad">
      <div class="form-grid"><div class="field full"><label>Senha atual</label><input id="pwCurrent" type="password" autocomplete="current-password"></div><div class="field"><label>Nova senha</label><input id="pwNew" type="password" autocomplete="new-password"></div><div class="field"><label>Confirmar nova senha</label><input id="pwConfirm" type="password" autocomplete="new-password"></div></div>
      <div class="small muted" style="margin-top:8px">A nova senha deve ter pelo menos 8 caracteres.</div>
      <div class="actions"><button class="btn blue" onclick="changePassword()">Salvar nova senha</button></div>
    </div></div>`;
}

function applyV5Adjustments(){
  if(isViewer){
    $('#myProjectNav')?.classList.add('hidden');
    document.querySelector('.nav-btn[data-nav="meeting"]')?.classList.add('hidden');
  }
  const role=$('#userRole');
  if(role){
    if(isViewer)role.textContent='Visualizador';
    else if(isDirection)role.textContent='Diretoria';
    else role.textContent=project(USER.project_id)?.name||'Responsável';
  }
  const visible=$$('.view').find(v=>!v.classList.contains('hidden'));
  if(!visible||visible.id==='homeView')renderHome();
}

applyV5Adjustments();
