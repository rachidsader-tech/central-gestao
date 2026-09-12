function renderMeeting(){
  const allowed=isDirection?(state.projects||[]):[project(USER.project_id)].filter(Boolean);
  if(!allowed.length){$('#meetingView').innerHTML='<div class="card empty">Nenhum projeto disponível.</div>';return}
  if(!allowed.some(p=>p.id===meetingProjectId))meetingProjectId=allowed[0].id;
  const p=project(meetingProjectId),c=counts(p);
  $('#meetingView').innerHTML=`
    <div class="hero">
      <div><h1>Modo Reunião</h1><p>Ritual de quarta-feira: revisar o combinado, entender o avanço, decidir e fechar a próxima semana.</p></div>
      <div class="field" style="min-width:260px"><label>Projeto apresentado</label><select id="meetProject" onchange="changeMeetingProject(this.value)">${allowed.map(x=>`<option value="${x.id}" ${x.id===p.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div>
    </div>
    <div class="meeting-shell">
      <div class="meeting-steps">
        ${meetingStepLabel(1,'Resumo do projeto')}
        ${meetingStepLabel(2,'Semana anterior')}
        ${meetingStepLabel(3,'Andamento e decisões')}
        ${meetingStepLabel(4,'Próxima semana')}
      </div>
      <div id="meetingPanel"></div>
    </div>
  `;
  renderMeetingStep()
}
function meetingStepLabel(n,label){return `<div class="meeting-step ${meetingStep===n?'active':''}">${n}. ${label}</div>`}
function changeMeetingProject(id){meetingProjectId=id;meetingStep=1;transcriptText='';pendingAudioBlob=null;renderMeeting()}
function goMeetingStep(n){meetingStep=n;renderMeeting()}
function renderMeetingStep(){
  const p=project(meetingProjectId),root=$('#meetingPanel'),c=counts(p);
  if(meetingStep===1){
    const dps=(state.dependencies||[]).filter(d=>d.projectId===p.id&&d.status!=='Resolvida');
    root.innerHTML=`<div class="card meeting-box"><h3>1. Resumo do projeto</h3><p>Comece contextualizando o objetivo e o estado atual. Esta etapa é informativa.</p>
      <div class="two">
        <div><div class="muted small">OBJETIVO</div><div class="objective" style="margin-top:6px">${esc(p.objective)}</div></div>
        <div>
          <div class="summary-grid" style="grid-template-columns:1fr 1fr">
            <div class="summary-mini"><strong>${c.done}/${c.total}</strong><span>Marcos concluídos</span></div>
            <div class="summary-mini"><strong>${dps.length}</strong><span>Pendências ativas</span></div>
          </div>
          <div>${badge(p.status)}</div>
        </div>
      </div>
      <div class="summary-box" style="margin-top:14px"><div class="smart-text">${esc(smartMilestoneSummary(p))}</div></div>
      <div class="actions"><button class="btn blue" onclick="goMeetingStep(2)">Revisar semana anterior →</button></div>
    </div>`
  }
  if(meetingStep===2){
    root.innerHTML=`<div class="card meeting-box"><h3>2. Pendências e compromissos da semana anterior</h3><p>O foco é Prometido × Realizado. Atualize cada compromisso antes de seguir.</p>
      ${commitmentsCard(p,true,false)}
      <div class="section-title"><h2>Pendências externas abertas</h2></div>
      ${depsCard((state.dependencies||[]).filter(d=>d.projectId===p.id&&d.status!=='Resolvida'))}
      <div class="actions"><button class="btn light" onclick="goMeetingStep(1)">← Voltar</button><button class="btn blue" onclick="goMeetingStep(3)">Andamento da reunião →</button></div>
    </div>`
  }
  if(meetingStep===3){
    root.innerHTML=`<div class="card meeting-box"><h3>3. Andamento da reunião e decisões tomadas</h3><p>O dono do projeto inicia o microfone ao começar sua apresentação. O sistema grava o áudio e, quando o navegador permitir, transcreve a conversa ao vivo. Revise o resumo antes de fechar.</p>
      <div class="micbar">
        <button id="micBtn" class="btn icon" onclick="toggleMic()">🎙 <span id="micBtnText">${listening?'Parar gravação':'Iniciar microfone'}</span></button>
        <span id="micState" class="micstatus">${listening?'Gravando e ouvindo a reunião…':'Microfone desligado'}</span>
        <span id="micWave" class="wave ${listening?'recording':''}"><i></i><i></i><i></i><i></i></span>
      </div>
      <div class="field"><label>Transcrição da conversa — revise livremente</label><textarea id="meetTranscript" class="transcript" oninput="transcriptText=this.value">${esc(transcriptText)}</textarea></div>
      <div class="actions" style="justify-content:flex-start"><button class="btn light" onclick="generateMeetingSummary()">Gerar resumo a partir da transcrição</button></div>
      <div class="field" style="margin-top:12px"><label>Resumo da reunião — revisar antes de registrar</label><textarea id="meetSummary" style="min-height:150px">${esc(window.currentMeetingSummary||'')}</textarea></div>
      <div class="field" style="margin-top:12px"><label>Decisões tomadas</label><textarea id="meetDecisions" placeholder="Decisões efetivamente tomadas pela reunião...">${esc(window.currentMeetingDecisions||'')}</textarea></div>
      <div class="actions"><button class="btn light" onclick="goMeetingStep(2)">← Voltar</button><button class="btn blue" onclick="captureMeetingStep3();goMeetingStep(4)">Definir próxima semana →</button></div>
    </div>`
  }
  if(meetingStep===4){
    root.innerHTML=`<div class="card meeting-box"><h3>4. Próxima semana</h3><p>Feche com resultados claros até a próxima quarta-feira. Não transforme isso em uma lista de microtarefas.</p>
      <div class="field"><label>Resultado / compromisso até a próxima reunião</label><textarea id="meetNext" placeholder="Ex.: Apresentar proposta final da estrutura de carteiras para validação.">${esc(window.currentMeetingNext||'')}</textarea></div>
      <div class="info" style="margin-top:12px">Se existir uma dependência da Diretoria, abra uma pendência externa separada. Assim fica claro quem tem a bola e qual prazo foi combinado.</div>
      <div class="actions"><button class="btn light" onclick="goMeetingStep(3)">← Voltar</button><button class="btn light" onclick="openDependencyModal()">＋ Abrir pendência</button><button class="btn blue" onclick="saveMeeting()">Fechar e registrar reunião</button></div>
    </div>`
  }
}
function captureMeetingStep3(){
  window.currentMeetingSummary=$('#meetSummary')?.value||window.currentMeetingSummary||'';
  window.currentMeetingDecisions=$('#meetDecisions')?.value||window.currentMeetingDecisions||'';
  transcriptText=$('#meetTranscript')?.value||transcriptText
}
function summarizeText(text){
  const clean=(text||'').replace(/\s+/g,' ').trim();
  if(!clean)return '';
  const sentences=clean.split(/(?<=[.!?])\s+/).filter(Boolean);
  const pick=(words)=>sentences.filter(s=>words.some(w=>s.toLowerCase().includes(w))).slice(0,4);
  const evolution=pick(['avanç','feito','conclu','evolu','entreg','andamento']);
  const problems=pick(['problema','risco','trav','atras','dificuldade','não conseguimos','não foi']);
  const decisions=pick(['decid','defin','ficou combinado','aprov','vamos fazer']);
  const pending=pick(['precisa','pend','diretoria','depende','aguard']);
  const commitments=pick(['até quarta','próxima semana','vai entregar','ficou de','compromisso']);
  const fallback=sentences.slice(0,5);
  const section=(title,arr)=>arr.length?`${title}\n${arr.map(x=>'• '+x.trim()).join('\n')}\n\n`:'';
  let out='';
  out+=section('EVOLUÇÃO',evolution);
  out+=section('PONTOS DE ATENÇÃO',problems);
  out+=section('DECISÕES',decisions);
  out+=section('DEPENDÊNCIAS / PENDÊNCIAS',pending);
  out+=section('PRÓXIMOS COMPROMISSOS',commitments);
  if(!out)out=`RESUMO\n${fallback.map(x=>'• '+x.trim()).join('\n')}`;
  return out.trim()
}
function generateMeetingSummary(){
  transcriptText=$('#meetTranscript')?.value||transcriptText;
  const s=summarizeText(transcriptText);
  if(!s){alert('Ainda não há transcrição suficiente para resumir.');return}
  $('#meetSummary').value=s;window.currentMeetingSummary=s
}
async function toggleMic(){if(listening)stopMic();else await startMic()}
async function startMic(){
  try{
    mediaStream=await navigator.mediaDevices.getUserMedia({audio:true});
    audioChunks=[];
    mediaRecorder=new MediaRecorder(mediaStream);
    mediaRecorder.ondataavailable=e=>{if(e.data.size)audioChunks.push(e.data)};
    mediaRecorder.onstop=()=>{pendingAudioBlob=new Blob(audioChunks,{type:mediaRecorder.mimeType||'audio/webm'});mediaStream?.getTracks().forEach(t=>t.stop())};
    mediaRecorder.start();
    const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(SR){
      recognition=new SR();recognition.lang='pt-BR';recognition.continuous=true;recognition.interimResults=true;
      recognition.onresult=e=>{
        let final='',interim='';
        for(let i=e.resultIndex;i<e.results.length;i++){const t=e.results[i][0].transcript;if(e.results[i].isFinal)final+=t+' ';else interim+=t}
        if(final){transcriptText=(transcriptText+' '+final).trim()}
        const ta=$('#meetTranscript');if(ta)ta.value=(transcriptText+(interim?' '+interim:'')).trim()
      };
      recognition.onerror=()=>{};
      try{recognition.start()}catch{}
    }
    listening=true;renderMeetingStep()
  }catch(e){alert('Não foi possível acessar o microfone. Verifique a permissão do navegador.')}
}
function stopMic(){
  try{mediaRecorder?.stop()}catch{}
  try{recognition?.stop()}catch{}
  listening=false;
  const ta=$('#meetTranscript');if(ta)transcriptText=ta.value.trim();
  renderMeetingStep();
  setTimeout(()=>{if(transcriptText){const s=summarizeText(transcriptText);window.currentMeetingSummary=s;const el=$('#meetSummary');if(el&&!el.value)el.value=s}},200)
}
async function uploadMeetingAudio(pid){
  if(!pendingAudioBlob)return null;
  const fd=new FormData();
  fd.append('file',pendingAudioBlob,`reuniao_${pid}_${todayFile()}.webm`);
  fd.append('project_id',pid);
  fd.append('note','Áudio da reunião semanal');
  const r=await fetch('/api/attachments',{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
  const j=await r.json();if(!r.ok)throw new Error(j.error||'Falha ao salvar áudio');
  return j
}
async function saveMeeting(){
  captureMeetingStep3();
  window.currentMeetingNext=$('#meetNext')?.value||window.currentMeetingNext||'';
  if(listening)stopMic();
  try{
    let audio=null;
    if(pendingAudioBlob)audio=await uploadMeetingAudio(meetingProjectId);
    await api('/api/meetings','POST',{
      projectId:meetingProjectId,
      notes:window.currentMeetingSummary||transcriptText,
      decisions:window.currentMeetingDecisions||'',
      nextWeek:window.currentMeetingNext||'',
      transcript:transcriptText,
      summary:window.currentMeetingSummary||'',
      audioAttachmentId:audio?.id||null,
      audioUrl:audio?.url||''
    });
    alert('Reunião registrada com sucesso.');
    pendingAudioBlob=null;transcriptText='';window.currentMeetingSummary='';window.currentMeetingDecisions='';window.currentMeetingNext='';
    meetingStep=1;await refresh();renderMeeting()
  }catch(e){alert(e.message)}
}

function renderHelp(){
  $('#helpView').innerHTML=`
    <div class="hero"><div><h1>Ajuda</h1><p>Manual completo e tutorial rápido para usar o sistema com a lógica correta.</p></div></div>
    <div class="help-grid">
      <div class="card help-card">
        <h3>Manual do Usuário</h3>
        <p class="smart-text">Governança, responsabilidades, marcos, pendências externas, dinâmica das reuniões de quarta-feira e boas práticas.</p>
        <a href="/manual" download class="btn blue" style="display:inline-block;text-decoration:none;margin-top:8px">⇩ Baixar manual completo</a>
      </div>
      <div class="card help-card">
        <h3>Tutorial tela a tela</h3>
        <p class="smart-text">Percorra as telas principais e entenda rapidamente o que deve ser feito em cada uma.</p>
        <button class="btn" onclick="startTutorial()" style="margin-top:8px">▶ Iniciar tutorial</button>
      </div>
    </div>
    <div class="section-title"><h2>Mapa rápido do sistema</h2></div>
    <div class="tutorial-list">
      ${tutorialRows()}
    </div>
  `
}
function tutorialRows(){
  const rows=isDirection?[
    ['Início','Radar executivo dos 7 projetos, marcos, riscos e pendências ativas.'],
    ['Todos os projetos','Abra qualquer projeto para consultar ou alterar seu andamento.'],
    ['Pendências da Diretoria','Caixa de entrada conjunta da Diretoria, preservando um diretor responsável por pendência.'],
    ['Modo Reunião','Conduza o ritual de quarta-feira e registre decisões e compromissos.'],
    ['Configurações','Altere sua própria senha.']
  ]:[
    ['Início','Sua home mostra somente o projeto pelo qual você responde e o que exige atenção agora.'],
    ['Meu projeto','Acompanhe objetivo, status, marcos, compromissos, pendências e histórico.'],
    ['Todos os projetos','Consulte toda a transformação, sem editar áreas de outros responsáveis.'],
    ['Pendências','Peça atuação da Diretoria quando houver uma dependência real.'],
    ['Modo Reunião','Use na quarta-feira para Prometido × Realizado, decisões e próxima semana.'],
    ['Configurações','Altere sua própria senha.']
  ];
  return rows.map((r,i)=>`<div class="tutorial-row"><div class="n">${i+1}</div><div><b>${r[0]}</b><div class="smart-text">${r[1]}</div></div></div>`).join('')
}
let tutorialIndex=0;
function tutorialSteps(){
  return isDirection?[
    {title:'Início — Visão da Transformação',view:'home',text:'Aqui a Diretoria enxerga os sete projetos juntos. Use a tela como radar: situação, evolução dos marcos, riscos e pendências.'},
    {title:'Projetos',view:'projects',text:'Abra qualquer projeto para analisar objetivo, marcos, compromissos e histórico. A Diretoria pode editar todos.'},
    {title:'Pendências da Diretoria',view:'director',text:'Todas as pendências chegam aqui. Existe um único diretor responsável, mas os quatro podem analisar e responder em conjunto.'},
    {title:'Modo Reunião',view:'meeting',text:'Na quarta-feira, selecione o projeto, revise a semana anterior, ligue o microfone durante a apresentação, revise o resumo e feche a próxima semana.'},
    {title:'Configurações',view:'settings',text:'Cada usuário pode alterar a própria senha sem depender do administrador.'},
    {title:'Ajuda',view:'help',text:'O manual completo e este tutorial ficam disponíveis permanentemente nesta área.'}
  ]:[
    {title:'Início — Seu painel',view:'home',text:'Aqui aparece somente o que é seu: 1 projeto, seus marcos, compromissos da semana e pendências com a Diretoria.'},
    {title:'Meu projeto',view:'myproject',text:'Esta é a central da transformação da sua área. A Visão Geral interpreta; a aba Marcos mostra a relação completa.'},
    {title:'Todos os projetos',view:'projects',text:'Você pode acompanhar toda a empresa, mas só altera o projeto pelo qual é responsável.'},
    {title:'Pendências',view:'dependencies',text:'Abra uma pendência apenas quando depender da Diretoria. Escolha um único diretor responsável.'},
    {title:'Modo Reunião',view:'meeting',text:'Na quarta-feira, revise Prometido × Realizado, use o microfone durante sua apresentação e confirme decisões e compromissos.'},
    {title:'Configurações',view:'settings',text:'Altere sua senha individualmente sempre que precisar.'},
    {title:'Ajuda',view:'help',text:'Baixe o manual e reinicie este tutorial sempre que quiser.'}
  ]
}
function startTutorial(){tutorialIndex=0;showTutorialStep()}
function showTutorialStep(){
  const steps=tutorialSteps(),s=steps[tutorialIndex];
  if(s.view==='myproject')openMyProject();else showView(s.view);
  modal(`<div class="tutorial-modal">
    <div class="tutorial-top">Tutorial · ${tutorialIndex+1} de ${steps.length}</div>
    <h2>${esc(s.title)}</h2><p>${esc(s.text)}</p>
    <div class="actions"><button class="btn light" onclick="closeModal()">Pular tutorial</button>${tutorialIndex?'<button class="btn light" onclick="tutorialPrev()">← Anterior</button>':''}<button class="btn blue" onclick="tutorialNext()">${tutorialIndex===steps.length-1?'Concluir':'Próximo →'}</button></div>
  </div>`)
}
function tutorialPrev(){tutorialIndex=Math.max(0,tutorialIndex-1);closeModal();showTutorialStep()}
function tutorialNext(){const steps=tutorialSteps();if(tutorialIndex>=steps.length-1){closeModal();showView('help');return}tutorialIndex++;closeModal();showTutorialStep()}

function renderSettings(){
  const p=USER.project_id?project(USER.project_id):null;
  $('#settingsView').innerHTML=`
    <div class="hero"><div><h1>Configurações</h1><p>Dados da sua conta e alteração individual de senha.</p></div></div>
    <div class="card settings-card">
      <div class="card-h"><h3>Minha conta</h3></div>
      <div class="pad">
        <div class="profile-row"><b>Nome</b><span>${esc(USER.display_name)}</span></div>
        <div class="profile-row"><b>Usuário</b><span>${esc(USER.username)}</span></div>
        <div class="profile-row"><b>Perfil</b><span>${isDirection?'Diretoria':'Responsável de projeto'}</span></div>
        <div class="profile-row"><b>Projeto</b><span>${esc(p?.name||'Visão global')}</span></div>
      </div>
    </div>
    <div class="card settings-card" style="margin-top:14px">
      <div class="card-h"><h3>Alterar senha</h3></div>
      <div class="pad">
        <div class="form-grid">
          <div class="field full"><label>Senha atual</label><input id="pwCurrent" type="password" autocomplete="current-password"></div>
          <div class="field"><label>Nova senha</label><input id="pwNew" type="password" autocomplete="new-password"></div>
          <div class="field"><label>Confirmar nova senha</label><input id="pwConfirm" type="password" autocomplete="new-password"></div>
        </div>
        <div class="small muted" style="margin-top:8px">A nova senha deve ter pelo menos 8 caracteres.</div>
        <div class="actions"><button class="btn blue" onclick="changePassword()">Salvar nova senha</button></div>
      </div>
    </div>
  `
}
async function changePassword(){
  const current=$('#pwCurrent').value,newp=$('#pwNew').value,confirm=$('#pwConfirm').value;
  if(!current||!newp||!confirm){alert('Preencha os três campos.');return}
  try{await api('/api/password','POST',{current_password:current,new_password:newp,confirm_password:confirm});$('#pwCurrent').value='';$('#pwNew').value='';$('#pwConfirm').value='';alert('Senha alterada com sucesso.')}catch(e){alert(e.message)}
}

function modal(html){$('#modalRoot').innerHTML=`<div class="modal-wrap" onclick="if(event.target===this)closeModal()"><div class="modal">${html}</div></div>`}
function closeModal(){$('#modalRoot').innerHTML=''}

function init(){
  $('#avatar').textContent=initials(USER.display_name);
  $('#userName').textContent=USER.display_name;
  $('#userRole').textContent=isDirection?'Diretoria':project(USER.project_id)?.name||USER.role;
  $$('.directionOnly').forEach(x=>x.classList.toggle('hidden',!isDirection));
  $$('.adminOnly').forEach(x=>x.classList.toggle('hidden',USER.role!=='admin'));
  $('#myProjectNav').classList.toggle('hidden',!USER.project_id);
  renderHome()
}
init()
