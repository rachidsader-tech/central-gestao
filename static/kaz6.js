// Modo Reunião V2 — gravação integral como fonte principal; ditado deixa de ser a fonte oficial.
let meetingAudioContext=null, meetingAnalyser=null, meetingMeterRAF=null;
let meetingRecordingStart=0, meetingTimerHandle=null, meetingObjectUrl=null;
let meetingProcessing=false, meetingProcessStatus='', meetingDraftRecognition=null;
let meetingAudioAttachment=null;

const _baseRenderMeetingStepV2 = renderMeetingStep;
const _baseChangeMeetingProjectV2 = changeMeetingProject;

function meetingElapsed(){
  if(!meetingRecordingStart)return '00:00';
  const s=Math.max(0,Math.floor((Date.now()-meetingRecordingStart)/1000));
  return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
}
function updateMeetingTimer(){
  const el=document.getElementById('meetingTimer');
  if(el)el.textContent=meetingElapsed();
}
function stopMeetingMeter(){
  if(meetingMeterRAF)cancelAnimationFrame(meetingMeterRAF);
  meetingMeterRAF=null;
}
function runMeetingMeter(){
  if(!meetingAnalyser)return;
  const data=new Uint8Array(meetingAnalyser.fftSize);
  const tick=()=>{
    if(!listening)return stopMeetingMeter();
    meetingAnalyser.getByteTimeDomainData(data);
    let sum=0;
    for(const v of data){const n=(v-128)/128;sum+=n*n}
    const rms=Math.sqrt(sum/data.length);
    const pct=Math.min(100,Math.max(3,Math.round(rms*320)));
    const bar=document.getElementById('meetingLevelBar');
    if(bar)bar.style.width=pct+'%';
    meetingMeterRAF=requestAnimationFrame(tick);
  };
  tick();
}
function meetingStatusHtml(){
  if(meetingProcessing)return '<span class="pill s-analise">Processando gravação…</span>';
  if(listening)return '<span class="pill s-risco">● Gravando</span>';
  if(pendingAudioBlob)return '<span class="pill s-conc">Gravação pronta para processar</span>';
  return '<span class="pill s-nao">Aguardando gravação</span>';
}
function renderMeetingRecorder(){
  return `<div class="card" style="margin:14px 0;border:1px solid #dfe5eb">
    <div class="pad">
      <div class="flex wrap" style="align-items:center">
        <div>
          <div style="font-weight:800;font-size:17px">Gravação da discussão</div>
          <div class="muted small">O áudio completo é a fonte principal. A transcrição é gerada depois da gravação e deve ser revisada antes do registro.</div>
        </div>
        <div class="right">${meetingStatusHtml()}</div>
      </div>
      <div class="micbar" style="margin-top:14px">
        <button class="btn ${listening?'light':'blue'}" onclick="${listening?'stopMeetingRecording()':'startMeetingRecording()'}">
          ${listening?'■ Encerrar gravação':'🎙 Gravar reunião'}
        </button>
        <strong id="meetingTimer">${listening?meetingElapsed():'00:00'}</strong>
        <span class="muted small">${listening?'Captação contínua da sala':'Posicione o computador ou microfone no centro da mesa'}</span>
      </div>
      <div style="height:8px;background:#eef1f4;border-radius:99px;overflow:hidden;margin-top:10px">
        <div id="meetingLevelBar" style="height:100%;width:${listening?'8':'0'}%;background:#20364b;transition:width .08s linear"></div>
      </div>
      <div class="info" style="margin-top:12px">
        <b>Captação otimizada para reunião:</b> cancelamento de eco, redução de ruído, ganho automático e reforço controlado do sinal. Para uma mesa grande, um microfone USB omnidirecional no centro continua sendo a melhor configuração física.
      </div>
      ${pendingAudioBlob?`<div style="margin-top:12px">
        ${meetingObjectUrl?`<audio controls src="${meetingObjectUrl}" style="width:100%"></audio>`:''}
        <div class="actions" style="justify-content:flex-start;margin-top:8px">
          <button class="btn blue" onclick="processMeetingRecording()" ${meetingProcessing?'disabled':''}>${meetingProcessing?'Processando…':'Processar gravação'}</button>
          <button class="btn light" onclick="discardMeetingRecording()" ${meetingProcessing?'disabled':''}>Descartar e gravar novamente</button>
        </div>
        ${meetingProcessStatus?`<div class="small muted" style="margin-top:7px">${esc(meetingProcessStatus)}</div>`:''}
      </div>`:''}
    </div>
  </div>`;
}

