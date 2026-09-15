// Transformação KAZ V7 — histórico visível dos registros de andamento dos marcos.
(function(){
  const baseRenderProjectPanel = renderProjectPanel;

  function milestoneMemoMeta(m){
    const ms=(m.memos||[]).slice().sort((a,b)=>String(b.at||'').localeCompare(String(a.at||'')));
    if(!ms.length)return '<span class="muted small">Nenhum registro de andamento</span>';
    const last=ms[0];
    return `<span class="muted small">${ms.length} ${ms.length===1?'registro':'registros'} · último em ${fmtDate(last.at)}</span>`;
  }

  function milestoneHistory(m){
    const ms=(m.memos||[]).slice();
    return `<div style="margin-top:18px;border-top:1px solid #e5eaf0;padding-top:14px">
      <div class="flex wrap" style="align-items:center;margin-bottom:9px">
        <div><b>Histórico do marco</b><div class="muted small">Evoluções, decisões e mudanças de contexto registradas ao longo do tempo.</div></div>
        <span class="right pill s-nao">${ms.length} ${ms.length===1?'registro':'registros'}</span>
      </div>
      ${ms.length?memosCard(ms):'<div class="empty">Nenhum andamento registrado ainda.</div>'}
    </div>`;
  }

  milestonesCard = function(p,editable){
    const ownerStructural=USER.project_id===p.id&&!isDirection&&!p.milestonesLocked;
    return `<div class="card"><div class="pad">${(p.milestones||[]).map((m,i)=>`
      <div class="milestone">
        <div class="m-row">
          <div>
            <div class="m-name">${i+1}. ${esc(m.name)}</div>
            <div class="muted small" style="margin-top:3px">${m.deadline?`Prazo: ${esc(m.deadline)}`:'Sem prazo definido'}</div>
            <div style="margin-top:4px">${milestoneMemoMeta(m)}</div>
          </div>
          <div>${badge(m.status)}</div>
          <div class="small">${esc(m.deadline||'—')}</div>
          <button class="btn light small" onclick="toggleMilestone('${m.id}')">${editable?'Abrir':'Ver'}</button>
        </div>
        <div id="md-${m.id}" class="m-detail hidden">
          ${editable?`
            <div class="form-grid">
              <div class="field full">
                <label>Marco ${ownerStructural?'— pode ser ajustado nesta revisão inicial':'— estrutura preservada'}</label>
                <input id="mn-${m.id}" value="${esc(m.name)}" ${ownerStructural||isDirection?'':'disabled'}>
              </div>
              <div class="field"><label>Status</label><select id="ms-${m.id}">${['Não iniciado','Em andamento','Em risco','Concluído'].map(s=>`<option ${m.status===s?'selected':''}>${s}</option>`).join('')}</select></div>
              <div class="field"><label>Prazo</label><input id="dl-${m.id}" type="date" value="${esc(m.deadline||'')}" ${ownerStructural||isDirection?'':'disabled'}></div>
              <div class="field full"><label>Conclusão / resultado</label><textarea id="co-${m.id}">${esc(m.conclusion||'')}</textarea></div>
              <div class="field full">
                <label>Registrar andamento</label>
                <textarea id="mm-${m.id}" placeholder="Registre evolução, decisão, mudança de contexto ou informação relevante sobre este marco..."></textarea>
                <div class="muted small" style="margin-top:5px">Este registro ficará salvo no histórico do marco e também aparecerá na aba Registros do projeto.</div>
              </div>
            </div>
            <div class="actions"><button class="btn" onclick="saveMilestone('${m.id}')">Salvar andamento</button></div>
            ${milestoneHistory(m)}
          `:`
            ${m.conclusion?`<p><b>Conclusão / resultado:</b> ${esc(m.conclusion)}</p>`:''}
            ${milestoneHistory(m)}
          `}
        </div>
      </div>`).join('')}</div></div>`;
  };

  function consolidatedMilestoneHistory(p){
    const items=[];
    (p.milestones||[]).forEach((m,index)=>{
      (m.memos||[]).forEach(mm=>items.push({
        at:mm.at||'',
        author:mm.author||mm.actor||'Sistema',
        text:mm.text||mm.detail||'',
        milestone:m.name||`Marco ${index+1}`,
        position:index+1
      }));
    });
    items.sort((a,b)=>String(b.at||'').localeCompare(String(a.at||'')));
    if(!items.length)return '<div class="empty">Nenhum andamento de marco registrado ainda.</div>';
    return items.map(x=>`<div class="message">
      <div class="small muted" style="font-weight:800;text-transform:uppercase;margin-bottom:4px">Marco ${x.position} · ${esc(x.milestone)}</div>
      <strong>${esc(x.author)} · ${fmtDate(x.at)}</strong>
      <p>${esc(x.text)}</p>
    </div>`).join('');
  }

  renderProjectPanel = function(){
    baseRenderProjectPanel();
    if(currentTab!=='history')return;
    const p=project(currentProjectId);
    if(!p)return;
    const pad=document.querySelector('#projectPanel .card .pad');
    if(!pad)return;
    const section=document.createElement('div');
    section.innerHTML=`<h4 style="margin-top:0">Histórico dos marcos</h4>
      <div class="info" style="margin-bottom:10px">Aqui ficam reunidos todos os registros de andamento feitos dentro dos marcos, do mais recente para o mais antigo.</div>
      ${consolidatedMilestoneHistory(p)}
      <h4 style="margin-top:22px">Memorandos gerais do projeto</h4>`;

    const firstHeading=pad.querySelector('h4');
    if(firstHeading){
      firstHeading.textContent='Memorandos gerais do projeto';
      pad.insertBefore(section,firstHeading);
      firstHeading.remove();
    }else{
      pad.prepend(section);
    }
  };
})();
