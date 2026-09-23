// Transformação KAZ — experimento de usabilidade em homologação.
// Este arquivo é carregado apenas na branch ux-staging.
(function(){
  const UX_VIEWER = USER.role === 'viewer';
  let uxDepFilter = 'active';
  let uxTimelineFilter = 'all';
  let uxTimelineFiles = {};

  function uxProjectState(p){
    const c=counts(p);
    if(!c.total)return {label:'Não iniciado',css:'s-nao'};
    if(c.done===c.total)return {label:'Concluído',css:'s-conc'};
    if(c.risk>0)return {label:'Atenção',css:'s-risco'};
    if(c.and>0||c.done>0)return {label:'Em andamento',css:'s-and'};
    return {label:'Não iniciado',css:'s-nao'};
  }
  function uxProjectBadge(p){
    const s=uxProjectState(p);
    return '<span class="pill '+s.css+'">'+esc(s.label)+'</span>';
  }
  function uxProgress(p){
    const c=counts(p),pct=c.total?Math.round((c.done/c.total)*100):0;
    return '<div class="ux-progress"><div style="width:'+pct+'%"></div></div><div class="muted small">'+c.done+' de '+c.total+' concluídos · '+pct+'%</div>';
  }
  function uxScopeDefined(p){return Boolean(p && (p.scopeDefined ?? p.milestonesLocked))}
  function uxCanManageScope(p){return USER.username==='rachid'||USER.project_id===p.id}
  function uxCanAddRoadmap(p){return USER.username==='rachid'||USER.project_id===p.id}
  function uxPrimaryMilestone(p){
    return (p.milestones||[]).find(function(m){return m.status==='Em risco'})
      ||(p.milestones||[]).find(function(m){return m.status==='Em andamento'})
      ||(p.milestones||[]).find(function(m){return m.status==='Não iniciado'})
      ||(p.milestones||[])[0]||null;
  }
  function uxLastRoadmapUpdate(p){
    const dates=[];
    (p.generalMemos||[]).forEach(function(m){if(m.at)dates.push(m.at)});
    (p.milestones||[]).forEach(function(m){
      (m.memos||[]).forEach(function(mm){if(mm.at)dates.push(mm.at)});
      if(m.concludedAt)dates.push(m.concludedAt);
    });
    if(p.lastUpdate)dates.push(p.lastUpdate);
    dates.sort();
    return dates.length?dates[dates.length-1]:'';
  }
  function uxActiveDependencies(p){
    return (state.dependencies||[]).filter(function(d){return d.projectId===p.id&&d.status!=='Resolvida'});
  }
  function uxRoadmapScopeBanner(p){
    const defined=uxScopeDefined(p),manage=uxCanManageScope(p);
    if(defined){
      return '<div class="ux-scope-banner defined"><div><b>Escopo definido</b><span>Nomes e prazos das etapas existentes estão congelados. Status, registros, resultados e arquivos continuam atualizáveis.</span></div>'
        +(USER.username==='rachid'?'<button class="btn light small" onclick="reopenProjectScope()">Reabrir escopo</button>':'')+'</div>';
    }
    return '<div class="ux-scope-banner open"><div><b>Escopo em definição</b><span>Este é o momento de ajustar nomes e prazos. Depois de definir o escopo, somente Rachid poderá reabri-lo.</span></div>'
      +(manage?'<button class="btn blue small" onclick="defineProjectScope()">Definir escopo</button>':'')+'</div>';
  }

  function uxToast(message,type){
    type=type||'success';
    let box=document.getElementById('uxToastBox');
    if(!box){box=document.createElement('div');box.id='uxToastBox';box.className='ux-toast-box';document.body.appendChild(box)}
    const item=document.createElement('div');
    item.className='ux-toast '+type;
    item.textContent=String(message||'');
    box.appendChild(item);
    requestAnimationFrame(function(){item.classList.add('show')});
    setTimeout(function(){item.classList.remove('show');setTimeout(function(){item.remove()},220)},3600);
  }
  window.uxToast=uxToast;
  const nativeAlert=window.alert.bind(window);
  window.alert=function(message){
    const t=String(message||'').toLowerCase();
    const type=(t.includes('erro')||t.includes('falha')||t.includes('não foi possível')||t.includes('excede'))?'error':(t.includes('atenção')?'warning':'success');
    uxToast(message,type);
  };

  function uxSimplifyNavigation(){
    const side=document.querySelector('.side');if(!side)return;
    const home=side.querySelector('[data-nav="home"]');
    const projects=side.querySelector('[data-nav="projects"]');
    const mine=document.getElementById('myProjectNav');
    const deps=side.querySelector('[data-nav="dependencies"]');
    const director=side.querySelector('[data-nav="director"]');
    const meeting=side.querySelector('[data-nav="meeting"]');
    if(director)director.classList.add('hidden');
    if(deps)deps.innerHTML='! Pendências';
    if(meeting)meeting.innerHTML='◫ Reuniões';
    if(isDirection&&mine)mine.classList.add('hidden');
    if(UX_VIEWER&&meeting)meeting.classList.add('hidden');
    if(UX_VIEWER&&mine)mine.classList.add('hidden');
    const anchor=side.querySelector('.nav-section.personal-nav');
    const order=[];
    if(home)order.push(home);
    if(!isDirection&&!UX_VIEWER&&mine)order.push(mine);
    if(projects)order.push(projects);
    if(deps)order.push(deps);
    if(!UX_VIEWER&&meeting)order.push(meeting);
    order.forEach(function(el){if(anchor)side.insertBefore(el,anchor)});
    const mobile=document.querySelector('.mobile-menu');
    if(mobile){mobile.setAttribute('onclick','toggleMobileMenu()');mobile.setAttribute('aria-label','Abrir menu')}
    side.querySelectorAll('.nav-btn').forEach(function(el){el.addEventListener('click',function(){closeMobileMenu()})});
  }

  window.toggleMobileMenu=function(){
    document.body.classList.toggle('mobile-nav-open');
    let overlay=document.getElementById('uxMobileOverlay');
    if(!overlay){overlay=document.createElement('div');overlay.id='uxMobileOverlay';overlay.className='ux-mobile-overlay';overlay.onclick=closeMobileMenu;document.body.appendChild(overlay)}
  };
  window.closeMobileMenu=function(){document.body.classList.remove('mobile-nav-open')};

  projectsCard=function(list){
    if(!list.length)return '<div class="card empty">Nenhum projeto.</div>';
    return '<div class="card ux-project-card"><table class="project-table"><thead><tr><th>Projeto</th><th>Responsável</th><th>Situação</th><th>Roadmap</th><th>Agora</th><th>Pendências</th></tr></thead><tbody>'
      +list.map(function(p){
        const c=counts(p),deps=uxActiveDependencies(p).length,now=uxPrimaryMilestone(p);
        return '<tr class="clickable" onclick="openProject(\''+p.id+'\')"><td><b>'+esc(p.name)+'</b><div class="muted small">'+(uxLastRoadmapUpdate(p)?'Atualizado '+fmtDate(uxLastRoadmapUpdate(p)):'Sem atualização')+'</div></td><td>'+esc(p.owner)+'</td><td>'+uxProjectBadge(p)+'</td><td><b>'+c.done+'/'+c.total+'</b><div class="ux-progress mini"><div style="width:'+(c.total?Math.round(c.done/c.total*100):0)+'%"></div></div></td><td class="ux-now-cell">'+(now?esc(now.name):'—')+'</td><td>'+deps+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  };

  renderProjects=function(){
    let text='Consulte toda a transformação. A edição permanece restrita ao projeto pelo qual você responde.';
    if(isDirection)text='Visão consolidada dos projetos, com a situação calculada diretamente pelo Roadmap do Sucesso.';
    if(UX_VIEWER)text='Visão completa da Transformação KAZ em modo somente leitura.';
    document.getElementById('projectsView').innerHTML='<div class="hero"><div><h1>Todos os projetos</h1><p>'+text+'</p></div></div>'+projectsCard(state.projects||[]);
  };

  renderHome=function(){
    const root=document.getElementById('homeView');
    const all=state.projects||[];
    if(isDirection||UX_VIEWER){
      const openDeps=(state.dependencies||[]).filter(function(d){return d.status!=='Resolvida'}).length;
      const attention=all.slice().sort(function(a,b){
        const ar=counts(a).risk*10+uxActiveDependencies(a).length;
        const br=counts(b).risk*10+uxActiveDependencies(b).length;
        return br-ar;
      });
      const critical=attention.filter(function(p){return counts(p).risk>0||uxActiveDependencies(p).length>0});
      root.innerHTML='<div class="hero"><div><h1>O que exige atenção agora</h1><p>Leitura executiva baseada no Roadmap do Sucesso e nas dependências abertas.</p></div>'+(UX_VIEWER?'<span class="pill s-nao">Somente leitura</span>':'')+'</div>'
        +'<div class="grid-kpi"><div class="kpi"><strong>'+all.length+'</strong><span>Projetos</span></div><div class="kpi"><strong>'+all.reduce(function(a,p){return a+counts(p).risk},0)+'</strong><span>Etapas em risco</span></div><div class="kpi"><strong>'+openDeps+'</strong><span>Pendências ativas</span></div><div class="kpi"><strong>'+all.reduce(function(a,p){return a+counts(p).done},0)+'</strong><span>Etapas concluídas</span></div></div>'
        +'<div class="section-title"><h2>Atenções</h2></div>'
        +(critical.length?'<div class="ux-attention-grid">'+critical.slice(0,6).map(function(p){
          const now=uxPrimaryMilestone(p),depCount=uxActiveDependencies(p).length;
          return '<button class="ux-attention-card" onclick="openProject(\''+p.id+'\')"><div class="flex wrap"><b>'+esc(p.name)+'</b><span class="right">'+uxProjectBadge(p)+'</span></div><div class="ux-attention-main">'+(now?esc(now.name):'Roadmap sem etapa ativa')+'</div><div class="muted small">'+counts(p).risk+' em risco · '+depCount+' pendência(s) ativa(s)</div></button>';
        }).join('')+'</div>':'<div class="good">Nenhum projeto exige atenção crítica neste momento.</div>')
        +'<div class="section-title"><h2>Visão completa</h2><button class="btn light small" onclick="showView(\'projects\')">Abrir todos</button></div>'+projectsCard(all);
      return;
    }

    const p=project(USER.project_id);
    if(!p){root.innerHTML='<div class="card empty">Você não está alocado a um projeto.</div>';return}
    const c=counts(p),now=uxPrimaryMilestone(p),deps=uxActiveDependencies(p),commit=typeof latestStrategicCommitment==='function'?latestStrategicCommitment(p):null;
    root.innerHTML='<div class="hero"><div><h1>'+esc(USER.display_name.split(' ')[0])+', aqui está o seu projeto hoje</h1><p>O painel destaca somente o que ajuda a entender o momento da transformação.</p></div>'+uxProjectBadge(p)+'</div>'
      +'<div class="card ux-focus-card clickable" onclick="openProject(\''+p.id+'\')"><div><div class="muted small ux-eyebrow">MEU PROJETO</div><h2>'+esc(p.name)+'</h2><div class="muted small">Responsável: '+esc(p.owner)+' · '+c.done+' de '+c.total+' etapas concluídas</div><div style="margin-top:12px">'+uxProgress(p)+'</div></div><div class="ux-focus-side"><span class="btn light small">Abrir projeto →</span></div></div>'
      +'<div class="ux-home-actions">'
      +'<div class="card pad"><div class="ux-eyebrow">AGORA</div><h3>'+(now?esc(now.name):'Roadmap concluído')+'</h3><div class="muted small">'+(now?badge(now.status)+' '+(now.deadline?'· prazo '+esc(now.deadline):''):'Nenhuma etapa pendente')+'</div></div>'
      +'<div class="card pad clickable" onclick="showView(\'dependencies\')"><div class="ux-eyebrow">DEPENDÊNCIAS</div><h3>'+deps.length+' pendência(s) ativa(s)</h3><div class="muted small">'+(deps[0]?esc(deps[0].subject):'Nada aguardando Diretoria')+'</div></div>'
      +'<div class="card pad"><div class="ux-eyebrow">ATÉ A PRÓXIMA REUNIÃO</div><h3>'+(commit?esc(commit.text):'Nenhum compromisso registrado')+'</h3><div class="muted small">'+(commit?'Compromisso estratégico, não tarefa operacional.':'Será definido no fechamento da reunião.')+'</div></div>'
      +'</div>'
      +'<div class="section-title"><h2>Leitura do Roadmap</h2><button class="btn light small" onclick="openProject(\''+p.id+'\',\'milestones\')">Abrir Roadmap</button></div>'
      +'<div class="card pad"><div class="smart-text">'+esc(smartMilestoneSummary(p))+'</div><div class="muted small" style="margin-top:9px">Última atualização: '+(uxLastRoadmapUpdate(p)?fmtDate(uxLastRoadmapUpdate(p)):'—')+'</div></div>';
  };

  function uxAttachmentBox(m,editable){
    return '<div class="roadmap-files"><div class="flex wrap"><div><b>Arquivos anexados</b><div class="muted small">Documentos e evidências desta etapa.</div></div></div>'
      +'<div id="roadmap-files-'+m.id+'" class="roadmap-file-list"><div class="muted small">Carregando arquivos…</div></div>'
      +(editable?'<div class="flex wrap" style="margin-top:10px"><input type="file" id="roadmap-file-input-'+m.id+'" class="roadmap-file-input-hidden" onchange="uploadRoadmapAttachment(\''+m.id+'\')"><button type="button" class="btn light small" onclick="chooseRoadmapAttachment(\''+m.id+'\')">＋ Anexar arquivo</button><span id="roadmap-file-status-'+m.id+'" class="muted small">Clique para escolher um arquivo.</span></div>':'')
      +'</div>';
  }
  function uxMilestoneHistory(m){
    const ms=(m.memos||[]).slice();
    return '<div class="roadmap-history"><div class="flex wrap"><div><b>Histórico desta etapa</b><div class="muted small">Evoluções, decisões e mudanças de contexto.</div></div><span class="right pill s-nao">'+ms.length+' registro(s)</span></div>'
      +(ms.length?memosCard(ms):'<div class="empty">Nenhum andamento registrado ainda.</div>')+'</div>';
  }
  milestonesCard=function(p,editable){
    const structureOpen=!uxScopeDefined(p);
    const items=p.milestones||[];
    return '<div class="ux-roadmap">'+items.map(function(m,i){
      const memos=(m.memos||[]).slice().sort(function(a,b){return String(b.at||'').localeCompare(String(a.at||''))});
      const last=memos[0];
      return '<div class="ux-roadmap-item status-'+String(m.status||'').toLowerCase().replace(/[^a-z0-9]+/g,'-')+'">'
        +'<div class="ux-roadmap-rail"><span>'+String(i+1)+'</span>'+(i<items.length-1?'<i></i>':'')+'</div>'
        +'<div class="ux-roadmap-body"><div class="ux-roadmap-head"><div class="ux-roadmap-title"><b>'+esc(m.name)+'</b><div class="ux-roadmap-meta">'+badge(m.status)+'<span>'+(m.deadline?'Prazo '+esc(m.deadline):'Sem prazo')+'</span><span>'+memos.length+' registro(s)</span><span id="ux-files-'+m.id+'">… arquivos</span>'+(last?'<span>Atualizado '+fmtDate(last.at)+'</span>':'')+'</div></div><button class="btn light small" onclick="toggleMilestone(\''+m.id+'\')">'+(editable?'Abrir':'Ver')+'</button></div>'
        +'<div id="md-'+m.id+'" class="m-detail hidden">'
        +(editable?'<div class="form-grid"><div class="field full"><label>Etapa do Roadmap '+(structureOpen?'— estrutura editável':'— estrutura definida')+'</label><input id="mn-'+m.id+'" value="'+esc(m.name)+'" '+(structureOpen?'':'disabled')+'></div><div class="field"><label>Status</label><select id="ms-'+m.id+'">'+['Não iniciado','Em andamento','Em risco','Concluído'].map(function(s){return '<option '+(m.status===s?'selected':'')+'>'+s+'</option>'}).join('')+'</select></div><div class="field"><label>Prazo</label><input id="dl-'+m.id+'" type="date" value="'+esc(m.deadline||'')+'" '+(structureOpen?'':'disabled')+'></div><div class="field full"><label>Conclusão / resultado</label><textarea id="co-'+m.id+'">'+esc(m.conclusion||'')+'</textarea></div><div class="field full"><label>Registrar andamento</label><textarea id="mm-'+m.id+'" placeholder="Registre evolução, decisão, mudança de contexto ou informação relevante..."></textarea><div class="muted small" style="margin-top:5px">O registro ficará no histórico desta etapa e na linha do tempo do projeto.</div></div></div><div class="actions"><button id="ux-save-'+m.id+'" class="btn" onclick="saveMilestone(\''+m.id+'\')">Salvar andamento</button></div>':(m.conclusion?'<p><b>Conclusão / resultado:</b> '+esc(m.conclusion)+'</p>':''))
        +uxAttachmentBox(m,editable)+uxMilestoneHistory(m)+'</div></div></div>';
    }).join('')+'</div>';
  };

  async function uxLoadRoadmapCounts(p){
    for(const m of (p.milestones||[])){
      const el=document.getElementById('ux-files-'+m.id);if(!el)continue;
      try{
        const r=await fetch('/api/projects/'+encodeURIComponent(p.id)+'/milestones/'+encodeURIComponent(m.id)+'/attachments',{headers:{'X-CSRF-Token':CSRF}});
        const j=await r.json();
        el.textContent=((j.attachments||[]).length)+' arquivo(s)';
      }catch{el.textContent='arquivos indisponíveis'}
    }
  }

  saveMilestone=async function(id){
    const btn=document.getElementById('ux-save-'+id);
    const original=btn?btn.textContent:'';
    if(btn){btn.disabled=true;btn.textContent='Salvando…'}
    try{
      const p=project(currentProjectId),structureOpen=!uxScopeDefined(p);
      await api('/api/projects/'+p.id,'POST',{
        action:'milestone',milestoneId:id,
        name:structureOpen?document.getElementById('mn-'+id)?.value:undefined,
        status:document.getElementById('ms-'+id)?.value,
        deadline:structureOpen?document.getElementById('dl-'+id)?.value:undefined,
        conclusion:document.getElementById('co-'+id)?.value||'',
        memo:document.getElementById('mm-'+id)?.value||''
      });
      await refresh();currentTab='milestones';renderProject();uxToast('Andamento registrado com sucesso.','success');
    }catch(e){uxToast(e.message,'error');if(btn){btn.disabled=false;btn.textContent=original}}
  };

  function uxStatusCard(p){
    const c=counts(p),now=uxPrimaryMilestone(p);
    return '<div class="card"><div class="card-h"><h3>Situação do projeto</h3>'+uxProjectBadge(p)+'</div><div class="pad"><div class="muted small">Calculada automaticamente pelo Roadmap do Sucesso. Não existe um segundo status manual para manter.</div><div style="margin-top:14px">'+uxProgress(p)+'</div><div class="ux-status-grid"><div><span>Concluídas</span><b>'+c.done+'</b></div><div><span>Em andamento</span><b>'+c.and+'</b></div><div><span>Em risco</span><b>'+c.risk+'</b></div><div><span>Não iniciadas</span><b>'+c.not+'</b></div></div>'+(now?'<div class="info" style="margin-top:12px"><b>Próximo foco:</b> '+esc(now.name)+'</div>':'')+'</div></div>';
  }

  renderProject=function(){
    const p=project(currentProjectId);if(!p)return;
    if(currentTab==='commitments')currentTab='overview';
    const c=counts(p),editable=canEdit(p.id),dps=(state.dependencies||[]).filter(function(d){return d.projectId===p.id});
    document.getElementById('projectView').innerHTML='<button class="btn light small" onclick="showView(\'projects\')">← Todos os projetos</button>'
      +'<div class="detail-head ux-project-head" style="margin-top:15px"><div><div class="muted small ux-eyebrow">PROJETO DE TRANSFORMAÇÃO</div><h1>'+esc(p.name)+'</h1><div class="muted small">Responsável: <b>'+esc(p.owner)+'</b> · '+(editable?'Edição habilitada':'Modo consulta')+'</div></div><div class="flex wrap">'+uxProjectBadge(p)+'<span class="pill '+(uxScopeDefined(p)?'s-conc':'s-analise')+'">'+(uxScopeDefined(p)?'Escopo definido':'Escopo em definição')+'</span>'+(UX_VIEWER?'<span class="pill s-nao">Somente leitura</span>':'')+'</div></div>'
      +uxRoadmapScopeBanner(p)
      +'<div class="tabs"><button class="tab '+(currentTab==='overview'?'active':'')+'" onclick="projectTab(\'overview\')">Visão geral</button><button class="tab '+(currentTab==='milestones'?'active':'')+'" onclick="projectTab(\'milestones\')">Roadmap do Sucesso ('+c.total+')</button><button class="tab '+(currentTab==='dependencies'?'active':'')+'" onclick="projectTab(\'dependencies\')">Pendências ('+dps.filter(function(d){return d.status!=='Resolvida'}).length+')</button><button class="tab '+(currentTab==='history'?'active':'')+'" onclick="projectTab(\'history\')">Registros</button></div><div id="projectPanel"></div>';
    renderProjectPanel();
  };

  function uxTimelineItems(p){
    const items=[];
    (p.generalMemos||[]).forEach(function(m){items.push({at:m.at||'',type:'roadmap',label:'Projeto',title:'Registro geral',text:m.text||'',author:m.author||''})});
    (p.milestones||[]).forEach(function(m,index){
      (m.memos||[]).forEach(function(mm){items.push({at:mm.at||'',type:'roadmap',label:'Roadmap',title:(index+1)+'. '+m.name,text:mm.text||'',author:mm.author||''})});
      if(m.concludedAt)items.push({at:m.concludedAt,type:'roadmap',label:'Roadmap',title:(index+1)+'. '+m.name,text:'Etapa concluída'+(m.conclusion?': '+m.conclusion:''),author:''});
      (uxTimelineFiles[m.id]||[]).forEach(function(f){items.push({at:f.createdAt||'',type:'files',label:'Arquivo',title:f.name||'Arquivo anexado',text:'Anexado à etapa '+m.name,author:f.uploadedBy||''})});
    });
    (state.meetings||[]).filter(function(m){return m.projectId===p.id}).forEach(function(m){items.push({at:m.at||'',type:'meetings',label:'Reunião',title:'Reunião registrada',text:m.summary||m.notes||'Reunião registrada no sistema.',author:m.createdBy||''})});
    (state.dependencies||[]).filter(function(d){return d.projectId===p.id}).forEach(function(d){
      (d.history||[]).forEach(function(h){items.push({at:h.at||'',type:'dependencies',label:'Pendência',title:d.subject||'Pendência',text:(h.action||'')+(h.detail?' · '+h.detail:''),author:h.actor||''})});
    });
    items.sort(function(a,b){return String(b.at||'').localeCompare(String(a.at||''))});
    return items;
  }
  function uxRenderTimeline(p){
    const host=document.getElementById('uxTimeline');if(!host)return;
    const items=uxTimelineItems(p).filter(function(x){return uxTimelineFilter==='all'||x.type===uxTimelineFilter});
    host.innerHTML=items.length?items.map(function(x){
      return '<div class="ux-timeline-item"><div class="ux-timeline-dot '+x.type+'"></div><div><div class="flex wrap"><span class="ux-timeline-label">'+esc(x.label)+'</span><strong>'+esc(x.title)+'</strong><span class="right muted small">'+fmtDate(x.at)+'</span></div><div class="ux-timeline-text">'+esc(x.text).replace(/\n/g,'<br>')+'</div>'+(x.author?'<div class="muted small">'+esc(x.author)+'</div>':'')+'</div></div>';
    }).join(''):'<div class="empty">Nenhum registro neste filtro.</div>';
  }
  window.setUxTimelineFilter=function(filter){
    uxTimelineFilter=filter;
    document.querySelectorAll('[data-ux-timeline]').forEach(function(b){b.classList.toggle('active',b.dataset.uxTimeline===filter)});
    const p=project(currentProjectId);if(p)uxRenderTimeline(p);
  };
  async function uxLoadTimelineFiles(p){
    uxTimelineFiles={};
    for(const m of (p.milestones||[])){
      try{
        const r=await fetch('/api/projects/'+encodeURIComponent(p.id)+'/milestones/'+encodeURIComponent(m.id)+'/attachments',{headers:{'X-CSRF-Token':CSRF}});
        const j=await r.json();uxTimelineFiles[m.id]=j.attachments||[];
      }catch{uxTimelineFiles[m.id]=[]}
    }
    if(currentTab==='history'&&currentProjectId===p.id)uxRenderTimeline(p);
  }

  renderProjectPanel=function(){
    const p=project(currentProjectId),editable=canEdit(p.id),root=document.getElementById('projectPanel'),defined=uxScopeDefined(p);
    if(currentTab==='overview'){
      const c=counts(p),deps=uxActiveDependencies(p),commit=typeof latestStrategicCommitment==='function'?latestStrategicCommitment(p):null;
      root.innerHTML='<div class="two"><div class="card"><div class="card-h"><h3>Objetivo do projeto</h3>'+(editable?'<button class="btn light small" onclick="editObjective()">Editar</button>':'')+'</div><div class="pad objective">'+esc(p.objective)+'</div></div>'+uxStatusCard(p)+'</div>'
        +'<div class="ux-overview-grid"><div class="card pad"><div class="ux-eyebrow">COMPROMISSO ESTRATÉGICO</div><div class="smart-text">'+(commit?esc(commit.text):'Nenhum compromisso registrado na última reunião.')+'</div></div><div class="card pad clickable" onclick="projectTab(\'dependencies\')"><div class="ux-eyebrow">DEPENDÊNCIAS</div><div class="smart-text">'+deps.length+' pendência(s) ativa(s)</div><div class="muted small">'+(deps[0]?esc(deps[0].subject):'Nada aguardando Diretoria')+'</div></div></div>'
        +'<div class="section-title"><h2>Roadmap do Sucesso</h2><button class="btn light small" onclick="projectTab(\'milestones\')">Abrir Roadmap →</button></div><div class="card pad"><div class="smart-text">'+esc(smartMilestoneSummary(p))+'</div><div style="margin-top:12px">'+uxProgress(p)+'</div></div>'
        +'<div class="section-title"><h2>Registro geral do projeto</h2></div><div class="card"><div class="pad">'+memosCard(p.generalMemos)+(editable?'<div class="flex" style="margin-top:10px"><input id="generalMemo" placeholder="Registrar evolução do projeto..." style="flex:1;border:1px solid #d6dde5;border-radius:8px;padding:9px"><button class="btn" onclick="addGeneralMemo()">Registrar</button></div>':'')+'</div></div>';
      return;
    }
    if(currentTab==='milestones'){
      root.innerHTML='<div class="section-title"><div><h2>Roadmap do Sucesso</h2><div class="muted small">A sequência dos resultados que demonstra que a transformação está avançando.</div></div>'+(editable&&uxCanAddRoadmap(p)?'<button class="btn blue small" onclick="openNewRoadmapItem()">＋ Novo item</button>':'')+'</div>'
        +'<div style="margin-top:12px">'+milestonesCard(p,editable)+'</div>';
      setTimeout(function(){uxLoadRoadmapCounts(p)},0);
      return;
    }
    if(currentTab==='dependencies'){
      const list=(state.dependencies||[]).filter(function(d){return d.projectId===p.id});
      root.innerHTML='<div class="section-title"><h2>Pendências externas</h2>'+(editable?'<button class="btn blue" onclick="openDependencyModal()">＋ Nova pendência</button>':'')+'</div><div class="info" style="margin-bottom:12px">Use uma pendência somente quando o projeto depender de atuação real da Diretoria.</div>'+depsCard(list);
      return;
    }
    if(currentTab==='history'){
      uxTimelineFilter='all';
      root.innerHTML='<div class="section-title"><div><h2>Linha do tempo do projeto</h2><div class="muted small">Roadmap, reuniões, pendências e arquivos reunidos em uma única memória.</div></div></div>'
        +'<div class="ux-filter-tabs"><button class="active" data-ux-timeline="all" onclick="setUxTimelineFilter(\'all\')">Tudo</button><button data-ux-timeline="roadmap" onclick="setUxTimelineFilter(\'roadmap\')">Roadmap</button><button data-ux-timeline="meetings" onclick="setUxTimelineFilter(\'meetings\')">Reuniões</button><button data-ux-timeline="dependencies" onclick="setUxTimelineFilter(\'dependencies\')">Pendências</button><button data-ux-timeline="files" onclick="setUxTimelineFilter(\'files\')">Arquivos</button></div><div class="card"><div class="pad" id="uxTimeline"></div></div>';
      uxRenderTimeline(p);uxLoadTimelineFiles(p);return;
    }
  };

  function uxDependencyList(){
    const all=(isDirection||UX_VIEWER)?(state.dependencies||[]):(state.dependencies||[]).filter(function(d){return d.projectId===USER.project_id});
    if(uxDepFilter==='resolved')return all.filter(function(d){return d.status==='Resolvida'});
    if(uxDepFilter==='mine'){
      if(isDirection)return all.filter(function(d){return d.status!=='Resolvida'&&String(d.director||'').toLowerCase().includes(String(USER.display_name||'').split(' ')[0].toLowerCase())});
      return all.filter(function(d){return d.status!=='Resolvida'});
    }
    if(uxDepFilter==='all')return all;
    return all.filter(function(d){return d.status!=='Resolvida'});
  }
  window.setUxDependencyFilter=function(filter){uxDepFilter=filter;renderDependencies()};
  renderDependencies=function(){
    const list=uxDependencyList();
    const tabs='<div class="ux-filter-tabs"><button '+(uxDepFilter==='active'?'class="active"':'')+' onclick="setUxDependencyFilter(\'active\')">Ativas</button>'+(isDirection?'<button '+(uxDepFilter==='mine'?'class="active"':'')+' onclick="setUxDependencyFilter(\'mine\')">Comigo</button>':'')+'<button '+(uxDepFilter==='resolved'?'class="active"':'')+' onclick="setUxDependencyFilter(\'resolved\')">Resolvidas</button><button '+(uxDepFilter==='all'?'class="active"':'')+' onclick="setUxDependencyFilter(\'all\')">Todas</button></div>';
    let desc=isDirection?'Uma única caixa de entrada para a Diretoria. Cada pendência continua tendo um diretor responsável.':'Pendências externas do seu projeto.';
    if(UX_VIEWER)desc='Pendências da Transformação KAZ em modo somente leitura.';
    document.getElementById('dependenciesView').innerHTML='<div class="hero"><div><h1>Pendências</h1><p>'+desc+'</p></div>'+(!UX_VIEWER&&USER.project_id?'<button class="btn blue" onclick="openDependencyModal()">＋ Nova pendência</button>':'')+'</div>'+tabs+depsCard(list);
  };

  function uxImproveMeetingArchive(){
    const root=document.getElementById('meetingView');if(!root)return;
    const sections=[...root.querySelectorAll('.meeting-archive-section')];
    if(!sections.length)return;
    const summary=sections.find(function(s){return s.querySelector('.archive-step-number')?.textContent.trim()==='4'});
    const audio=sections.find(function(s){return s.querySelector('.archive-step-number')?.textContent.trim()==='3'});
    if(summary&&!summary.dataset.uxMoved){
      summary.dataset.uxMoved='1';summary.classList.add('ux-meeting-summary-first');
      const n=summary.querySelector('.archive-step-number');if(n)n.textContent='✓';
      const h=summary.querySelector('h2');if(h)h.textContent='Resumo executivo e próximos passos';
      root.insertBefore(summary,sections[0]);
    }
    if(audio&&!audio.dataset.uxCollapsed){
      audio.dataset.uxCollapsed='1';
      const body=audio.querySelector('.archive-step-body');
      const card=body?.querySelector('.card');
      if(body&&card){
        const details=document.createElement('details');details.className='ux-meeting-secondary';
        const sum=document.createElement('summary');sum.textContent='Ouvir gravação e consultar transcrição';
        details.appendChild(sum);details.appendChild(card);body.appendChild(details);
        const h=body.querySelector('h2');if(h)h.textContent='Áudio e transcrição';
      }
    }
  }
  const meetingObserver=new MutationObserver(function(){uxImproveMeetingArchive()});
  const meetingRoot=document.getElementById('meetingView');
  if(meetingRoot)meetingObserver.observe(meetingRoot,{childList:true,subtree:true});

  const css=document.createElement('style');
  css.textContent=
    '.ux-progress{height:7px;background:#edf1f5;border-radius:99px;overflow:hidden;margin-bottom:6px}.ux-progress>div{height:100%;background:#245fce;border-radius:99px}.ux-progress.mini{width:100px;height:5px;margin-top:5px}.ux-eyebrow{font-size:9px;font-weight:900;letter-spacing:.1em;color:#8a96a3}.ux-focus-card{padding:20px;display:flex;align-items:center;justify-content:space-between;gap:18px}.ux-focus-card h2{margin:4px 0 6px}.ux-home-actions,.ux-overview-grid,.ux-attention-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:14px 0}.ux-home-actions h3{font-size:14px;margin:7px 0}.ux-overview-grid{grid-template-columns:1fr 1fr}.ux-attention-card{border:1px solid var(--line);border-radius:13px;background:#fff;padding:15px;text-align:left;color:inherit;box-shadow:var(--shadow)}.ux-attention-main{font-size:12px;font-weight:750;line-height:1.4;margin:10px 0}.ux-scope-banner{display:flex;justify-content:space-between;gap:14px;align-items:center;border-radius:11px;padding:11px 13px;margin:12px 0}.ux-scope-banner div{display:grid;gap:3px}.ux-scope-banner span{font-size:11px}.ux-scope-banner.open{background:#fff8e3;border:1px solid #eedca0;color:#655615}.ux-scope-banner.defined{background:#ecfdf5;border:1px solid #c9f1df;color:#176247}.ux-status-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}.ux-status-grid div{background:#f7f9fb;border-radius:9px;padding:9px}.ux-status-grid span{display:block;font-size:9px;color:var(--muted)}.ux-status-grid b{font-size:17px}.ux-roadmap{display:grid;gap:0}.ux-roadmap-item{display:grid;grid-template-columns:44px minmax(0,1fr)}.ux-roadmap-rail{display:flex;flex-direction:column;align-items:center}.ux-roadmap-rail span{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:#eef3f8;color:#24405d;font-weight:900;font-size:11px;border:2px solid #fff;box-shadow:0 0 0 1px #dfe5ec}.ux-roadmap-rail i{width:2px;background:#dfe5ec;flex:1;min-height:32px}.ux-roadmap-body{border:1px solid var(--line);border-radius:12px;background:#fff;margin-bottom:10px;overflow:hidden}.ux-roadmap-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 14px}.ux-roadmap-title>b{font-size:13px}.ux-roadmap-meta{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:7px}.ux-roadmap-meta span:not(.pill){font-size:10px;color:var(--muted)}.ux-roadmap-body .m-detail{border-top:1px solid var(--line);padding:15px}.ux-filter-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px}.ux-filter-tabs button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:7px 11px;font-size:10px;font-weight:800;color:#53606d}.ux-filter-tabs button.active{background:#173b6d;color:#fff;border-color:#173b6d}.ux-timeline-item{display:grid;grid-template-columns:14px minmax(0,1fr);gap:11px;padding:13px 0;border-bottom:1px solid #edf0f3}.ux-timeline-item:last-child{border-bottom:0}.ux-timeline-dot{width:9px;height:9px;border-radius:50%;background:#94a3b8;margin-top:5px}.ux-timeline-dot.roadmap{background:#245fce}.ux-timeline-dot.meetings{background:#14785b}.ux-timeline-dot.dependencies{background:#a96d16}.ux-timeline-dot.files{background:#7c3aed}.ux-timeline-label{font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.06em;color:#738194}.ux-timeline-text{font-size:12px;line-height:1.5;margin:6px 0}.ux-toast-box{position:fixed;right:18px;bottom:18px;z-index:900;display:grid;gap:8px;max-width:min(390px,calc(100vw - 36px))}.ux-toast{opacity:0;transform:translateY(8px);transition:.2s;background:#17283b;color:#fff;border-radius:10px;padding:11px 13px;font-size:11px;box-shadow:0 12px 35px rgba(0,0,0,.18)}.ux-toast.show{opacity:1;transform:none}.ux-toast.error{background:#9f2934}.ux-toast.warning{background:#8a651c}.ux-meeting-summary-first{background:#f7fbff;border:1px solid #dcecff;border-radius:14px;padding:14px}.ux-meeting-secondary{margin-top:10px}.ux-meeting-secondary>summary{cursor:pointer;font-size:12px;font-weight:800;color:#31475f;padding:9px 0}.ux-now-cell{max-width:300px}.ux-mobile-overlay{display:none}'
    +'@media(max-width:960px){.ux-home-actions,.ux-overview-grid,.ux-attention-grid{grid-template-columns:1fr}.ux-status-grid{grid-template-columns:1fr 1fr}.ux-focus-card{align-items:flex-start;flex-direction:column}.side{display:block!important;position:fixed!important;left:0;top:29px!important;height:calc(100vh - 29px)!important;width:270px;z-index:600;transform:translateX(-105%);transition:transform .2s ease;box-shadow:10px 0 35px rgba(0,0,0,.16)}body.mobile-nav-open .side{transform:translateX(0)}.ux-mobile-overlay{display:block;position:fixed;inset:29px 0 0;background:rgba(15,29,45,.35);z-index:590;opacity:0;pointer-events:none;transition:.2s}body.mobile-nav-open .ux-mobile-overlay{opacity:1;pointer-events:auto}.ux-roadmap-item{grid-template-columns:36px minmax(0,1fr)}.ux-roadmap-head{align-items:flex-start}.ux-project-card .project-table th:nth-child(5),.ux-project-card .project-table td:nth-child(5){min-width:230px}.userbox>div:last-child{display:none}}';
  document.head.appendChild(css);

  uxSimplifyNavigation();
  setTimeout(function(){renderHome();uxImproveMeetingArchive()},0);
})();