renderMeetingStep = function(){
  if(meetingStep!==3)return _baseRenderMeetingStepV2();
  const root=$('#meetingPanel');
  root.innerHTML=`<div class="card meeting-box">
    <h3>3. Andamento da reunião e decisões tomadas</h3>
    <p>Grave a discussão completa deste projeto. Ao encerrar, processe a gravação e revise a transcrição e o resumo antes de avançar.</p>
    ${renderMeetingRecorder()}
    <div class="field">
      <label>Transcrição da gravação — revisar antes de registrar</label>
      <textarea id="meetTranscript" class="transcript" oninput="transcriptText=this.value" placeholder="A transcrição aparecerá aqui após o processamento.">${esc(transcriptText)}</textarea>
    </div>
    <div class="field" style="margin-top:12px">
      <label>Resumo da discussão — revisar e corrigir</label>
      <textarea id="meetSummary" style="min-height:150px">${esc(window.currentMeetingSummary||'')}</textarea>
    </div>
    <div class="field" style="margin-top:12px">
      <label>Decisões tomadas</label>
      <textarea id="meetDecisions" placeholder="Registre apenas decisões efetivamente confirmadas.">${esc(window.currentMeetingDecisions||'')}</textarea>
    </div>
    <div class="field" style="margin-top:12px">
      <label>Pendências / dependências da Diretoria identificadas</label>
      <textarea id="meetDependencies" placeholder="Use como apoio. A pendência oficial deve ser aberta na área de Pendências.">${esc(window.currentMeetingDependencies||'')}</textarea>
    </div>
    <div class="actions">
      <button class="btn light" onclick="goMeetingStep(2)">← Voltar</button>
      <button class="btn blue" onclick="captureMeetingStep3();goMeetingStep(4)" ${listening||meetingProcessing?'disabled':''}>Definir próxima semana →</button>
    </div>
  </div>`;
  if(listening){updateMeetingTimer();runMeetingMeter()}
};

