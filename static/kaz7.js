// Transformação KAZ — Roadmap do Sucesso + gravação longa segmentada + resumo por IA.
(function(){
  const baseProjectsCardRoadmap = projectsCard;
  const baseRenderHomeRoadmap = renderHome;
  const baseRenderProjectPanelRoadmap = renderProjectPanel;
  const baseRenderMeetingStepRoadmap = renderMeetingStep;
  const baseRenderMeetingRoadmap = renderMeeting;
  const baseShowViewRoadmap = showView;
  const baseRenderHelpRoadmap = renderHelp;
  const baseShowTutorialStepRoadmap = showTutorialStep;
  const baseMeetingStepLabelRoadmap = meetingStepLabel;

  const roadmapAttachmentCache = {};
  let meetingAIStatus = null;
  let longMeetingSessionId = null;
  let longMeetingSegmentIndex = 0;
  let longMeetingSegmentCount = 0;
  let longMeetingUploadPromises = [];
  let longMeetingProcessedStream = null;
  let longMeetingSegmentTimer = null;
  let longMeetingFinalizing = false;
  let longMeetingAIProcessed = false;
  let longMeetingUploadedPositions = [];
  let meetingPage = 'home';

  showView = function(name){
    if(name==='meeting'&&!listening&&!longMeetingFinalizing)meetingPage='home';
    baseShowViewRoadmap(name);
  };

  function resetMeetingDraft(){
    longMeetingSessionId=null;longMeetingSegmentIndex=0;longMeetingSegmentCount=0;
    longMeetingUploadedPositions=[];longMeetingUploadPromises=[];longMeetingAIProcessed=false;
    meetingProcessStatus='';transcriptText='';meetingStep=1;
    for(const key of ['Summary','Topics','Decisions','NextSteps','Dependencies','Next'])window['currentMeeting'+key]='';
  }

  renderMeeting = function(){
    if(meetingPage==='editor'){
      baseRenderMeetingRoadmap();
      $('#meetingView').insertAdjacentHTML('afterbegin','<button class="btn light small" style="margin-bottom:14px" onclick="openMeetingHome()">← Reuniões</button>');
      return;
    }
    const allowed=isDirection?(state.projects||[]):[project(USER.project_id)].filter(Boolean);
    if(!allowed.length){$('#meetingView').innerHTML='<div class="card empty">Nenhum projeto disponível.</div>';return}
    if(!allowed.some(p=>p.id===meetingProjectId))meetingProjectId=allowed[0].id;
    $('#meetingView').innerHTML=`<div class="hero"><div><h1>Reuniões</h1><p>Consulte gravações anteriores ou inicie uma reunião.</p></div></div>
      <div class="card meeting-box"><div class="field"><label>Projeto</label><select onchange="meetingProjectId=this.value;renderMeeting()">${allowed.map(p=>`<option value="${esc(p.id)}" ${p.id===meetingProjectId?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div>
      ${meetingPage==='home'?'<div class="actions" style="justify-content:flex-start"><button class="btn blue" onclick="showRecordedMeetings()">Ver reuniões gravadas</button><button class="btn light" onclick="startNewMeeting()">🎙 Gravar nova reunião</button></div>':
      '<div class="actions" style="justify-content:flex-start"><button class="btn light" onclick="openMeetingHome()">← Voltar</button><button class="btn blue" onclick="startNewMeeting()">🎙 Gravar nova reunião</button></div><div id="recordedMeetingList" class="meeting-history-list">Carregando gravações…</div>'}
      </div>`;
    if(meetingPage==='recorded')loadRecordedMeetings();
  };

  window.openMeetingHome = function(){
    if(listening||longMeetingFinalizing){alert('Encerre o processamento da reunião antes de voltar.');return}
    meetingPage='home';renderMeeting();
  };
  window.startNewMeeting = function(){
    if(listening||longMeetingFinalizing)return;
    resetMeetingDraft();meetingPage='editor';renderMeeting();
  };
  window.showRecordedMeetings = function(){meetingPage='recorded';renderMeeting()};

  async function loadRecordedMeetings(){
    const root=$('#recordedMeetingList'),selected=meetingProjectId;
    try{
      const j=await api('/api/meeting/audio-sessions');
      if(meetingPage!=='recorded'||meetingProjectId!==selected||root!==$('#recordedMeetingList'))return;
      const sessions=(j.sessions||[]).filter(s=>s.projectId===selected);
      const linked=new Set(sessions.map(s=>s.id));
      const textOnly=(state.meetings||[]).filter(m=>m.projectId===selected&&!linked.has(m.audioSessionId));
      const rows=[...sessions.map(s=>{
        const saved=(state.meetings||[]).find(m=>m.audioSessionId===s.id);
        return {date:s.startedAt,html:`<div class="message"><strong>${fmtDate(s.startedAt)} · ${esc(s.createdBy)}</strong><p>${s.segments} bloco(s) de áudio · ${s.transcribed} transcrito(s) · ${saved?'Reunião registrada':'Reunião ainda não registrada'}</p>${saved?.summary?`<p><b>Resumo:</b> ${esc(saved.summary)}</p>`:''}<button class="btn blue small" onclick="openRecordedMeeting('${s.id}')">Abrir gravação e processar com IA</button></div>`};
      }),...textOnly.map(m=>({date:m.at,html:`<div class="message"><strong>${fmtDate(m.at)} · ${esc(m.createdBy)}</strong><p>${m.audioSessionId?'Gravação não encontrada':'Registro sem gravação de áudio'}</p>${m.summary?`<p><b>Resumo:</b> ${esc(m.summary)}</p>`:''}${m.transcript?`<p><b>Transcrição:</b> ${esc(m.transcript)}</p>`:''}</div>`}))];
      rows.sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
      root.innerHTML=rows.length?rows.map(r=>r.html).join(''):'<div class="empty">Nenhuma reunião gravada neste projeto.</div>';
    }catch(e){root.textContent='Falha ao carregar reuniões: '+e.message}
  }

  window.openRecordedMeeting = async function(sessionId){
    try{
      const manifest=await api(`/api/meeting/audio-sessions/${encodeURIComponent(sessionId)}/segments`);
      if(!(manifest.segments||[]).length)throw new Error('Nenhum áudio salvo nesta gravação.');
      const saved=(state.meetings||[]).find(m=>m.audioSessionId===sessionId);
      resetMeetingDraft();
      meetingProjectId=saved?.projectId||manifest.projectId||meetingProjectId;
      longMeetingSessionId=sessionId;
      longMeetingUploadedPositions=manifest.segments.map(s=>s.position);
      longMeetingSegmentCount=manifest.segments.length;
      longMeetingSegmentIndex=Math.max(...longMeetingUploadedPositions)+1;
      transcriptText=manifest.segments.map(s=>s.transcript||'').filter(Boolean).join('\n\n')||saved?.transcript||'';
      window.currentMeetingSummary=saved?.summary||'';
      window.currentMeetingTopics=saved?.topics||saved?.notes||'';
      window.currentMeetingDecisions=saved?.decisions||'';
      window.currentMeetingNextSteps=saved?.nextSteps||'';
      window.currentMeetingDependencies=saved?.dependencies||'';
      window.currentMeetingNext=saved?.nextWeek||'';
      longMeetingAIProcessed=Boolean(saved?.aiProcessed);
      meetingProcessStatus='Gravação recuperada. Ouça os blocos ou processe com IA.';
      meetingPage='editor';meetingStep=3;renderMeeting();
    }catch(e){alert('Não foi possível abrir a gravação: '+e.message)}
  };

  meetingStepLabel = function(n,label){
    if(n===3)label='Gravação da reunião';
    if(n===4)label='Revisão e próximos passos';
    return `<div class="meeting-step ${meetingStep===n?'active':''}">${n}. ${label}</div>`;
  };

  function roadmapScopeDefined(p){ return Boolean(p?.scopeDefined ?? p?.milestonesLocked); }
  function canManageRoadmapScope(p){ return USER.username==='rachid' || USER.project_id===p.id; }

  smartMilestoneSummary = function(p){
    const c=counts(p);
    if(c.total===0)return 'O Roadmap do Sucesso ainda não possui itens definidos.';
    if(c.done===c.total)return 'Todos os itens do Roadmap do Sucesso foram concluídos. O foco agora é estabilizar o novo modelo e registrar o encerramento.';
    if(c.risk>0){const r=(p.milestones||[]).find(m=>m.status==='Em risco');return `${c.risk} ${c.risk===1?'item do Roadmap exige':'itens do Roadmap exigem'} atenção. ${r?`O ponto mais sensível neste momento é “${r.name}”.`:''}`}
    if(c.and>0){const a=(p.milestones||[]).find(m=>m.status==='Em andamento');return `${c.and} ${c.and===1?'item do Roadmap está':'itens do Roadmap estão'} em andamento. ${a?`O avanço mais visível está em “${a.name}”.`:''}`}
    const next=(p.milestones||[]).find(m=>m.status==='Não iniciado');
    return `Nenhum item do Roadmap está em andamento neste momento. ${next?`O próximo avanço sugerido é iniciar “${next.name}”.`:''}`;
  };

  projectsCard = function(list){
    return baseProjectsCardRoadmap(list)
      .replace('<th>Marcos</th>','<th>Roadmap do Sucesso</th>');
  };

  function applyRoadmapTerms(root){
    if(!root)return;
    const replacements=[
      ['Marcos concluídos','Itens do Roadmap concluídos'],
      ['marcos concluídos','itens concluídos no Roadmap'],
      ['Resumo dos marcos','Roadmap do Sucesso'],
      ['Resumo dos Marcos','Roadmap do Sucesso'],
      ['Ver todos os ','Ver Roadmap · '],
      [' marcos →',' itens →'],
      [' marcos',' itens no Roadmap'],
    ];
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(node=>{
      let value=node.nodeValue;
      replacements.forEach(([a,b])=>{value=value.split(a).join(b)});
      node.nodeValue=value;
    });
  }

  renderHome = function(){
    baseRenderHomeRoadmap();
    applyRoadmapTerms($('#homeView'));
  };

  renderProject = function(){
    const p=project(currentProjectId);if(!p)return;
    if(currentTab==='commitments')currentTab='overview';
    const c=counts(p),editable=canEdit(p.id),dps=(state.dependencies||[]).filter(d=>d.projectId===p.id);
    const defined=roadmapScopeDefined(p),manage=canManageRoadmapScope(p);
    let scopeAction='';
    if(manage){
      if(defined && USER.username==='rachid') scopeAction='<button class="btn light small" onclick="reopenProjectScope()">Reabrir escopo</button>';
      if(!defined) scopeAction='<button class="btn blue small" onclick="defineProjectScope()">Definir escopo do projeto</button>';
    }
    $('#projectView').innerHTML=`<button class="btn light small" onclick="showView('projects')">← Todos os projetos</button>
      <div class="detail-head" style="margin-top:15px">
        <div><div class="muted small" style="text-transform:uppercase">Projeto de transformação</div><h1>${esc(p.name)}</h1><div class="muted small">Responsável: <b>${esc(p.owner)}</b> · ${editable?'Edição habilitada':'Modo consulta'}</div></div>
        <div class="flex wrap">${badge(p.status)} <span class="pill ${defined?'s-conc':'s-analise'}">${defined?'Escopo definido':'Escopo em definição'}</span>${scopeAction}${isViewer?'<span class="pill s-nao">Somente leitura</span>':''}</div>
      </div>
      <div class="tabs">
        <button class="tab ${currentTab==='overview'?'active':''}" onclick="projectTab('overview')">Visão geral</button>
        <button class="tab ${currentTab==='milestones'?'active':''}" onclick="projectTab('milestones')">Roadmap do Sucesso (${c.total})</button>
        <button class="tab ${currentTab==='dependencies'?'active':''}" onclick="projectTab('dependencies')">Pendências (${dps.filter(d=>d.status!=='Resolvida').length})</button>
        <button class="tab ${currentTab==='history'?'active':''}" onclick="projectTab('history')">Registros</button>
      </div><div id="projectPanel"></div>`;
    renderProjectPanel();
  };

  function roadmapMemoMeta(m){
    const ms=(m.memos||[]).slice().sort((a,b)=>String(b.at||'').localeCompare(String(a.at||'')));
    if(!ms.length)return '<span class="muted small">Nenhum registro de andamento</span>';
    return `<span class="muted small">${ms.length} ${ms.length===1?'registro':'registros'} · último em ${fmtDate(ms[0].at)}</span>`;
  }
  function roadmapHistory(m){
    const ms=(m.memos||[]).slice();
    return `<div class="roadmap-history">
      <div class="flex wrap" style="align-items:center;margin-bottom:9px"><div><b>Histórico desta etapa</b><div class="muted small">Evoluções, decisões e mudanças de contexto.</div></div><span class="right pill s-nao">${ms.length} ${ms.length===1?'registro':'registros'}</span></div>
      ${ms.length?memosCard(ms):'<div class="empty">Nenhum andamento registrado ainda.</div>'}
    </div>`;
  }
  function roadmapAttachmentsBox(m,editable){
    return `<div class="roadmap-files">
      <div class="flex wrap" style="align-items:center"><div><b>Arquivos anexados</b><div class="muted small">Documentos, planilhas, apresentações e evidências relacionadas a esta etapa.</div></div></div>
      <div id="roadmap-files-${m.id}" class="roadmap-file-list"><div class="muted small">Carregando arquivos…</div></div>
      ${editable?`<div class="flex wrap" style="margin-top:10px">
        <input type="file" id="roadmap-file-input-${m.id}" class="roadmap-file-input-hidden" onchange="uploadRoadmapAttachment('${m.id}')">
        <button type="button" class="btn light small" onclick="chooseRoadmapAttachment('${m.id}')">＋ Anexar arquivo</button>
        <span id="roadmap-file-status-${m.id}" class="muted small">Clique para escolher um arquivo.</span>
      </div>`:''}
    </div>`;
  }

  milestonesCard = function(p,editable){
    const structureOpen=!roadmapScopeDefined(p);
    return `<div class="card"><div class="pad">${(p.milestones||[]).map((m,i)=>`
      <div class="milestone">
        <div class="m-row">
          <div><div class="m-name">${i+1}. ${esc(m.name)}</div><div class="muted small" style="margin-top:3px">${m.deadline?`Prazo: ${esc(m.deadline)}`:'Sem prazo definido'}</div><div style="margin-top:4px">${roadmapMemoMeta(m)}</div></div>
          <div>${badge(m.status)}</div><div class="small">${esc(m.deadline||'—')}</div>
          <button class="btn light small" onclick="toggleMilestone('${m.id}')">${editable?'Abrir':'Ver'}</button>
        </div>
        <div id="md-${m.id}" class="m-detail hidden">
          ${editable?`<div class="form-grid">
            <div class="field full"><label>Etapa do Roadmap ${structureOpen?'— estrutura ainda editável':'— estrutura definida'}</label><input id="mn-${m.id}" value="${esc(m.name)}" ${structureOpen?'':'disabled'}></div>
            <div class="field"><label>Status</label><select id="ms-${m.id}">${['Não iniciado','Em andamento','Em risco','Concluído'].map(s=>`<option ${m.status===s?'selected':''}>${s}</option>`).join('')}</select></div>
            <div class="field"><label>Prazo</label><input id="dl-${m.id}" type="date" value="${esc(m.deadline||'')}" ${structureOpen?'':'disabled'}></div>
            <div class="field full"><label>Conclusão / resultado</label><textarea id="co-${m.id}">${esc(m.conclusion||'')}</textarea></div>
            <div class="field full"><label>Registrar andamento</label><textarea id="mm-${m.id}" placeholder="Registre evolução, decisão, mudança de contexto ou informação relevante..."></textarea><div class="muted small" style="margin-top:5px">O registro ficará no histórico desta etapa e na aba Registros do projeto.</div></div>
          </div><div class="actions"><button class="btn" onclick="saveMilestone('${m.id}')">Salvar andamento</button></div>`:`${m.conclusion?`<p><b>Conclusão / resultado:</b> ${esc(m.conclusion)}</p>`:''}`}
          ${roadmapAttachmentsBox(m,editable)}${roadmapHistory(m)}
        </div>
      </div>`).join('')}</div></div>`;
  };

  renderProjectPanel = function(){
    const p=project(currentProjectId),editable=canEdit(p.id),root=$('#projectPanel'),defined=roadmapScopeDefined(p);
    if(currentTab!=='milestones'){
      baseRenderProjectPanelRoadmap();
      if(currentTab==='overview'){
        applyRoadmapTerms(root);
        const info=[...root.querySelectorAll('.info')].find(x=>x.textContent.includes('O que são marcos?'));
        if(info)info.innerHTML='<b>O que é o Roadmap do Sucesso?</b> É a sequência dos grandes resultados que demonstram que a transformação da área está avançando. Não é uma lista de tarefas do dia a dia.';
      }
      if(currentTab==='history'){
        applyRoadmapTerms(root);
        const recorded=(state.meetings||[]).filter(m=>m.projectId===p.id&&m.audioSessionId).slice().reverse();
        if(recorded.length){
          const card=root.querySelector('.card .pad');
          if(card){
            const section=document.createElement('div');
            section.innerHTML=`<h4 style="margin-top:22px">Gravações das reuniões</h4>${recorded.map(m=>`<div class="message"><strong>${fmtDate(m.at)} · ${esc(m.createdBy)}</strong><p>${m.aiProcessed?'Resumo processado por IA e revisado antes do registro.':'Gravação preservada no sistema.'}</p><button class="btn light small" onclick="openMeetingAudioSession('${m.audioSessionId}')">▶ Ouvir gravação (${m.audioSegments||0} partes)</button></div>`).join('')}`;
            card.appendChild(section);
          }
        }
      }
      return;
    }

    const manage=canManageRoadmapScope(p);
    root.innerHTML=`<div class="section-title"><h2>Roadmap do Sucesso</h2><div class="flex wrap"><span class="pill ${defined?'s-conc':'s-analise'}">${defined?'Escopo definido':'Escopo em definição'}</span>${editable&&manage?'<button class="btn blue small" onclick="openNewRoadmapItem()">＋ Novo item</button>':''}</div></div>
      ${defined?`<div class="good"><b>Escopo definido.</b> A estrutura dos itens existentes está congelada. Status, conclusão, registros de andamento e arquivos continuam atualizáveis. O usuário alocado ainda pode acrescentar um novo item ao Roadmap quando surgir um resultado estratégico novo.</div>`:`<div class="notice"><b>Última revisão do escopo.</b> Enquanto o projeto estiver em definição, o usuário alocado pode ajustar nomes e prazos do Roadmap. Ao definir o escopo, esses campos ficam congelados. Novos itens ainda poderão ser incluídos depois.</div>`}
      <div style="margin-top:12px">${milestonesCard(p,editable)}</div>
      ${!defined&&manage?`<div class="actions"><button class="btn blue" onclick="defineProjectScope()">Definir escopo e congelar estrutura atual</button></div>`:''}`;
  };

  toggleMilestone = function(id){
    const el=document.getElementById('md-'+id);if(!el)return;
    el.classList.toggle('hidden');
    if(!el.classList.contains('hidden'))loadRoadmapAttachments(id);
  };

  saveMilestone = async function(id){
    try{
      const p=project(currentProjectId),structureOpen=!roadmapScopeDefined(p);
      await api(`/api/projects/${p.id}`,'POST',{
        action:'milestone',milestoneId:id,
        name:structureOpen?$('#mn-'+id)?.value:undefined,
        status:$('#ms-'+id)?.value,
        deadline:structureOpen?$('#dl-'+id)?.value:undefined,
        conclusion:$('#co-'+id)?.value||'',memo:$('#mm-'+id)?.value||''
      });
      await refresh();currentTab='milestones';renderProject();
    }catch(e){alert(e.message)}
  };

  window.defineProjectScope = async function(){
    const p=project(currentProjectId);if(!p||roadmapScopeDefined(p))return;
    if(!confirm('Definir o escopo deste projeto agora? Este é o último momento para editar nomes e prazos dos itens já existentes no Roadmap do Sucesso. Depois, somente Rachid poderá reabrir o escopo.'))return;
    try{await api(`/api/projects/${p.id}`,'POST',{action:'scope_define'});await refresh();currentTab='milestones';renderProject();alert('Escopo definido. A estrutura atual do Roadmap do Sucesso foi congelada.')}catch(e){alert(e.message)}
  };
  window.reopenProjectScope = async function(){
    const p=project(currentProjectId);if(!p||USER.username!=='rachid')return;
    if(!confirm('Reabrir o escopo deste projeto? Nomes e prazos do Roadmap do Sucesso voltarão a ser editáveis até uma nova definição.'))return;
    try{await api(`/api/projects/${p.id}`,'POST',{action:'scope_reopen'});await refresh();currentTab='milestones';renderProject()}catch(e){alert(e.message)}
  };
  finalizeMilestones = defineProjectScope;
  unlockMilestones = reopenProjectScope;

  window.openNewRoadmapItem = function(){
    modal(`<h2>Novo item do Roadmap do Sucesso</h2><div class="form-grid"><div class="field full"><label>Resultado / etapa</label><input id="newRoadmapName" placeholder="Ex.: Modelo validado com dados reais"></div><div class="field"><label>Status inicial</label><select id="newRoadmapStatus"><option>Não iniciado</option><option>Em andamento</option><option>Em risco</option><option>Concluído</option></select></div><div class="field"><label>Prazo</label><input id="newRoadmapDeadline" type="date"></div></div><div class="info" style="margin-top:12px">Se o escopo já estiver definido, nome e prazo deste novo item serão definidos no momento da inclusão e ficarão congelados em seguida.</div><div class="actions"><button class="btn light" onclick="closeModal()">Cancelar</button><button class="btn blue" onclick="saveNewRoadmapItem()">Adicionar ao Roadmap</button></div>`);
  };
  window.saveNewRoadmapItem = async function(){
    const name=$('#newRoadmapName')?.value.trim();if(!name){alert('Informe o nome do novo item.');return}
    try{await api(`/api/projects/${currentProjectId}`,'POST',{action:'milestone_add',name,status:$('#newRoadmapStatus').value,deadline:$('#newRoadmapDeadline').value});closeModal();await refresh();currentTab='milestones';renderProject()}catch(e){alert(e.message)}
  };

  function humanFileSize(n){if(!n)return '0 B';const u=['B','KB','MB','GB'];let i=0,v=n;while(v>=1024&&i<u.length-1){v/=1024;i++}return `${v.toFixed(i?1:0)} ${u[i]}`}
  window.loadRoadmapAttachments = async function(id){
    const box=document.getElementById('roadmap-files-'+id);if(!box)return;
    try{
      const r=await fetch(`/api/projects/${encodeURIComponent(currentProjectId)}/milestones/${encodeURIComponent(id)}/attachments`,{headers:{'X-CSRF-Token':CSRF}});
      const j=await r.json();if(!r.ok)throw new Error(j.error||'Falha ao carregar arquivos.');
      roadmapAttachmentCache[id]=j.attachments||[];
      box.innerHTML=roadmapAttachmentCache[id].length?roadmapAttachmentCache[id].map(a=>`<div class="roadmap-file-row"><div><a href="${a.url}" class="roadmap-file-link">${esc(a.name)}</a><div class="muted small">${humanFileSize(a.size)} · ${esc(a.uploadedBy||'')} · ${fmtDate(a.createdAt)}</div>${a.note?`<div class="small roadmap-record-text">${esc(a.note)}</div>`:''}</div><a class="btn light small" href="${a.url}">Baixar</a></div>`).join(''):'<div class="muted small">Nenhum arquivo anexado.</div>';
    }catch(e){box.innerHTML=`<div class="small" style="color:#a9343e">${esc(e.message)}</div>`}
  };
  window.chooseRoadmapAttachment = function(id){
    const input=document.getElementById('roadmap-file-input-'+id);
    if(!input){alert('Não foi possível abrir o seletor de arquivos. Atualize a página e tente novamente.');return}
    input.click();
  };
  window.uploadRoadmapAttachment = async function(id){
    const input=document.getElementById('roadmap-file-input-'+id),file=input?.files?.[0];
    if(!file)return;
    const status=document.getElementById('roadmap-file-status-'+id);
    if(file.size>20*1024*1024){
      input.value='';
      alert('O arquivo excede o limite de 20 MB.');
      return;
    }
    if(status)status.textContent='Enviando '+file.name+'…';
    const fd=new FormData();fd.append('file',file);
    try{
      const r=await fetch(`/api/projects/${encodeURIComponent(currentProjectId)}/milestones/${encodeURIComponent(id)}/attachments`,{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
      const j=await r.json();if(!r.ok)throw new Error(j.error||'Falha ao anexar arquivo.');
      input.value='';
      if(status)status.textContent='Arquivo anexado com sucesso.';
      await loadRoadmapAttachments(id);
    }catch(e){
      input.value='';
      if(status)status.textContent='Falha ao anexar arquivo.';
      alert(e.message);
    }
  };

  async function ensureMeetingAIStatus(){
    if(meetingAIStatus!==null)return meetingAIStatus;
    try{const r=await fetch('/api/meeting/ai-status');meetingAIStatus=await r.json()}catch{meetingAIStatus={configured:false}}
    return meetingAIStatus;
  }
  function meetingAIStatusBadge(){
    if(meetingAIStatus===null)return '<span class="pill s-nao">Verificando IA…</span>';
    return meetingAIStatus.configured?'<span class="pill s-conc">IA conectada</span>':'<span class="pill s-risco">IA não conectada</span>';
  }

  function fallbackSentences(text){
    return String(text||'').replace(/\s+/g,' ').trim().split(/(?<=[.!?])\s+/).filter(Boolean);
  }
  function pickFallback(text,words,limit=5){
    return fallbackSentences(text).filter(s=>words.some(w=>s.toLowerCase().includes(w))).slice(0,limit);
  }
  function asReviewLines(items){
    return items.map(x=>'• '+x.trim()).join('\n');
  }
  function buildFallbackReview(text){
    const clean=String(text||'').trim();if(!clean)return;
    if(!window.currentMeetingSummary)window.currentMeetingSummary=summarizeText(clean);
    if(!window.currentMeetingTopics){
      const all=fallbackSentences(clean).slice(0,7);
      window.currentMeetingTopics=asReviewLines(all);
    }
    if(!window.currentMeetingDecisions){
      window.currentMeetingDecisions=asReviewLines(pickFallback(clean,['decid','defin','aprov','combin','ficou estabelecido','vamos fazer']));
    }
    if(!window.currentMeetingNextSteps){
      window.currentMeetingNextSteps=asReviewLines(pickFallback(clean,['próxim','vai ','ficou de','precisa','entregar','até quarta','até a próxima','responsável']));
    }
    if(!window.currentMeetingDependencies){
      window.currentMeetingDependencies=asReviewLines(pickFallback(clean,['diretoria','depende','aprova','aprovação','rachid','leo','márcio','marcinho','aguard']));
    }
    if(!window.currentMeetingNext){
      const next=pickFallback(clean,['até quarta','até a próxima','ficou de','vai entregar','compromisso'],1);
      if(next.length)window.currentMeetingNext=next[0];
    }
  }
  function reviewSourceBanner(){
    if(longMeetingAIProcessed)return '<div class="good"><b>Resumo gerado por IA.</b> Revise o conteúdo antes de registrar a reunião.</div>';
    if(transcriptText)return '<div class="notice"><b>Revisão provisória.</b> A gravação foi preservada, mas a IA do servidor não concluiu o processamento. Os campos abaixo foram montados apenas a partir da transcrição auxiliar e devem ser revisados com atenção.</div>';
    return '<div class="notice"><b>Gravação preservada, sem transcrição automática.</b> A IA não está conectada ao servidor neste momento. O áudio não foi perdido, mas o resumo não pode ser gerado a partir da gravação até a credencial da IA ser configurada.</div>';
  }
  function showRecordingBeacon(){
    let el=document.getElementById('meetingRecordingBeacon');
    if(!el){el=document.createElement('div');el.id='meetingRecordingBeacon';el.className='meeting-recording-beacon';el.onclick=()=>showView('meeting');document.body.appendChild(el)}
    el.innerHTML=`<span class="rec-dot"></span><b>REUNIÃO SENDO GRAVADA</b><span id="meetingBeaconTimer">${meetingElapsed()}</span>`;
  }
  function hideRecordingBeacon(){document.getElementById('meetingRecordingBeacon')?.remove()}
  const baseUpdateMeetingTimer=updateMeetingTimer;
  updateMeetingTimer=function(){
    baseUpdateMeetingTimer();
    const el=document.getElementById('meetingBeaconTimer');if(el)el.textContent=meetingElapsed();
  };

  function longMeetingRecorderHtml(){
    const uploaded=longMeetingUploadedPositions.length;
    const recorded=Math.max(longMeetingSegmentCount,uploaded);
    return `<div class="card meeting-recorder-card">
      <div class="pad"><div class="flex wrap"><div><div class="meeting-recorder-title">Gravação integral da reunião</div><div class="muted small">A gravação é dividida automaticamente em blocos curtos. Isso elimina o antigo limite prático de reuniões longas.</div></div><div class="right">${listening?'<span class="pill s-risco">● GRAVANDO</span>':longMeetingFinalizing?'<span class="pill s-analise">Processando…</span>':longMeetingSessionId?'<span class="pill s-conc">Gravação preservada</span>':'<span class="pill s-nao">Aguardando</span>'} ${meetingAIStatusBadge()}</div></div>
      <div class="micbar" style="margin-top:14px">${listening?'<button class="btn recording" onclick="stopLongMeetingRecording()">■ Encerrar gravação</button>':longMeetingSessionId?'':'<button class="btn blue" onclick="startLongMeetingRecording()">🎙 Iniciar gravação</button>'}<strong id="meetingTimer">${listening?meetingElapsed():'00:00'}</strong><span class="muted small">${listening?'Captação contínua · salvamento em blocos':longMeetingSessionId?'Gravação anterior preservada':'O áudio completo será preservado por blocos'}</span></div>
      <div class="meeting-level"><div id="meetingLevelBar" style="width:${listening?'6':'0'}%"></div></div>
      <div class="flex wrap small" style="margin-top:10px"><span><b>${recorded}</b> bloco(s) gravado(s)</span><span>·</span><span><b>${uploaded}</b> bloco(s) salvo(s) no servidor</span></div>
      ${meetingProcessStatus?`<div class="info" style="margin-top:11px">${esc(meetingProcessStatus)}</div>`:''}
      ${longMeetingSessionId&&!listening?`<div class="actions" style="justify-content:flex-start"><button class="btn light small" onclick="processLongMeetingRecording()" ${longMeetingFinalizing?'disabled':''}>↻ Processar / reprocessar com IA</button><button class="btn light small" onclick="openMeetingAudioSession('${longMeetingSessionId}')">▶ Ouvir blocos gravados</button></div>`:''}
      </div></div>`;
  }

  renderMeetingStep = function(){
    if(meetingStep!==3 && meetingStep!==4){baseRenderMeetingStepRoadmap();applyRoadmapTerms($('#meetingPanel'));return}
    if(meetingAIStatus===null)ensureMeetingAIStatus().then(()=>{if(meetingStep===3||meetingStep===4)renderMeetingStep()});
    const root=$('#meetingPanel');

    if(meetingStep===3){
      root.innerHTML=`<div class="card meeting-box"><h3>3. Gravação da reunião</h3>
        <p>Grave a conversa completa. Ao encerrar, o sistema preserva todos os blocos e tenta gerar automaticamente a transcrição e a revisão da reunião.</p>
        ${meetingAIStatus&&meetingAIStatus.configured?'':'<div class="notice" style="margin-bottom:12px"><b>IA ainda não conectada ao servidor.</b> A gravação funciona normalmente, mas sem a credencial de IA o áudio não pode ser transcrito e resumido pelo servidor. O sistema preservará o áudio e usará somente a transcrição auxiliar do navegador quando houver.</div>'}
        ${longMeetingRecorderHtml()}
        <div class="field"><label>Transcrição auxiliar / consolidada</label><textarea id="meetTranscript" class="transcript" oninput="transcriptText=this.value" placeholder="Quando disponível, a transcrição aparecerá aqui.">${esc(transcriptText)}</textarea></div>
        <div class="actions"><button class="btn light" onclick="goMeetingStep(2)">← Voltar</button>${longMeetingSessionId&&!listening&&!longMeetingFinalizing?'<button class="btn blue" onclick="captureMeetingStep3();goMeetingStep(4)">Revisar reunião →</button>':''}</div>
      </div>`;
      if(listening){showRecordingBeacon();updateMeetingTimer();runMeetingMeter()}
      return;
    }

    buildFallbackReview(transcriptText);
    root.innerHTML=`<div class="card meeting-box"><h3>4. Revisão da reunião e próximos passos</h3>
      <p>Esta é a etapa de conferência antes do registro definitivo. Revise o que foi tratado, decisões e próximos passos.</p>
      ${reviewSourceBanner()}
      ${meetingProcessStatus?`<div class="info" style="margin-top:10px">${esc(meetingProcessStatus)}</div>`:''}
      <div class="meeting-ai-grid" style="margin-top:14px">
        <div class="field full"><label>Resumo da reunião</label><textarea id="meetSummary">${esc(window.currentMeetingSummary||'')}</textarea></div>
        <div class="field"><label>O que foi tratado</label><textarea id="meetTopics">${esc(window.currentMeetingTopics||'')}</textarea></div>
        <div class="field"><label>Decisões tomadas</label><textarea id="meetDecisions">${esc(window.currentMeetingDecisions||'')}</textarea></div>
        <div class="field"><label>Próximos passos</label><textarea id="meetNextSteps">${esc(window.currentMeetingNextSteps||'')}</textarea></div>
        <div class="field"><label>Pendências / dependências da Diretoria</label><textarea id="meetDependencies">${esc(window.currentMeetingDependencies||'')}</textarea></div>
        <div class="field full"><label>Compromisso estratégico até a próxima reunião</label><textarea id="meetNext" placeholder="Qual resultado real precisa estar diferente até a próxima quarta-feira?">${esc(window.currentMeetingNext||'')}</textarea></div>
      </div>
      <div class="actions">
        <button class="btn light" onclick="goMeetingStep(3)">← Voltar à gravação</button>
        ${longMeetingSessionId?'<button class="btn light" onclick="captureMeetingReview();processLongMeetingRecording()" '+(longMeetingFinalizing?'disabled':'')+'>↻ Processar novamente com IA</button>':''}
        <button class="btn blue" onclick="saveMeeting()" ${longMeetingFinalizing?'disabled':''}>Fechar e registrar reunião</button>
      </div>
    </div>`;
  };

  async function createLongMeetingSession(){
    const j=await api('/api/meeting/audio-sessions','POST',{projectId:meetingProjectId});return j.id;
  }
  function startDraftRecognition(){
    const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR)return;
    meetingDraftRecognition=new SR();meetingDraftRecognition.lang='pt-BR';meetingDraftRecognition.continuous=true;meetingDraftRecognition.interimResults=false;
    meetingDraftRecognition.onresult=e=>{for(let i=e.resultIndex;i<e.results.length;i++){if(e.results[i].isFinal)transcriptText=(transcriptText+' '+e.results[i][0].transcript).trim()}};
    meetingDraftRecognition.onerror=()=>{};
    meetingDraftRecognition.onend=()=>{if(listening){try{meetingDraftRecognition.start()}catch{}}};
    try{meetingDraftRecognition.start()}catch{}
  }
  async function uploadLongMeetingSegment(blob,position){
    const fd=new FormData();fd.append('position',String(position));fd.append('file',blob,`reuniao_${meetingProjectId}_parte_${String(position).padStart(3,'0')}.webm`);
    const r=await fetch(`/api/meeting/audio-sessions/${longMeetingSessionId}/segments`,{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
    let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.error||`Falha ao salvar bloco ${position+1}.`);
    if(!longMeetingUploadedPositions.includes(position))longMeetingUploadedPositions.push(position);
    if(meetingStep===3)renderMeetingStep();
    return position;
  }
  function startSegmentRecorder(){
    if(!listening||!longMeetingProcessedStream)return;
    const position=longMeetingSegmentIndex++;
    longMeetingSegmentCount=Math.max(longMeetingSegmentCount,position+1);
    const mime=MediaRecorder.isTypeSupported('audio/webm;codecs=opus')?'audio/webm;codecs=opus':'audio/webm';
    const pieces=[];
    mediaRecorder=new MediaRecorder(longMeetingProcessedStream,{mimeType:mime,audioBitsPerSecond:64000});
    mediaRecorder.ondataavailable=e=>{if(e.data&&e.data.size)pieces.push(e.data)};
    mediaRecorder.onstop=()=>{
      if(longMeetingSegmentTimer)clearTimeout(longMeetingSegmentTimer);longMeetingSegmentTimer=null;
      const blob=new Blob(pieces,{type:mediaRecorder.mimeType||'audio/webm'});
      if(listening)startSegmentRecorder();
      if(blob.size){
        const promise=uploadLongMeetingSegment(blob,position).catch(err=>{meetingProcessStatus=`Falha ao salvar um bloco de áudio: ${err.message}. Tente encerrar e processar novamente.`;throw err});
        longMeetingUploadPromises.push(promise);
      }
      if(!listening)finalizeLongMeetingCapture();
    };
    mediaRecorder.start(1000);
    longMeetingSegmentTimer=setTimeout(()=>{if(listening&&mediaRecorder?.state==='recording')mediaRecorder.stop()},5*60*1000);
  }

  window.startLongMeetingRecording = async function(){
    if(listening)return;
    try{
      await ensureMeetingAIStatus();
      mediaStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:{ideal:1},sampleRate:{ideal:48000}}});
      longMeetingSessionId=await createLongMeetingSession();
      longMeetingSegmentIndex=0;longMeetingSegmentCount=0;longMeetingUploadPromises=[];longMeetingUploadedPositions=[];longMeetingAIProcessed=false;
      transcriptText='';window.currentMeetingSummary='';window.currentMeetingTopics='';window.currentMeetingNextSteps='';window.currentMeetingDecisions='';window.currentMeetingDependencies='';window.currentMeetingNext='';meetingProcessStatus='';

      meetingAudioContext=new (window.AudioContext||window.webkitAudioContext)();
      const source=meetingAudioContext.createMediaStreamSource(mediaStream);
      const highpass=meetingAudioContext.createBiquadFilter();highpass.type='highpass';highpass.frequency.value=80;
      const gain=meetingAudioContext.createGain();gain.gain.value=1.45;
      const compressor=meetingAudioContext.createDynamicsCompressor();compressor.threshold.value=-42;compressor.knee.value=24;compressor.ratio.value=4;compressor.attack.value=.01;compressor.release.value=.25;
      meetingAnalyser=meetingAudioContext.createAnalyser();meetingAnalyser.fftSize=256;
      const dest=meetingAudioContext.createMediaStreamDestination();
      source.connect(highpass);highpass.connect(gain);gain.connect(compressor);compressor.connect(meetingAnalyser);meetingAnalyser.connect(dest);
      longMeetingProcessedStream=dest.stream;

      listening=true;meetingRecordingStart=Date.now();meetingTimerHandle=setInterval(updateMeetingTimer,1000);
      startDraftRecognition();startSegmentRecorder();showRecordingBeacon();renderMeetingStep();
    }catch(e){
      listening=false;mediaStream?.getTracks().forEach(t=>t.stop());hideRecordingBeacon();alert('Não foi possível iniciar a gravação: '+e.message);
    }
  };

  window.stopLongMeetingRecording = function(){
    if(!listening)return;
    listening=false;longMeetingFinalizing=true;meetingProcessStatus='Encerrando gravação e garantindo o salvamento de todos os blocos…';
    if(meetingTimerHandle)clearInterval(meetingTimerHandle);meetingTimerHandle=null;if(longMeetingSegmentTimer)clearTimeout(longMeetingSegmentTimer);longMeetingSegmentTimer=null;
    stopMeetingMeter();hideRecordingBeacon();try{meetingDraftRecognition?.stop()}catch{}
    if(mediaRecorder?.state==='recording')mediaRecorder.stop();else finalizeLongMeetingCapture();
    renderMeetingStep();
  };

  async function finalizeLongMeetingCapture(){
    if(!longMeetingFinalizing)return;
    try{
      await Promise.allSettled(longMeetingUploadPromises);
      await api(`/api/meeting/audio-sessions/${longMeetingSessionId}/finish`,'POST',{});
      mediaStream?.getTracks().forEach(t=>t.stop());try{await meetingAudioContext?.close()}catch{}
      meetingAudioContext=null;meetingAnalyser=null;longMeetingProcessedStream=null;
      meetingProcessStatus=`Gravação concluída e preservada em ${longMeetingUploadedPositions.length} bloco(s). Iniciando transcrição e resumo…`;
      renderMeetingStep();
      await processLongMeetingRecording();
    }catch(e){meetingProcessStatus='A gravação foi encerrada, mas houve falha ao confirmar todos os blocos. '+e.message;longMeetingFinalizing=false;renderMeetingStep()}
  }

  window.processLongMeetingRecording = async function(){
    if(!longMeetingSessionId)return;
    longMeetingFinalizing=true;longMeetingAIProcessed=false;renderMeetingStep();
    try{
      const aiStatus=await ensureMeetingAIStatus();
      if(!aiStatus.configured){
        buildFallbackReview(transcriptText);
        meetingProcessStatus='A gravação foi salva corretamente, mas a IA do servidor não está conectada. A revisão abaixo usa apenas a transcrição auxiliar disponível.';
        return;
      }

      const manifestResp=await fetch(`/api/meeting/audio-sessions/${longMeetingSessionId}/segments`);
      const manifest=await manifestResp.json();
      if(!manifestResp.ok)throw new Error(manifest.error||'Falha ao listar os blocos.');
      const segments=manifest.segments||[];
      if(!segments.length)throw new Error('Nenhum bloco de áudio foi salvo.');

      const texts=[];
      for(let i=0;i<segments.length;i++){
        const s=segments[i];
        meetingProcessStatus=`Transcrevendo bloco ${i+1} de ${segments.length}…`;renderMeetingStep();
        if(s.transcript){texts.push(s.transcript);continue}
        const r=await api(`/api/meeting/audio-sessions/${longMeetingSessionId}/segments/${s.position}/transcribe`,'POST',{});
        if(r.transcript)texts.push(r.transcript);
      }
      transcriptText=texts.join('\n\n').trim()||transcriptText;
      meetingProcessStatus='Transcrição concluída. A IA está estruturando a revisão da reunião…';renderMeetingStep();

      const ai=await api('/api/meeting/summarize','POST',{projectId:meetingProjectId,transcript:transcriptText});
      window.currentMeetingSummary=ai.summary||'';
      window.currentMeetingTopics=ai.topics||'';
      window.currentMeetingDecisions=ai.decisions||'';
      window.currentMeetingNextSteps=ai.nextSteps||'';
      window.currentMeetingDependencies=ai.dependencies||'';
      if(ai.commitment)window.currentMeetingNext=ai.commitment;
      longMeetingAIProcessed=true;
      meetingProcessStatus='Resumo de IA concluído. Confira e ajuste antes de registrar.';
    }catch(e){
      buildFallbackReview(transcriptText);
      meetingProcessStatus=`A gravação está preservada, mas o processamento automático não foi concluído: ${e.message}`;
    }finally{
      longMeetingFinalizing=false;
      meetingStep=4;
      renderMeetingStep();
    }
  };

  captureMeetingStep3 = function(){
    transcriptText=$('#meetTranscript')?.value||transcriptText;
  };
  window.captureMeetingReview = function(){
    window.currentMeetingSummary=$('#meetSummary')?.value||window.currentMeetingSummary||'';
    window.currentMeetingTopics=$('#meetTopics')?.value||window.currentMeetingTopics||'';
    window.currentMeetingDecisions=$('#meetDecisions')?.value||window.currentMeetingDecisions||'';
    window.currentMeetingNextSteps=$('#meetNextSteps')?.value||window.currentMeetingNextSteps||'';
    window.currentMeetingDependencies=$('#meetDependencies')?.value||window.currentMeetingDependencies||'';
    window.currentMeetingNext=$('#meetNext')?.value||window.currentMeetingNext||'';
  };

  saveMeeting = async function(){
    if(listening){alert('Encerre a gravação antes de salvar a reunião.');return}
    if(longMeetingFinalizing){alert('Aguarde o salvamento/processamento da gravação terminar.');return}
    captureMeetingReview();
    try{
      await api('/api/meetings','POST',{
        projectId:meetingProjectId,
        notes:window.currentMeetingTopics||'',topics:window.currentMeetingTopics||'',
        decisions:window.currentMeetingDecisions||'',nextSteps:window.currentMeetingNextSteps||'',
        nextWeek:window.currentMeetingNext||'',transcript:transcriptText,summary:window.currentMeetingSummary||'',
        dependencies:window.currentMeetingDependencies||'',audioSessionId:longMeetingSessionId||'',
        audioSegments:longMeetingUploadedPositions.length,aiProcessed:longMeetingAIProcessed
      });
      alert('Reunião registrada com sucesso.');
      transcriptText='';window.currentMeetingSummary='';window.currentMeetingTopics='';window.currentMeetingNextSteps='';window.currentMeetingDecisions='';window.currentMeetingDependencies='';window.currentMeetingNext='';
      longMeetingSessionId=null;longMeetingSegmentCount=0;longMeetingUploadedPositions=[];longMeetingUploadPromises=[];longMeetingAIProcessed=false;meetingProcessStatus='';meetingStep=1;meetingPage='home';
      await refresh();renderMeeting();
    }catch(e){alert(e.message)}
  };

  window.openMeetingAudioSession = async function(sessionId){
    try{
      const r=await fetch(`/api/meeting/audio-sessions/${sessionId}/manifest`);const j=await r.json();if(!r.ok)throw new Error(j.error||'Falha ao abrir gravação.');
      modal(`<h2>Gravação da reunião</h2><p class="muted small">A reunião foi salva em ${j.segments.length} bloco(s) contínuos para evitar limite de tamanho.</p>${j.segments.map((s,i)=>`<div class="roadmap-audio-part"><b>Parte ${i+1}</b><audio controls preload="metadata" src="${s.url}"></audio></div>`).join('')}<div class="actions"><button class="btn light" onclick="closeModal()">Fechar</button></div>`);
    }catch(e){alert(e.message)}
  };

  const originalChangeMeetingProject = changeMeetingProject;
  changeMeetingProject = function(id){
    if(listening){alert('Encerre a gravação antes de trocar de projeto.');const select=$('#meetProject');if(select)select.value=meetingProjectId;return}
    longMeetingSessionId=null;longMeetingSegmentCount=0;longMeetingUploadedPositions=[];longMeetingUploadPromises=[];longMeetingAIProcessed=false;meetingProcessStatus='';
    window.currentMeetingTopics='';window.currentMeetingNextSteps='';
    originalChangeMeetingProject(id);
  };

  window.addEventListener('beforeunload',e=>{if(listening){e.preventDefault();e.returnValue='A reunião ainda está sendo gravada.'}});


  renderHelp = function(){baseRenderHelpRoadmap();applyRoadmapTerms($('#helpView'));};
  showTutorialStep = function(){baseShowTutorialStepRoadmap();applyRoadmapTerms($('#modalRoot'));};

  applyRoadmapTerms($('#homeView'));
})();
