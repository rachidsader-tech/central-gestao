// Transformação KAZ — pós-reunião: compromisso, anexos e documento único por IA.
(function(){
  const previousShowView = showView;
  const previousRenderMeeting = renderMeeting;
  const previousStartNewMeeting = window.startNewMeeting;

  let archiveMode='list';
  let archiveDetail=null;
  let archiveLoading=false;
  let archiveAudioIndex=0;
  let archiveStatus='';

  function fmtDuration(total){
    if(total===null||total===undefined)return 'Sem áudio';
    const sec=Math.max(0,Number(total)||0);
    const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=Math.floor(sec%60);
    return h?`${h}h ${String(m).padStart(2,'0')}min`:`${m}min ${String(s).padStart(2,'0')}s`;
  }
  function fmtMeetingDate(value){
    if(!value)return '—';
    try{return new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})}catch{return value}
  }
  function humanMeetingFileSize(n){
    if(!n)return '0 B';
    const u=['B','KB','MB','GB'];let i=0,v=n;
    while(v>=1024&&i<u.length-1){v/=1024;i++}
    return `${v.toFixed(i?1:0)} ${u[i]}`;
  }
  function meetingDocumentHtml(text){
    const value=String(text||'').trim();
    if(!value)return '<div class="empty">O documento da reunião ainda não foi gerado.</div>';
    return `<div class="readonly-value meeting-document-text">${esc(value).replace(/\n/g,'<br>')}</div>`;
  }

  showView=function(name){
    if(name==='meeting'&&!listening){
      archiveMode='list';archiveDetail=null;archiveStatus='';
    }
    previousShowView(name);
  };

  renderMeeting=function(){
    if(archiveMode==='editor'){previousRenderMeeting();return}
    if(archiveMode==='detail'){renderMeetingArchiveDetail();return}
    renderMeetingArchiveList();
  };

  window.startNewMeeting=function(){
    if(listening)return;
    archiveMode='editor';archiveDetail=null;archiveStatus='';
    previousStartNewMeeting();
  };
  window.openMeetingHome=function(){
    if(listening){alert('Encerre a reunião em andamento antes de voltar.');return}
    archiveMode='list';archiveDetail=null;archiveStatus='';renderMeeting();
  };
  window.showRecordedMeetings=function(){window.openMeetingHome()};

  function renderMeetingArchiveList(){
    const root=$('#meetingView');
    root.innerHTML=`<div class="hero">
      <div><h1>Reuniões</h1><p>Gravação, compromisso, arquivos apresentados e documento da reunião.</p></div>
      <button class="btn blue" onclick="startNewMeeting()">🎙 Nova reunião</button>
    </div>
    <div class="card"><div class="card-h"><h3>Reuniões anteriores</h3></div>
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
        <thead><tr><th>Data</th><th>Projeto</th><th>Gravação</th><th>Situação</th><th></th></tr></thead>
        <tbody>${rows.map(m=>`<tr class="clickable" onclick="openMeetingArchive('${m.id}')">
          <td><b>${fmtMeetingDate(m.date)}</b></td>
          <td>${esc(m.projectName||m.projectId)}</td>
          <td>${fmtDuration(m.durationSeconds)}</td>
          <td>${m.registered?(m.aiProcessed?'<span class="pill s-conc">Documento gerado</span>':'<span class="pill s-analise">Pós-reunião aberto</span>'):'<span class="pill s-risco">Não salva</span>'}</td>
          <td style="text-align:right"><button class="btn light small" onclick="event.stopPropagation();openMeetingArchive('${m.id}')">Abrir →</button></td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    }catch(e){root.innerHTML=`<div class="empty">Falha ao carregar reuniões: ${esc(e.message)}</div>`}
  }

  window.openMeetingArchive=async function(sessionId){
    if(archiveLoading)return;
    archiveMode='detail';archiveDetail=null;archiveStatus='';archiveLoading=true;renderMeetingArchiveDetail();
    try{archiveDetail=await api(`/api/meeting/history/${encodeURIComponent(sessionId)}`)}
    catch(e){archiveDetail={error:e.message}}
    finally{archiveLoading=false;renderMeetingArchiveDetail()}
  };

  function commitmentBox(d){
    const value=d.review?.commitment||'';
    if(!d.registered){
      return '<div class="notice"><b>Reunião ainda não salva.</b> O compromisso será solicitado quando a reunião for registrada.</div>';
    }
    if(!d.canEdit){
      return `<div class="field"><label>Compromisso para a próxima reunião</label><div class="readonly-value">${value?esc(value):'Não informado.'}</div></div>`;
    }
    return `<div class="field"><label>Compromisso para a próxima reunião</label>
      <textarea id="archiveCommitment" style="min-height:110px" placeholder="Informe o resultado esperado até a próxima reunião.">${esc(value)}</textarea>
      <div class="muted small" style="margin-top:6px">Este é o compromisso que aparecerá no início da próxima reunião deste projeto. Pode ser alterado mesmo com a reunião encerrada.</div>
    </div>
    <div class="actions"><button class="btn blue" onclick="saveArchivedMeetingCommitment()">Salvar compromisso</button></div>`;
  }

  function attachmentsBox(d){
    const files=d.attachments||[];
    const rows=files.length?files.map(a=>`<div class="roadmap-file-row">
      <div><a href="${a.url}" class="roadmap-file-link">${esc(a.name)}</a>
        <div class="muted small">${humanMeetingFileSize(a.size)} · ${esc(a.uploadedBy||'')} · ${fmtDate(a.createdAt)}</div>
      </div><a href="${a.url}" class="btn light small">Baixar</a>
    </div>`).join(''):'<div class="muted small">Nenhum arquivo apresentado foi anexado.</div>';
    return `<div class="card"><div class="card-h"><h3>Arquivos apresentados na reunião</h3></div><div class="pad">
      <p class="muted small" style="margin-top:0">Depois que a reunião é salva, os documentos apresentados podem ser anexados aqui. Eles também aparecem dentro do projeto e podem ser considerados pela IA.</p>
      <div id="archiveMeetingFiles">${rows}</div>
      ${d.canEdit&&d.registered?`<div class="flex wrap" style="margin-top:12px">
        <input id="archiveMeetingFileInput" type="file" class="roadmap-file-input-hidden" onchange="uploadArchivedMeetingFile()">
        <button class="btn light small" onclick="chooseArchivedMeetingFile()">＋ Anexar arquivo</button>
        <span id="archiveMeetingFileStatus" class="muted small">Limite de 20 MB por arquivo.</span>
      </div>`:''}
    </div></div>`;
  }

  function aiDocumentBox(d){
    if(!d.registered)return '';
    const summary=d.review?.summary||'';
    const button=d.canEdit?`<button class="btn blue" onclick="generateArchivedMeetingDocument()" ${archiveLoading?'disabled':''}>${summary?'↻ Reprocessar documento da reunião':'Gerar documento da reunião com IA'}</button>`:'';
    return `<div class="card"><div class="card-h"><h3>Documento da reunião</h3>${button}</div><div class="pad">
      <p class="muted small" style="margin-top:0">Síntese única da reunião. A IA usa a gravação/transcrição, o compromisso informado pela pessoa e, quando legíveis, os arquivos anexados.</p>
      ${archiveStatus?`<div class="info" style="margin-bottom:12px">${esc(archiveStatus)}</div>`:''}
      ${meetingDocumentHtml(summary)}
    </div></div>`;
  }

  function audioBox(d){
    const first=d.segments?.[0]?.url||'';
    return `<details class="ux-meeting-secondary" style="margin-top:14px"><summary>Gravação e transcrição</summary>
      <div class="card" style="margin-top:10px"><div class="pad">
        <div class="flex wrap"><div><b>Áudio da reunião</b><div class="muted small">A gravação técnica pode estar dividida em blocos, mas é reproduzida em sequência.</div></div><span class="right pill s-nao">${fmtDuration(d.durationSeconds)}</span></div>
        ${first?'<audio id="meetingArchiveAudio" controls preload="metadata" style="width:100%;margin-top:12px"></audio>':'<div class="empty">Áudio não disponível.</div>'}
        ${d.transcript?`<details class="archive-transcript"><summary>Ver transcrição</summary><div class="readonly-value transcript-readonly">${esc(d.transcript).replace(/\n/g,'<br>')}</div></details>`:''}
      </div></div>
    </details>`;
  }

  function renderMeetingArchiveDetail(){
    const root=$('#meetingView');if(!root)return;
    if(archiveLoading&&!archiveDetail){
      root.innerHTML='<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button><div class="card empty" style="margin-top:14px">Carregando reunião…</div>';return;
    }
    if(archiveDetail?.error){
      root.innerHTML=`<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button><div class="card empty" style="margin-top:14px">${esc(archiveDetail.error)}</div>`;return;
    }
    const d=archiveDetail;if(!d){renderMeetingArchiveList();return}
    root.innerHTML=`<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button>
      <div class="detail-head meeting-archive-head" style="margin-top:15px">
        <div><div class="muted small" style="text-transform:uppercase">Reunião</div><h1>${esc(d.projectName)}</h1><div class="muted small">${fmtMeetingDate(d.date)} · ${fmtDuration(d.durationSeconds)} · ${esc(d.createdBy||'')}</div></div>
        <span class="pill ${d.registered?'s-conc':'s-risco'}">${d.registered?'Reunião salva':'Não salva'}</span>
      </div>

      <div class="card" style="margin-bottom:14px"><div class="card-h"><h3>Compromisso da próxima reunião</h3></div><div class="pad">${commitmentBox(d)}</div></div>
      ${attachmentsBox(d)}
      <div style="margin-top:14px">${aiDocumentBox(d)}</div>
      ${audioBox(d)}
    `;
    setupArchiveAudio();
  }

  window.saveArchivedMeetingCommitment=async function(){
    const d=archiveDetail;if(!d||!d.canEdit)return;
    const value=$('#archiveCommitment')?.value.trim()||'';
    try{
      await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/commitment`,'POST',{commitment:value});
      d.review=d.review||{};d.review.commitment=value;
      await refresh();
      archiveStatus='Compromisso atualizado. Ele aparecerá na próxima reunião deste projeto.';
      renderMeetingArchiveDetail();
    }catch(e){alert(e.message)}
  };

  window.chooseArchivedMeetingFile=function(){
    document.getElementById('archiveMeetingFileInput')?.click();
  };
  window.uploadArchivedMeetingFile=async function(){
    const d=archiveDetail,input=$('#archiveMeetingFileInput'),file=input?.files?.[0];
    if(!d||!file)return;
    if(file.size>20*1024*1024){input.value='';alert('O arquivo excede o limite de 20 MB.');return}
    const status=$('#archiveMeetingFileStatus');if(status)status.textContent='Enviando '+file.name+'…';
    const fd=new FormData();fd.append('file',file);
    try{
      const r=await fetch(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/attachments`,{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
      const raw=await r.text();let j={};try{j=raw?JSON.parse(raw):{}}catch{}
      if(!r.ok)throw new Error(j.error||'Falha ao anexar arquivo.');
      input.value='';archiveDetail=await api(`/api/meeting/history/${encodeURIComponent(d.id)}`);
      archiveStatus='Arquivo anexado. Ele já está disponível na reunião e no projeto.';
      renderMeetingArchiveDetail();
    }catch(e){if(status)status.textContent='Falha ao anexar.';alert(e.message)}
  };

  window.generateArchivedMeetingDocument=async function(){
    const d=archiveDetail;if(!d||!d.canEdit||archiveLoading)return;
    archiveLoading=true;archiveStatus='Preparando a transcrição da gravação…';renderMeetingArchiveDetail();
    try{
      const manifest=await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/segments`);
      const pieces=[];
      for(let i=0;i<(manifest.segments||[]).length;i++){
        const seg=manifest.segments[i];
        archiveStatus=`Transcrevendo a gravação: parte ${i+1} de ${manifest.segments.length}…`;renderMeetingArchiveDetail();
        if(seg.transcript){pieces.push(seg.transcript);continue}
        try{
          const tr=await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/segments/${seg.position}/transcribe`,'POST',{});
          if(tr.transcript)pieces.push(tr.transcript);
        }catch(e){
          if(!String(e.message||'').toLowerCase().includes('não produziu transcrição'))throw e;
        }
      }
      const transcript=pieces.join('\n\n').trim()||d.transcript||'';
      if(!transcript)throw new Error('A gravação não produziu transcrição suficiente para gerar o documento.');
      archiveStatus='Transcrição concluída. Gerando o documento da reunião com a gravação e os anexos…';renderMeetingArchiveDetail();
      const result=await api('/api/meeting/summarize','POST',{projectId:d.projectId,sessionId:d.id,transcript});
      archiveDetail=await api(`/api/meeting/history/${encodeURIComponent(d.id)}`);
      archiveDetail.review=archiveDetail.review||{};archiveDetail.review.summary=result.summary||archiveDetail.review.summary||'';
      archiveStatus='Documento da reunião gerado e salvo.';
      await refresh();
    }catch(e){archiveStatus='Não foi possível gerar o documento: '+e.message;alert(archiveStatus)}
    finally{archiveLoading=false;renderMeetingArchiveDetail()}
  };

  function setupArchiveAudio(){
    const audio=document.getElementById('meetingArchiveAudio'),segments=archiveDetail?.segments||[];
    if(!audio||!segments.length)return;
    archiveAudioIndex=0;audio.src=segments[0].url;
    audio.onended=()=>{
      if(archiveAudioIndex<segments.length-1){
        archiveAudioIndex++;audio.src=segments[archiveAudioIndex].url;audio.play().catch(()=>{});
      }
    };
  }
})();