async function startMeetingRecording(){
  if(listening)return;
  try{
    mediaStream=await navigator.mediaDevices.getUserMedia({audio:{
      echoCancellation:true,
      noiseSuppression:true,
      autoGainControl:true,
      channelCount:{ideal:1},
      sampleRate:{ideal:48000}
    }});
    audioChunks=[]; pendingAudioBlob=null; meetingAudioAttachment=null;
    if(meetingObjectUrl){URL.revokeObjectURL(meetingObjectUrl);meetingObjectUrl=null}

    meetingAudioContext=new (window.AudioContext||window.webkitAudioContext)();
    const source=meetingAudioContext.createMediaStreamSource(mediaStream);
    const highpass=meetingAudioContext.createBiquadFilter();
    highpass.type='highpass';highpass.frequency.value=80;
    const gain=meetingAudioContext.createGain();gain.gain.value=1.55;
    const compressor=meetingAudioContext.createDynamicsCompressor();
    compressor.threshold.value=-42;compressor.knee.value=24;compressor.ratio.value=4;compressor.attack.value=.01;compressor.release.value=.25;
    meetingAnalyser=meetingAudioContext.createAnalyser();meetingAnalyser.fftSize=256;
    const dest=meetingAudioContext.createMediaStreamDestination();
    source.connect(highpass);highpass.connect(gain);gain.connect(compressor);compressor.connect(meetingAnalyser);meetingAnalyser.connect(dest);

    const mime=MediaRecorder.isTypeSupported('audio/webm;codecs=opus')?'audio/webm;codecs=opus':'audio/webm';
    mediaRecorder=new MediaRecorder(dest.stream,{mimeType:mime,audioBitsPerSecond:128000});
    mediaRecorder.ondataavailable=e=>{if(e.data&&e.data.size)audioChunks.push(e.data)};
    mediaRecorder.onstop=async()=>{
      pendingAudioBlob=new Blob(audioChunks,{type:mediaRecorder.mimeType||'audio/webm'});
      if(meetingObjectUrl)URL.revokeObjectURL(meetingObjectUrl);
      meetingObjectUrl=URL.createObjectURL(pendingAudioBlob);
      mediaStream?.getTracks().forEach(t=>t.stop());
      try{await meetingAudioContext?.close()}catch{}
      meetingAudioContext=null;meetingAnalyser=null;
      meetingProcessStatus='Gravação concluída. Agora processe o áudio para gerar transcrição e resumo.';
      renderMeetingStep();
    };
    mediaRecorder.start(1000);

    const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(SR){
      meetingDraftRecognition=new SR();
      meetingDraftRecognition.lang='pt-BR';
      meetingDraftRecognition.continuous=true;
      meetingDraftRecognition.interimResults=false;
      meetingDraftRecognition.onresult=e=>{
        for(let i=e.resultIndex;i<e.results.length;i++){
          if(e.results[i].isFinal)transcriptText=(transcriptText+' '+e.results[i][0].transcript).trim();
        }
      };
      meetingDraftRecognition.onerror=()=>{};
      try{meetingDraftRecognition.start()}catch{}
    }
    listening=true;meetingRecordingStart=Date.now();
    meetingTimerHandle=setInterval(updateMeetingTimer,1000);
    meetingProcessStatus='';
    renderMeetingStep();
  }catch(e){
    alert('Não foi possível acessar o microfone. Verifique a permissão do navegador e o dispositivo de entrada selecionado.');
  }
}
function stopMeetingRecording(){
  if(!listening)return;
  listening=false;
  if(meetingTimerHandle)clearInterval(meetingTimerHandle);
  meetingTimerHandle=null;stopMeetingMeter();
  try{meetingDraftRecognition?.stop()}catch{}
  try{mediaRecorder?.stop()}catch{}
  meetingRecordingStart=0;
}
function discardMeetingRecording(){
  if(listening)stopMeetingRecording();
  pendingAudioBlob=null;audioChunks=[];meetingAudioAttachment=null;meetingProcessStatus='';
  if(meetingObjectUrl){URL.revokeObjectURL(meetingObjectUrl);meetingObjectUrl=null}
  transcriptText='';window.currentMeetingSummary='';window.currentMeetingDecisions='';window.currentMeetingDependencies='';
  renderMeetingStep();
}
async function processMeetingRecording(){
  if(!pendingAudioBlob||meetingProcessing)return;
  meetingProcessing=true;meetingProcessStatus='Enviando e analisando a gravação…';renderMeetingStep();
  try{
    const fd=new FormData();
    fd.append('file',pendingAudioBlob,`reuniao_${meetingProjectId}_${todayFile()}.webm`);
    fd.append('project_id',meetingProjectId);
    const r=await fetch('/api/meeting/process',{method:'POST',headers:{'X-CSRF-Token':CSRF},body:fd});
    let j={};try{j=await r.json()}catch{}
    if(!r.ok){
      if(r.status===503){
        meetingProcessStatus='Áudio preservado. O processamento automático ainda não está configurado no servidor; o rascunho auxiliar foi mantido para revisão.';
        if(transcriptText&&!window.currentMeetingSummary)window.currentMeetingSummary=summarizeText(transcriptText);
      }else throw new Error(j.error||'Falha ao processar a gravação.');
    }else{
      transcriptText=j.transcript||transcriptText;
      window.currentMeetingSummary=j.summary||'';
      window.currentMeetingDecisions=j.decisions||'';
      window.currentMeetingDependencies=j.dependencies||'';
      if(j.commitment&&!window.currentMeetingNext)window.currentMeetingNext=j.commitment;
      meetingProcessStatus='Processamento concluído. Revise o conteúdo antes de avançar.';
    }
  }catch(e){
    meetingProcessStatus='Não foi possível processar agora. A gravação continua disponível e será salva ao fechar a reunião.';
    alert(e.message);
  }finally{
    meetingProcessing=false;renderMeetingStep();
  }
}
captureMeetingStep3 = function(){
  window.currentMeetingSummary=$('#meetSummary')?.value||window.currentMeetingSummary||'';
  window.currentMeetingDecisions=$('#meetDecisions')?.value||window.currentMeetingDecisions||'';
  window.currentMeetingDependencies=$('#meetDependencies')?.value||window.currentMeetingDependencies||'';
  transcriptText=$('#meetTranscript')?.value||transcriptText;
};

changeMeetingProject = function(id){
  if(listening)stopMeetingRecording();
  pendingAudioBlob=null;audioChunks=[];meetingAudioAttachment=null;meetingProcessStatus='';
  transcriptText='';window.currentMeetingSummary='';window.currentMeetingDecisions='';window.currentMeetingDependencies='';window.currentMeetingNext='';
  if(meetingObjectUrl){URL.revokeObjectURL(meetingObjectUrl);meetingObjectUrl=null}
  _baseChangeMeetingProjectV2(id);
};
