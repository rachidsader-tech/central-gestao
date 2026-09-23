// Transformação KAZ — arquivo executivo de reuniões (somente leitura) + teste controlado de IA.
(function(){
  const previousShowView = showView;
  const previousRenderMeeting = renderMeeting;
  const previousStartNewMeeting = window.startNewMeeting;

  let archiveMode = 'list';
  let archiveDetail = null;
  let archiveLoading = false;
  let aiPreview = null;
  let aiPreviewStatus = '';
  let archiveAudioIndex = 0;

  function fmtDuration(total){
    if(total===null||total===undefined)return 'Sem áudio';
    const s=Math.max(0,Number(total)||0);
    const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);
    if(h)return `${h}h ${String(m).padStart(2,'0')}min`;
    return `${m}min ${String(sec).padStart(2,'0')}s`;
  }
  function fmtMeetingDate(value){
    if(!value)return '—';
    try{return new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})}catch{return value}
  }
  function roValue(value,empty='Não registrado nesta reunião.'){
    const text=String(value||'').trim();
    return `<div class="readonly-value ${text?'':'empty-value'}">${text?esc(text).replace(/\n/g,'<br>'):esc(empty)}</div>`;
  }
  function canTestAI(projectId){
    return isDirection || USER.project_id===projectId;
  }

  showView = function(name){
    if(name==='meeting'&&!listening){
      archiveMode='list';archiveDetail=null;aiPreview=null;aiPreviewStatus='';
    }
    previousShowView(name);
  };

  renderMeeting = function(){
    if(archiveMode==='editor'){
      previousRenderMeeting();
      return;
    }
    if(archiveMode==='detail'){
      renderMeetingArchiveDetail();
      return;
    }
    renderMeetingArchiveList();
  };

  window.startNewMeeting = function(){
    if(listening)return;
    archiveMode='editor';
    previousStartNewMeeting();
  };

  window.openMeetingHome = function(){
    if(listening){alert('Encerre a reunião em andamento antes de voltar.');return}
    archiveMode='list';archiveDetail=null;aiPreview=null;aiPreviewStatus='';renderMeeting();
  };

  window.showRecordedMeetings = function(){
    archiveMode='list';archiveDetail=null;aiPreview=null;aiPreviewStatus='';renderMeeting();
  };

  function renderMeetingArchiveList(){
    const root=$('#meetingView');
    root.innerHTML=`<div class="hero">
      <div><h1>Reuniões</h1><p>Histórico das reuniões gravadas. As reuniões anteriores são somente leitura.</p></div>
      <button class="btn blue" onclick="startNewMeeting()">🎙 Nova reunião</button>
    </div>
    <div class="card">
      <div class="card-h"><h3>Reuniões anteriores</h3></div>
      <div class="pad" id="meetingArchiveList"><div class="empty">Carregando reuniões…</div></div>
    </div>`;
    loadMeetingArchiveList();
  }

  async function loadMeetingArchiveList(){
    const root=$('#meetingArchiveList');if(!root)return;
    try{
      const j=await api('/api/meeting/history');
      const rows=j.meetings||[];
      if(!rows.length){root.innerHTML='<div class="empty">Nenhuma reunião gravada encontrada.</div>';return}
      root.innerHTML=`<div class="meeting-archive-table-wrap"><table class="project-table meeting-archive-table">
        <thead><tr><th>Data</th><th>Projeto</th><th>Tempo de gravação</th><th></th></tr></thead>
        <tbody>${rows.map(m=>`<tr class="clickable" onclick="openMeetingArchive('${m.id}')">
          <td><b>${fmtMeetingDate(m.date)}</b></td>
          <td>${esc(m.projectName||m.projectId)}</td>
          <td>${fmtDuration(m.durationSeconds)}</td>
          <td style="text-align:right"><button class="btn light small" onclick="event.stopPropagation();openMeetingArchive('${m.id}')">Ver reunião →</button></td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    }catch(e){root.innerHTML=`<div class="empty">Falha ao carregar reuniões: ${esc(e.message)}</div>`}
  }

  window.openMeetingArchive = async function(sessionId){
    if(archiveLoading)return;
    archiveMode='detail';archiveDetail=null;aiPreview=null;aiPreviewStatus='';archiveLoading=true;renderMeetingArchiveDetail();
    try{
      archiveDetail=await api(`/api/meeting/history/${encodeURIComponent(sessionId)}`);
      if(archiveDetail.aiTestPreview?.status==='success'){
        aiPreview={
          summary:archiveDetail.aiTestPreview.summary||'',
          topics:archiveDetail.aiTestPreview.topics||'',
          decisions:archiveDetail.aiTestPreview.decisions||'',
          nextSteps:archiveDetail.aiTestPreview.nextSteps||'',
          dependencies:archiveDetail.aiTestPreview.dependencies||'',
          commitment:archiveDetail.aiTestPreview.commitment||''
        };
        aiPreviewStatus='Teste de IA já concluído nesta reunião histórica. A prévia abaixo não altera o registro oficial.';
      }else if(archiveDetail.aiTestPreview?.status==='failed'){
        aiPreviewStatus='O teste automático de IA desta gravação falhou anteriormente. Você pode tentar novamente.';
      }
    }catch(e){
      archiveDetail={error:e.message};
    }finally{
      archiveLoading=false;renderMeetingArchiveDetail();
    }
  };

  function renderPreviousReview(detail){
    const review=detail.previousReview;
    if(!review){
      return '<div class="notice">Esta reunião é anterior ao registro do snapshot da etapa 2. Por isso, não é possível reconstruir com segurança quais compromissos e pendências estavam abertos naquele momento.</div>';
    }
    const commitments=review.commitments||[],deps=review.dependencies||[];
    return `<div class="meeting-read-grid">
      <div>
        <div class="small muted archive-label">COMPROMISSOS DA SEMANA ANTERIOR</div>
        ${commitments.length?commitments.map(c=>`<div class="message"><div class="flex wrap"><strong>${esc(c.text||'')}</strong><span class="right">${badgeCommit(c.status||'Aberto')}</span></div></div>`).join(''):'<div class="empty compact-empty">Nenhum compromisso registrado.</div>'}
      </div>
      <div>
        <div class="small muted archive-label">PENDÊNCIAS EXTERNAS</div>
        ${deps.length?deps.map(d=>`<div class="message"><strong>${esc(d.subject||'Pendência')}</strong><div class="small muted" style="margin-top:5px">${esc(d.status||'')} ${d.director?'· '+esc(d.director):''} ${d.deadline?'· '+esc(d.deadline):''}</div></div>`).join(''):'<div class="empty compact-empty">Nenhuma pendência aberta registrada.</div>'}
      </div>
    </div>`;
  }

  function renderOfficialReview(detail){
    const r=detail.review||{};
    const none=!detail.registered;
    return `<div class="meeting-read-grid">
      <div class="field full"><label>Resumo da reunião</label>${roValue(r.summary,none?'A gravação existe, mas esta reunião não foi fechada/registrada no sistema.':'Não registrado nesta reunião.')}</div>
      <div class="field"><label>O que foi tratado</label>${roValue(r.topics)}</div>
      <div class="field"><label>Decisões tomadas</label>${roValue(r.decisions)}</div>
      <div class="field"><label>Próximos passos</label>${roValue(r.nextSteps)}</div>
      <div class="field"><label>Pendências / dependências da Diretoria</label>${roValue(r.dependencies)}</div>
      <div class="field full"><label>Compromisso estratégico da próxima reunião</label>${roValue(r.commitment)}</div>
    </div>`;
  }

  function renderAiPreview(detail){
    if(!canTestAI(detail.projectId))return '';
    if(!aiPreview){
      return `<div class="card ai-preview-card"><div class="pad">
        <div class="flex wrap"><div><b>Teste da IA nesta gravação</b><div class="muted small">Gera uma prévia sem alterar nem salvar a reunião histórica.</div></div>
        <button class="btn blue right" onclick="runMeetingAiPreview()" ${archiveLoading?'disabled':''}>Testar IA nesta gravação</button></div>
        ${aiPreviewStatus?`<div class="info" style="margin-top:12px">${esc(aiPreviewStatus)}</div>`:''}
      </div></div>`;
    }
    return `<div class="card ai-preview-card"><div class="card-h"><h3>Prévia da IA — teste, não salva a reunião</h3></div><div class="pad">
      ${aiPreviewStatus?`<div class="good" style="margin-bottom:12px">${esc(aiPreviewStatus)}</div>`:''}
      <div class="meeting-read-grid">
        <div class="field full"><label>Resumo da reunião</label>${roValue(aiPreview.summary)}</div>
        <div class="field"><label>O que foi tratado</label>${roValue(aiPreview.topics)}</div>
        <div class="field"><label>Decisões tomadas</label>${roValue(aiPreview.decisions)}</div>
        <div class="field"><label>Próximos passos</label>${roValue(aiPreview.nextSteps)}</div>
        <div class="field"><label>Pendências / dependências da Diretoria</label>${roValue(aiPreview.dependencies)}</div>
        <div class="field full"><label>Possível compromisso estratégico da próxima reunião</label>${roValue(aiPreview.commitment)}</div>
      </div>
      <div class="actions"><button class="btn light" onclick="runMeetingAiPreview()">↻ Reprocessar teste</button></div>
    </div></div>`;
  }

  function renderMeetingArchiveDetail(){
    const root=$('#meetingView');if(!root)return;
    if(archiveLoading&&!archiveDetail){
      root.innerHTML='<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button><div class="card empty" style="margin-top:14px">Carregando reunião…</div>';return;
    }
    if(archiveDetail?.error){
      root.innerHTML=`<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button><div class="card empty" style="margin-top:14px">${esc(archiveDetail.error)}</div>`;return;
    }
    const d=archiveDetail;
    if(!d){renderMeetingArchiveList();return}
    const firstAudio=d.segments?.[0]?.url||'';
    root.innerHTML=`<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button>
      <div class="detail-head meeting-archive-head" style="margin-top:15px">
        <div><div class="muted small" style="text-transform:uppercase">Reunião registrada</div><h1>${esc(d.projectName)}</h1><div class="muted small">${fmtMeetingDate(d.date)} · ${fmtDuration(d.durationSeconds)} · ${esc(d.createdBy||'')}</div></div>
        <span class="pill s-nao">Somente leitura</span>
      </div>

      <div class="meeting-archive-section">
        <div class="archive-step-number">2</div>
        <div class="archive-step-body"><h2>Semana anterior</h2><p class="muted small">Retrato dos compromissos e pendências registrados no fechamento daquela reunião.</p>${renderPreviousReview(d)}</div>
      </div>

      <div class="meeting-archive-section">
        <div class="archive-step-number">3</div>
        <div class="archive-step-body"><h2>Gravação da reunião</h2>
          <div class="card"><div class="pad">
            <div class="flex wrap"><div><b>Áudio da reunião</b><div class="muted small">Uma única reunião para o usuário; os blocos técnicos ficam ocultos.</div></div><span class="right pill s-conc">${fmtDuration(d.durationSeconds)}</span></div>
            ${firstAudio?`<audio id="meetingArchiveAudio" controls preload="metadata" style="width:100%;margin-top:12px"></audio>`:'<div class="empty compact-empty">Áudio não disponível.</div>'}
            ${d.transcript?`<details class="archive-transcript"><summary>Ver transcrição</summary><div class="readonly-value transcript-readonly">${esc(d.transcript).replace(/\n/g,'<br>')}</div></details>`:''}
          </div></div>
        </div>
      </div>

      <div class="meeting-archive-section">
        <div class="archive-step-number">4</div>
        <div class="archive-step-body"><h2>Revisão e próximos passos</h2><p class="muted small">Conteúdo oficial salvo no fechamento da reunião. Não pode ser alterado nesta tela.</p>
          <div class="card"><div class="pad">${renderOfficialReview(d)}</div></div>
        </div>
      </div>

      ${renderAiPreview(d)}
    `;
    setupArchiveAudio();
  }

  function setupArchiveAudio(){
    const audio=document.getElementById('meetingArchiveAudio');
    const segments=archiveDetail?.segments||[];
    if(!audio||!segments.length)return;
    archiveAudioIndex=0;
    audio.src=segments[0].url;
    audio.onended=()=>{
      if(archiveAudioIndex<segments.length-1){
        archiveAudioIndex++;
        audio.src=segments[archiveAudioIndex].url;
        audio.play().catch(()=>{});
      }
    };
  }

  window.runMeetingAiPreview = async function(){
    const d=archiveDetail;if(!d||archiveLoading)return;
    if(!canTestAI(d.projectId)){alert('Sem permissão para processar esta gravação.');return}
    archiveLoading=true;aiPreview=null;aiPreviewStatus='Preparando transcrição do áudio…';renderMeetingArchiveDetail();
    try{
      const manifest=await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/segments`);
      const pieces=[];
      for(let i=0;i<(manifest.segments||[]).length;i++){
        const s=manifest.segments[i];
        aiPreviewStatus=`Transcrevendo áudio: parte ${i+1} de ${manifest.segments.length}…`;renderMeetingArchiveDetail();
        if(s.transcript){pieces.push(s.transcript);continue}
        try{
          const tr=await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/segments/${s.position}/transcribe`,'POST',{});
          if(tr.transcript)pieces.push(tr.transcript);
        }catch(e){
          // Trechos muito curtos ou silenciosos podem retornar sem fala; seguimos com os demais.
          if(!String(e.message||'').toLowerCase().includes('não produziu transcrição'))throw e;
        }
      }
      const transcript=pieces.join('\n\n').trim();
      if(!transcript)throw new Error('A gravação não produziu transcrição suficiente para o teste.');
      aiPreviewStatus='Transcrição concluída. A IA está estruturando a reunião…';renderMeetingArchiveDetail();
      const result=await api('/api/meeting/summarize','POST',{projectId:d.projectId,transcript});
      aiPreview={
        summary:result.summary||'',
        topics:result.topics||'',
        decisions:result.decisions||'',
        nextSteps:result.nextSteps||'',
        dependencies:result.dependencies||'',
        commitment:result.commitment||'',
        transcript
      };
      aiPreviewStatus='Teste concluído. Esta prévia não foi salva nem alterou a reunião histórica.';
    }catch(e){
      aiPreviewStatus='Teste não concluído: '+e.message;
      alert(aiPreviewStatus);
    }finally{
      archiveLoading=false;renderMeetingArchiveDetail();
    }
  };
})();