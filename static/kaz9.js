// Transformação KAZ — Documentos + pós-reunião definitivo.
(function(){
  const previousShowViewV9=showView;
  const previousRenderMeetingV9=renderMeeting;
  const previousStartNewMeetingV9=window.startNewMeeting;
  const previousRenderProjectV9=renderProject;
  const previousRenderProjectPanelV9=renderProjectPanel;

  let v9MeetingMode='list';
  let v9MeetingDetail=null;
  let v9MeetingLoading=false;
  let v9MeetingStatus='';
  let v9AudioIndex=0;

  function v9Duration(total){
    if(total===null||total===undefined)return 'Sem áudio';
    const sec=Math.max(0,Number(total)||0),h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=Math.floor(sec%60);
    return h?`${h}h ${String(m).padStart(2,'0')}min`:`${m}min ${String(s).padStart(2,'0')}s`;
  }
  function v9Date(value){
    if(!value)return '—';
    try{return new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})}catch{return value}
  }
  function v9Size(n){
    if(!n)return '0 B';
    const u=['B','KB','MB','GB'];let i=0,v=Number(n)||0;
    while(v>=1024&&i<u.length-1){v/=1024;i++}
    return `${v.toFixed(i?1:0)} ${u[i]}`;
  }
  function v9Lines(value){
    return String(value||'').split(/\n+/).map(x=>x.trim()).filter(Boolean);
  }
  function v9MeetingStatusBadge(status){
    return status==='Reunião completa'
      ?'<span class="pill s-conc">Reunião completa</span>'
      :'<span class="pill s-nao">Reunião finalizada</span>';
  }
  function v9AiBadge(processed){
    return processed
      ?'<span class="pill s-conc">✓ Resumo IA processado</span>'
      :'<span class="pill s-nao">Resumo IA pendente</span>';
  }

  showView=function(name){
    if(name==='meeting'&&!listening){v9MeetingMode='list';v9MeetingDetail=null;v9MeetingStatus=''}
    previousShowViewV9(name);
  };

  renderMeeting=function(){
    if(v9MeetingMode==='editor'){previousRenderMeetingV9();return}
    if(v9MeetingMode==='detail'){renderV9MeetingDetail();return}
    renderV9MeetingList();
  };

  window.startNewMeeting=function(){
    v9MeetingMode='editor';v9MeetingDetail=null;v9MeetingStatus='';
    previousStartNewMeetingV9();
  };
  window.openMeetingHome=function(){
    if(listening){alert('Encerre a reunião em andamento antes de voltar.');return}
    v9MeetingMode='list';v9MeetingDetail=null;v9MeetingStatus='';renderMeeting();
  };
  window.showRecordedMeetings=function(){window.openMeetingHome()};

  function renderV9MeetingList(){
    const root=$('#meetingView');if(!root)return;
    root.innerHTML=`<div class="hero meeting-list-hero">
      <div><h1>Reuniões</h1><p>Histórico oficial das reuniões, apresentações anexadas e resumos processados pela IA.</p></div>
      <button class="btn blue" onclick="startNewMeeting()">🎙 Nova reunião</button>
    </div>
    <div class="card"><div class="card-h"><h3>Reuniões anteriores</h3></div>
      <div class="pad" id="v9MeetingList"><div class="empty">Carregando reuniões…</div></div>
    </div>`;
    loadV9MeetingList();
  }

  async function loadV9MeetingList(){
    const root=$('#v9MeetingList');if(!root)return;
    try{
      const j=await api('/api/meeting/history');
      const rows=(j.meetings||[]).filter(m=>m.registered);
      if(!rows.length){root.innerHTML='<div class="empty">Nenhuma reunião finalizada encontrada.</div>';return}
      root.innerHTML=`<div class="meeting-archive-table-wrap"><table class="project-table meeting-archive-table">
        <thead><tr><th>Data</th><th>Projeto</th><th>Duração</th><th>Status</th><th>Resumo IA</th><th></th></tr></thead>
        <tbody>${rows.map(m=>`<tr class="clickable" onclick="openMeetingArchive('${m.id}')">
          <td><b>${v9Date(m.date)}</b></td>
          <td>${esc(m.projectName)}</td>
          <td>${v9Duration(m.durationSeconds)}</td>
          <td>${v9MeetingStatusBadge(m.meetingStatus)}</td>
          <td>${v9AiBadge(m.aiProcessed)}</td>
          <td style="text-align:right"><button class="btn light small" onclick="event.stopPropagation();openMeetingArchive('${m.id}')">Abrir →</button></td>
        </tr>`).join('')}</tbody></table></div>`;
    }catch(e){root.innerHTML=`<div class="empty">Falha ao carregar reuniões: ${esc(e.message)}</div>`}
  }

  window.openMeetingArchive=async function(sessionId){
    if(v9MeetingLoading)return;
    v9MeetingMode='detail';v9MeetingDetail=null;v9MeetingStatus='';v9MeetingLoading=true;renderV9MeetingDetail();
    try{v9MeetingDetail=await api(`/api/meeting/history/${encodeURIComponent(sessionId)}`)}
    catch(e){v9MeetingDetail={error:e.message}}
    finally{v9MeetingLoading=false;renderV9MeetingDetail()}
  };

  function v9CommitmentBox(d){
    const value=d.review?.commitment||'';
    if(!d.registered)return '<div class="notice">A reunião ainda não foi registrada.</div>';
    if(!d.canEditCommitment){
      return `<div class="field"><label>Compromisso para a próxima reunião</label>
        <div class="readonly-value">${value?esc(value):'Não informado.'}</div>
        <div class="muted small" style="margin-top:6px">Após a reunião, somente Rachid pode alterar este compromisso.</div></div>`;
    }
    return `<div class="field"><label>Compromisso para a próxima reunião</label>
      <textarea id="v9Commitment" style="min-height:105px" placeholder="Informe o resultado esperado até a próxima reunião.">${esc(value)}</textarea>
      <div class="muted small" style="margin-top:6px">Edição pós-reunião restrita a Rachid.</div>
      <div class="actions"><button class="btn blue" onclick="saveV9Commitment()">Salvar compromisso</button></div></div>`;
  }

  function v9AttachmentsBox(d){
    const files=d.attachments||[];
    const rows=files.length?files.map(a=>`<div class="roadmap-file-row">
      <div><a href="${a.url}" class="roadmap-file-link">${esc(a.name)}</a>
        <div class="muted small">${v9Size(a.size)} · ${esc(a.uploadedBy||'')} · ${fmtDate(a.createdAt)}</div></div>
      <a class="btn light small" href="${a.url}">Baixar</a>
    </div>`).join(''):'<div class="empty compact-empty">Nenhuma apresentação ou documento anexado nesta reunião.</div>';
    return `<div class="card meeting-files-card"><div class="card-h"><div><h3>Apresentação / documentos da reunião</h3>
      <div class="muted small">Os arquivos anexados ficam visíveis aqui e também na aba Documentos do projeto.</div></div></div>
      <div class="pad"><div class="roadmap-file-list">${rows}</div>
      ${d.canUploadAttachment?`<div class="meeting-attach-line">
        <input id="v9MeetingFile" type="file" class="roadmap-file-input-hidden" onchange="uploadV9MeetingFile()">
        <button class="btn light small" onclick="document.getElementById('v9MeetingFile').click()">＋ Anexar apresentação</button>
        <span id="v9MeetingFileStatus" class="muted small">Limite de 20 MB por arquivo.</span>
      </div>`:''}</div></div>`;
  }

  function v9AiDocument(d){
    const doc=d.aiDocument||{},processed=Boolean(d.review?.aiProcessed);
    if(!processed){
      return `<div class="meeting-ai-empty"><div>${v9AiBadge(false)}</div><p>O registro executivo ainda não foi processado com sucesso.</p></div>`;
    }

    const legacy=Boolean(d.review?.isLegacyAiDocument);
    const executive=String(doc.executiveSummary||'').trim();
    const points=Array.isArray(doc.keyPoints)?doc.keyPoints.filter(x=>x&&String(x.text||'').trim()):[];
    const nextSteps=Array.isArray(doc.nextSteps)?doc.nextSteps.filter(x=>x&&String(x.text||'').trim()):[];
    const attention=Array.isArray(doc.attentionPoints)?doc.attentionPoints.filter(Boolean):[];
    const complete=String(doc.meetingSummary||'').trim();
    const paragraphs=complete.split(/\n\s*\n/).map(x=>x.trim()).filter(Boolean);

    const keyPointsHtml=points.length
      ?`<div class="executive-points-grid">${points.map((item,index)=>`
        <div class="executive-point-card ${item.type==='decision'?'decision':''}">
          <div class="executive-point-number">${String(index+1).padStart(2,'0')}</div>
          <div class="executive-point-content">
            <div class="executive-point-type">${item.type==='decision'?'DECISÃO':'IMPORTANTE'}</div>
            <div class="executive-point-text">${esc(item.text)}</div>
          </div>
        </div>`).join('')}</div>`
      :'<div class="executive-empty">Nenhuma decisão ou ponto estratégico adicional foi identificado.</div>';

    const nextStepsHtml=nextSteps.length
      ?`<div class="executive-next-table">
        <div class="executive-next-head"><div>PRÓXIMO PASSO</div><div>RESPONSÁVEL</div><div>PRAZO</div></div>
        ${nextSteps.map(item=>`<div class="executive-next-row">
          <div><b>${esc(item.text)}</b></div>
          <div>${esc(item.responsible||'—')}</div>
          <div>${esc(item.deadline||'—')}</div>
        </div>`).join('')}
      </div>`
      :'<div class="executive-empty">Nenhuma pendência ou próximo passo foi identificado com segurança.</div>';

    const attentionHtml=attention.length
      ?`<div class="executive-attention"><div class="executive-section-eyebrow">PONTOS DE ATENÇÃO</div>
        <ul>${attention.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`
      :'';

    return `<div class="meeting-ai-document executive-document">
      ${legacy?`<div class="executive-legacy-banner">
        <div><b>Resumo no padrão anterior</b><span>Reprocesse esta reunião para aplicar o novo Registro Executivo.</span></div>
      </div>`:''}

      <section class="executive-summary-hero">
        <div class="executive-section-eyebrow">RESUMO EXECUTIVO</div>
        <div class="executive-summary-text">${executive?esc(executive):'Resumo executivo não disponível.'}</div>
      </section>

      <section class="executive-section">
        <div class="executive-section-title">Decisões e pontos importantes</div>
        ${keyPointsHtml}
      </section>

      <section class="executive-section">
        <div class="executive-section-title">Pendências e próximos passos</div>
        ${nextStepsHtml}
      </section>

      ${attentionHtml}

      <section class="executive-section executive-long-summary">
        <div class="executive-section-title">Sumário da reunião</div>
        <div class="meeting-full-summary">${paragraphs.map(x=>`<p>${esc(x).replace(/\n/g,'<br>')}</p>`).join('')||'<p>Sumário não disponível.</p>'}</div>
      </section>
    </div>`;
  }

  function v9AiBox(d){
    const processed=Boolean(d.review?.aiProcessed);
    const legacy=Boolean(d.review?.isLegacyAiDocument);
    const actionLabel=!processed?'Processar registro executivo':legacy?'Reprocessar no novo padrão':'↻ Reprocessar registro executivo';
    return `<div class="card meeting-ai-card executive-shell"><div class="card-h executive-shell-head">
      <div><div class="executive-shell-kicker">REGISTRO EXECUTIVO</div><h3>Reunião</h3><div class="muted small">Síntese de gestão gerada a partir da gravação e dos documentos anexados.</div></div>
      <div class="flex wrap">${v9AiBadge(processed)}</div>
    </div><div class="pad">
      ${v9MeetingStatus?`<div class="info" style="margin-bottom:12px">${esc(v9MeetingStatus)}</div>`:''}
      ${v9AiDocument(d)}
      <div class="actions meeting-document-actions">
        ${d.canGenerateAi?`<button class="btn blue" onclick="generateV9MeetingSummary()" ${v9MeetingLoading?'disabled':''}>${actionLabel}</button>`:''}
        ${processed?`<a class="btn light" target="_blank" href="${d.pdfUrl}">Abrir PDF executivo</a>
          <a class="btn light" href="${d.pdfUrl}?download=1">Baixar PDF</a>
          <button class="btn light" onclick="shareV9MeetingPdf()">Compartilhar PDF</button>`:''}
      </div>
    </div></div>`;
  }

  function v9AudioBox(d){
    const first=(d.segments||[])[0];
    return `<details class="ux-meeting-secondary" style="margin-top:14px"><summary>Gravação e transcrição</summary>
      <div class="card" style="margin-top:10px"><div class="pad">
        <div class="flex wrap"><div><b>Áudio da reunião</b><div class="muted small">A gravação pode estar dividida em blocos, reproduzidos em sequência.</div></div><span class="right pill s-nao">${v9Duration(d.durationSeconds)}</span></div>
        ${first?'<audio id="v9MeetingAudio" controls preload="metadata" style="width:100%;margin-top:12px"></audio>':'<div class="empty">Áudio não disponível.</div>'}
        ${d.transcript?`<details class="archive-transcript"><summary>Ver transcrição</summary><div class="readonly-value transcript-readonly">${esc(d.transcript).replace(/\n/g,'<br>')}</div></details>`:''}
      </div></div></details>`;
  }

  function renderV9MeetingDetail(){
    const root=$('#meetingView');if(!root)return;
    if(v9MeetingLoading&&!v9MeetingDetail){
      root.innerHTML='<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button><div class="card empty" style="margin-top:14px">Carregando reunião…</div>';return;
    }
    if(v9MeetingDetail?.error){
      root.innerHTML=`<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button><div class="card empty" style="margin-top:14px">${esc(v9MeetingDetail.error)}</div>`;return;
    }
    const d=v9MeetingDetail;if(!d){renderV9MeetingList();return}
    root.innerHTML=`<button class="btn light small" onclick="openMeetingHome()">← Reuniões</button>
      <div class="detail-head meeting-archive-head" style="margin-top:15px">
        <div><div class="muted small" style="text-transform:uppercase">Reunião</div><h1>${esc(d.projectName)}</h1>
          <div class="muted small">${v9Date(d.date)} · ${v9Duration(d.durationSeconds)} · ${esc(d.createdBy||'')}</div></div>
        <div class="flex wrap">${v9MeetingStatusBadge(d.meetingStatus)}${v9AiBadge(d.review?.aiProcessed)}</div>
      </div>
      <div class="card" style="margin-bottom:14px"><div class="card-h"><h3>Compromisso da próxima reunião</h3></div><div class="pad">${v9CommitmentBox(d)}</div></div>
      ${v9AttachmentsBox(d)}
      <div style="margin-top:14px">${v9AiBox(d)}</div>
      ${v9AudioBox(d)}`;
    setupV9Audio();
  }

  window.saveV9Commitment=async function(){
    const d=v9MeetingDetail;if(!d||!d.canEditCommitment)return;
    try{
      const value=$('#v9Commitment')?.value.trim()||'';
      await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/commitment`,'POST',{commitment:value});
      v9MeetingDetail=await api(`/api/meeting/history/${encodeURIComponent(d.id)}`);
      v9MeetingStatus='Compromisso atualizado.';renderV9MeetingDetail();
    }catch(e){alert(e.message)}
  };

  window.uploadV9MeetingFile=async function(){
    const d=v9MeetingDetail,input=$('#v9MeetingFile'),file=input?.files?.[0];if(!d||!file)return;
    if(file.size>20*1024*1024){input.value='';alert('O arquivo excede 20 MB.');return}
    const status=$('#v9MeetingFileStatus');if(status)status.textContent='Enviando '+file.name+'…';
    const fd=new FormData();fd.append('file',file);
    try{
      const r=await fetch(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/attachments`,{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
      let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.error||'Falha ao anexar arquivo.');
      input.value='';v9MeetingDetail=await api(`/api/meeting/history/${encodeURIComponent(d.id)}`);
      v9MeetingStatus='Arquivo anexado. A reunião agora aparece como completa.';renderV9MeetingDetail();
    }catch(e){if(status)status.textContent='Falha ao anexar.';alert(e.message)}
  };

  window.generateV9MeetingSummary=async function(){
    const d=v9MeetingDetail;if(!d||!d.canGenerateAi||v9MeetingLoading)return;
    v9MeetingLoading=true;v9MeetingStatus='Preparando a transcrição da gravação…';renderV9MeetingDetail();
    try{
      const manifest=await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/segments`);
      const texts=[];
      for(let i=0;i<(manifest.segments||[]).length;i++){
        const seg=manifest.segments[i];
        v9MeetingStatus=`Transcrevendo a gravação: parte ${i+1} de ${manifest.segments.length}…`;renderV9MeetingDetail();
        if(seg.transcript){texts.push(seg.transcript);continue}
        const tr=await api(`/api/meeting/audio-sessions/${encodeURIComponent(d.id)}/segments/${seg.position}/transcribe`,'POST',{});
        if(tr.transcript)texts.push(tr.transcript);
      }
      const transcript=texts.join('\n\n').trim()||d.transcript||'';
      if(!transcript)throw new Error('A gravação não produziu transcrição suficiente.');
      v9MeetingStatus='Transcrição concluída. Processando o resumo executivo…';renderV9MeetingDetail();
      await api('/api/meeting/summarize','POST',{projectId:d.projectId,sessionId:d.id,transcript});
      v9MeetingDetail=await api(`/api/meeting/history/${encodeURIComponent(d.id)}`);
      v9MeetingStatus='Resumo processado com sucesso.';renderV9MeetingDetail();
    }catch(e){v9MeetingStatus='Não foi possível processar o resumo: '+e.message;alert(v9MeetingStatus)}
    finally{v9MeetingLoading=false;renderV9MeetingDetail()}
  };

  window.shareV9MeetingPdf=async function(){
    const d=v9MeetingDetail;if(!d?.pdfUrl)return;
    try{
      const r=await fetch(d.pdfUrl);if(!r.ok)throw new Error('Não foi possível abrir o PDF.');
      const blob=await r.blob();
      const file=new File([blob],`resumo_reuniao_${d.projectId}.pdf`,{type:'application/pdf'});
      if(navigator.share&&navigator.canShare&&navigator.canShare({files:[file]})){
        await navigator.share({title:`Resumo da reunião - ${d.projectName}`,files:[file]});
      }else{
        const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);
      }
    }catch(e){alert(e.message)}
  };

  function setupV9Audio(){
    const audio=document.getElementById('v9MeetingAudio'),segments=v9MeetingDetail?.segments||[];if(!audio||!segments.length)return;
    v9AudioIndex=0;audio.src=segments[0].url;
    audio.onended=()=>{if(v9AudioIndex<segments.length-1){v9AudioIndex++;audio.src=segments[v9AudioIndex].url;audio.play().catch(()=>{})}};
  }

  renderProject=function(){
    previousRenderProjectV9();
    const tabs=$('#projectView .tabs');if(!tabs)return;
    if(tabs.querySelector('[data-v9-documents]'))return;
    const roadmap=[...tabs.querySelectorAll('.tab')].find(x=>x.textContent.includes('Roadmap do Sucesso'));
    const btn=document.createElement('button');
    btn.className='tab '+(currentTab==='documents'?'active':'');
    btn.dataset.v9Documents='1';
    btn.textContent='Documentos';
    btn.onclick=()=>projectTab('documents');
    if(roadmap?.nextSibling)tabs.insertBefore(btn,roadmap.nextSibling);else tabs.appendChild(btn);
    if(currentTab==='documents')tabs.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===btn));
  };

  renderProjectPanel=function(){
    if(currentTab==='documents'){renderProjectDocumentsV9();return}
    previousRenderProjectPanelV9();
  };

  function docRow(a,meta){
    return `<div class="project-document-row"><div class="project-document-icon">DOC</div><div class="project-document-main">
      <a class="roadmap-file-link" href="${a.url}">${esc(a.name)}</a>
      <div class="muted small">${esc(meta||'')} ${meta?'· ':''}${v9Size(a.size)} · ${esc(a.uploadedBy||'')} · ${fmtDate(a.createdAt)}</div>
    </div><a class="btn light small" href="${a.url}">Abrir</a></div>`;
  }
  function docSection(title,subtitle,items,kind){
    const rows=items.length?items.map(a=>{
      const meta=kind==='roadmap'?`Roadmap: ${a.milestoneName||'Etapa'}`:kind==='meeting'?`Reunião de ${v9Date(a.meetingDate)}`:'Documento do projeto';
      return docRow(a,meta);
    }).join(''):'<div class="empty compact-empty">Nenhum documento nesta categoria.</div>';
    return `<div class="card project-document-category"><div class="card-h"><div><h3>${title}</h3><div class="muted small">${subtitle}</div></div><span class="pill s-nao">${items.length}</span></div><div class="pad">${rows}</div></div>`;
  }

  function renderProjectDocumentsV9(){
    const p=project(currentProjectId),root=$('#projectPanel');if(!p||!root)return;
    root.innerHTML=`<div class="section-title"><div><h2>Documentos</h2><div class="muted small">Arquivo central do projeto, organizado pela origem de cada documento.</div></div>
      ${canEdit(p.id)?`<div class="flex wrap"><input id="projectDocInput" type="file" class="roadmap-file-input-hidden" onchange="uploadProjectDocumentV9()"><button class="btn blue small" onclick="document.getElementById('projectDocInput').click()">＋ Anexar documento ao projeto</button></div>`:''}</div>
      <div id="projectDocumentsV9"><div class="card empty">Carregando documentos…</div></div>`;
    loadProjectDocumentsV9();
  }

  async function loadProjectDocumentsV9(){
    const box=$('#projectDocumentsV9');if(!box)return;
    try{
      const j=await api(`/api/projects/${encodeURIComponent(currentProjectId)}/documents`);
      box.innerHTML=`<div class="project-documents-grid">
        ${docSection('Documentos do projeto','Arquivos gerais, não vinculados a uma reunião ou etapa específica.',j.project||[],'project')}
        ${docSection('Roadmap do Sucesso','Arquivos anexados diretamente às etapas do Roadmap.',j.roadmap||[],'roadmap')}
        ${docSection('Reuniões','Apresentações e documentos anexados após as reuniões.',j.meetings||[],'meeting')}
      </div>`;
    }catch(e){box.innerHTML=`<div class="card empty">${esc(e.message)}</div>`}
  }

  window.uploadProjectDocumentV9=async function(){
    const input=$('#projectDocInput'),file=input?.files?.[0];if(!file)return;
    if(file.size>20*1024*1024){input.value='';alert('O arquivo excede 20 MB.');return}
    const fd=new FormData();fd.append('file',file);
    try{
      const r=await fetch(`/api/projects/${encodeURIComponent(currentProjectId)}/documents`,{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
      let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.error||'Falha ao anexar documento.');
      input.value='';await loadProjectDocumentsV9();
    }catch(e){alert(e.message)}
  };
})();