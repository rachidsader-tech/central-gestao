// Transformação KAZ — Roadmap do Sucesso + gravação longa segmentada + resumo por IA.
(function(){
  const baseProjectsCardRoadmap = projectsCard;
  const baseRenderHomeRoadmap = renderHome;
  const baseRenderProjectPanelRoadmap = renderProjectPanel;
  const baseRenderMeetingStepRoadmap = renderMeetingStep;

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
      ${editable?`<div class="flex wrap" style="margin-top:10px"><input type="file" id="roadmap-file-input-${m.id}" class="roadmap-file-input"><button class="btn light small" onclick="uploadRoadmapAttachment('${m.id}')">＋ Anexar arquivo</button></div>`:''}
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
  window.uploadRoadmapAttachment = async function(id){
    const input=document.getElementById('roadmap-file-input-'+id),file=input?.files?.[0];if(!file){alert('Selecione um arquivo.');return}
    const fd=new FormData();fd.append('file',file);
    try{
      const r=await fetch(`/api/projects/${encodeURIComponent(currentProjectId)}/milestones/${encodeURIComponent(id)}/attachments`,{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
      const j=await r.json();if(!r.ok)throw new Error(j.error||'Falha ao anexar arquivo.');
      input.value='';await loadRoadmapAttachments(id);
    }catch(e){alert(e.message)}
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
      <div class="micbar" style="margin-top:14px"><button class="btn ${listening?'recording':'blue'}" onclick="${listening?'stopLongMeetingRecording()':'startLongMeetingRecording()'}">${listening?'■ Encerrar gravação':'🎙 Iniciar gravação'}</button><strong id="meetingTimer">${listening?meetingElapsed():'00:00'}</strong><span class="muted small">${listening?'Captação contínua · salvamento em blocos':'O áudio completo será preservado por blocos'}</span></div>
      <div class="meeting-level"><div id="meetingLevelBar" style="width:${listening?'6':'0'}%"></div></div>
      <div class="flex wrap small" style="margin-top:10px"><span><b>${recorded}</b> bloco(s) gravado(s)</span><span>·</span><span><b>${uploaded}</b> bloco(s) salvo(s) no servidor</span></div>
      ${meetingProcessStatus?`<div class="info" style="margin-top:11px">${esc(meetingProcessStatus)}</div>`:''}
      ${longMeetingSessionId&&!listening?`<div class="actions" style="justify-content:flex-start"><button class="btn light small" onclick="processLongMeetingRecording()" ${longMeetingFinalizing?'disabled':''}>↻ Processar / reprocessar com IA</button><button class="btn light small" onclick="openMeetingAudioSession('${longMeetingSessionId}')">▶ Ouvir blocos gravados</button></div>`:''}
      </div></div>`;
  }

  renderMeetingStep = function(){
    if(meetingStep!==3)return baseRenderMeetingStepRoadmap();
    if(meetingAIStatus===null)ensureMeetingAIStatus().then(()=>{if(meetingStep===3)renderMeetingStep()});
    const root=$('#meetingPanel');
    root.innerHTML=`<div class="card meeting-box"><h3>3. Gravação, conteúdo e decisões da reunião</h3><p>Grave a conversa completa. Ao encerrar, o sistema consolida a transcrição por blocos e, quando a IA estiver conectada, gera automaticamente o resumo executivo.</p>
      ${longMeetingRecorderHtml()}
      <div class="field"><label>Transcrição consolidada — fonte para o resumo</label><textarea id="meetTranscript" class="transcript" oninput="transcriptText=this.value" placeholder="A transcrição consolidada aparecerá aqui após o processamento.">${esc(transcriptText)}</textarea></div>
      <div class="meeting-ai-grid">
        <div class="field full"><label>Resumo da reunião</label><textarea id="meetSummary">${esc(window.currentMeetingSummary||'')}</textarea></div>
        <div class="field"><label>O que foi tratado</label><textarea id="meetTopics">${esc(window.currentMeetingTopics||'')}</textarea></div>
        <div class="field"><label>Próximos passos</label><textarea id="meetNextSteps">${esc(window.currentMeetingNextSteps||'')}</textarea></div>
        <div class="field"><label>Decisões tomadas</label><textarea id="meetDecisions">${esc(window.currentMeetingDecisions||'')}</textarea></div>
        <div class="field"><label>Pendências / dependências da Diretoria</label><textarea id="meetDependencies">${esc(window.currentMeetingDependencies||'')}</textarea></div>
      </div>
      <div class="actions"><button class="btn light" onclick="goMeetingStep(2)">← Voltar</button><button class="btn blue" onclick="captureMeetingStep3();goMeetingStep(4)" ${listening||longMeetingFinalizing?'disabled':''}>Definir próxima semana →</button></div></div>`;
    if(listening){showRecordingBeacon();updateMeetingTimer();runMeetingMeter()}
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
      const manifestResp=await fetch(`/api/meeting/audio-sessions/${longMeetingSessionId}/segments`);const manifest=await manifestResp.json();if(!manifestResp.ok)throw new Error(manifest.error||'Falha ao listar os blocos.');
      const segments=manifest.segments||[];if(!segments.length)throw new Error('Nenhum bloco de áudio foi salvo.');
      const texts=[];
      for(let i=0;i<segments.length;i++){
        const s=segments[i];meetingProcessStatus=`Transcrevendo bloco ${i+1} de ${segments.length}…`;renderMeetingStep();
        if(s.transcript){texts.push(s.transcript);continue}
        const r=await api(`/api/meeting/audio-sessions/${longMeetingSessionId}/segments/${s.position}/transcribe`,'POST',{});
        if(r.transcript)texts.push(r.transcript);
      }
      transcriptText=texts.join('\n\n').trim()||transcriptText;
      meetingProcessStatus='Transcrição concluída. A IA está estruturando o resumo da reunião…';renderMeetingStep();
      const ai=await api('/api/meeting/summarize','POST',{projectId:meetingProjectId,transcript:transcriptText});
      window.currentMeetingSummary=ai.summary||'';window.currentMeetingTopics=ai.topics||'';window.currentMeetingDecisions=ai.decisions||'';window.currentMeetingNextSteps=ai.nextSteps||'';window.currentMeetingDependencies=ai.dependencies||'';
      if(ai.commitment)window.currentMeetingNext=ai.commitment;
      longMeetingAIProcessed=true;meetingProcessStatus='Resumo de IA concluído. Revise o conteúdo abaixo antes de avançar.';
    }catch(e){
      if(transcriptText&&!window.currentMeetingSummary)window.currentMeetingSummary=summarizeText(transcriptText);
      meetingProcessStatus=`A gravação está preservada, mas o processamento automático não foi concluído: ${e.message}`;
    }finally{longMeetingFinalizing=false;renderMeetingStep()}
  };

  captureMeetingStep3 = function(){
    window.currentMeetingSummary=$('#meetSummary')?.value||window.currentMeetingSummary||'';
    window.currentMeetingTopics=$('#meetTopics')?.value||window.currentMeetingTopics||'';
    window.currentMeetingNextSteps=$('#meetNextSteps')?.value||window.currentMeetingNextSteps||'';
    window.currentMeetingDecisions=$('#meetDecisions')?.value||window.currentMeetingDecisions||'';
    window.currentMeetingDependencies=$('#meetDependencies')?.value||window.currentMeetingDependencies||'';
    transcriptText=$('#meetTranscript')?.value||transcriptText;
  };

  saveMeeting = async function(){
    if(listening){alert('Encerre a gravação antes de salvar a reunião.');return}
    if(longMeetingFinalizing){alert('Aguarde o salvamento/processamento da gravação terminar.');return}
    captureMeetingStep3();window.currentMeetingNext=$('#meetNext')?.value||window.currentMeetingNext||'';
    try{
      await api('/api/meetings','POST',{
        projectId:meetingProjectId,
        notes:window.currentMeetingTopics||'',topics:window.currentMeetingTopics||'',
        decisions:window.currentMeetingDecisions||'',nextSteps:window.currentMeetingNextSteps||'',
        nextWeek:window.currentMeetingNext||'',transcript:transcriptText,summary:window.currentMeetingSummary||'',
        dependencies:window.currentMeetingDependencies||'',audioSessionId:longMeetingSessionId||'',audioSegments:longMeetingUploadedPositions.length,aiProcessed:longMeetingAIProcessed
      });
      alert('Reunião registrada com sucesso.');
      transcriptText='';window.currentMeetingSummary='';window.currentMeetingTopics='';window.currentMeetingNextSteps='';window.currentMeetingDecisions='';window.currentMeetingDependencies='';window.currentMeetingNext='';
      longMeetingSessionId=null;longMeetingSegmentCount=0;longMeetingUploadedPositions=[];longMeetingUploadPromises=[];longMeetingAIProcessed=false;meetingProcessStatus='';meetingStep=1;
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

  applyRoadmapTerms($('#homeView'));
})();