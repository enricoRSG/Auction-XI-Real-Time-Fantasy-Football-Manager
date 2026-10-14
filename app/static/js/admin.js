const root = document.getElementById('admin-app');
const auctionId = Number(root.dataset.auctionId);
const adminToken = root.dataset.adminToken;
const auctioneerTeamId = Number(root.dataset.auctioneerTeamId || 0);
let state = null;
let ws;
function $(id){return document.getElementById(id)}
async function api(path, options={}){ const r=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options}); const b=await r.json().catch(()=>({})); if(!r.ok){const d=b.detail;const e=new Error(typeof d==='string'?d:(d?.message||'Operazione non riuscita'));e.validation=d;throw e;} if(r.headers.get('X-AuctionXI-Save-Warning'))msg('Operazione salvata nel database, ma checkpoint non riuscito. Riprova SALVA ORA.',true); return b; }
function adminUrl(path){ return `${path}${path.includes('?')?'&':'?'}admin_token=${encodeURIComponent(adminToken)}`; }
async function refresh(){ state=await api(adminUrl(`/api/auction/${auctionId}/state${auctioneerTeamId?`?team_id=${auctioneerTeamId}`:''}`)); render(); await loadTeams(); await loadAccessLinks(); await loadAdminRoster(); await loadCheckpoints();if(state.status==='ASTA_LIVE'&&!$('conclusion-summary').classList.contains('hidden'))showConclusion(await api(adminUrl(`/api/auction/${auctionId}/admin/validation`))); }
async function loadAccessLinks(){
  try{const rows=await api(`/api/auction/${auctionId}/admin/access-links?admin_token=${encodeURIComponent(adminToken)}`);
  $('team-access-links').innerHTML=rows.map(r=>`<div class="team-link-row"><strong>${esc(r.name)}</strong><input readonly value="${location.origin}${r.url}"><button type="button" data-copy-url="${r.url}">Copia</button></div>`).join('');
  document.querySelectorAll('[data-copy-url]').forEach(b=>b.addEventListener('click',async()=>{const u=location.origin+b.dataset.copyUrl;try{await navigator.clipboard.writeText(u);msg('Link copiato.',false)}catch(_){prompt('Copia questo link:',u)}}));
  }catch(e){console.warn(e)}
}
function render(){
  const p=state.current_player;
  if($('admin-phase')) $('admin-phase').textContent=(state.status||'').replaceAll('_',' ');
  $('admin-current-player').textContent=p?`${p.name} · ${p.team} · ${p.role} · Qt.A ${p.quotation??'—'}`:'Nessun giocatore selezionato';
  $('admin-current-bid').textContent=state.current_bid||0;
  $('admin-leader').textContent=state.leader?.name||'—';
  $('admin-last-bids').innerHTML=(state.last_bids||[]).map(b=>`<div class="bid-row"><strong>${b.amount}</strong><span>${esc(b.team)}</span></div>`).join('')||'<div class="muted">Nessun rilancio</div>';
  $('manual-amount').value=Math.max((state.current_bid||0)+1,1);
  const manual = state.call_mode === 'manual' || state.participation_mode === 'remote';
  $('manual-call-controls').classList.toggle('hidden', !manual);
  $('random-call-controls').classList.toggle('hidden', manual);
  $('call-mode-note').textContent = manual ? 'Modalità chiamata: Manuale' : (state.call_mode==='random_role' ? 'Modalità chiamata: Random ruolo per ruolo' : 'Modalità chiamata: Random totale');
  $('advance-role-button').classList.toggle('hidden', state.call_mode!=='random_role');
  $('active-role-label').textContent = state.call_mode==='random_role' ? `Ruolo attivo: ${state.active_role}` : '';
  $('next-random-button').disabled = !!p;
  renderAuctioneerBidControls();
}

function renderAuctioneerBidControls(){
  if(!auctioneerTeamId || !$('auctioneer-credits')) return;
  const team=state?.team;
  if(!team) return;
  $('auctioneer-credits').textContent=team.credits_remaining;
  $('auctioneer-slots').textContent=`P${team.counts.P} · D${team.counts.D} · C${team.counts.C} · A${team.counts.A}`;
  const current=Number(state?.current_bid||0);
  const opening=Number(state?.opening_minimum||1);
  $('self-amount').value=current===0?opening:current+1;
  const blocked=!state?.current_player || state?.status!=='ASTA_LIVE' || team.is_leader || team.needs_regularization;
  document.querySelectorAll('[data-self-step]').forEach(b=>b.disabled=blocked);
  $('self-submit').disabled=blocked;
  if(!state?.current_player){
    $('auctioneer-leader-note').textContent='Nessun giocatore in asta.';
  }else if(team.needs_regularization){
    $('auctioneer-leader-note').textContent=`Budget da regolarizzare · ruolo ${team.regularization_role||''}`;
  }else if(team.is_leader){
    $('auctioneer-leader-note').textContent='SEI LEADER · ulteriori rilanci bloccati';
  }else{
    $('auctioneer-leader-note').textContent=`Puoi offrire fino a ${team.max_bid} crediti.`;
  }
}
$('admin-player-search-btn').addEventListener('click',searchPlayers); $('admin-player-search').addEventListener('keydown',e=>{if(e.key==='Enter')searchPlayers()});
async function searchPlayers(){ try{const q=$('admin-player-search').value.trim(); const rows=await api(`/api/auction/${auctionId}/players?free_only=true&q=${encodeURIComponent(q)}`); $('admin-player-results').innerHTML=rows.slice(0,15).map(p=>`<button class="player-choice" data-player-id="${p.id}" type="button"><strong>${esc(p.name)}</strong><span>${esc(p.team)} · ${p.role}</span></button>`).join('')||'<div class="muted">Nessun giocatore libero trovato</div>'; document.querySelectorAll('[data-player-id]').forEach(b=>b.addEventListener('click',()=>startPlayer(Number(b.dataset.playerId))));}catch(e){msg(e.message,true)} }
async function startPlayer(playerId){ try{await api(adminUrl(`/api/auction/${auctionId}/start-player`),{method:'POST',body:JSON.stringify({player_id:playerId})}); $('admin-player-results').innerHTML=''; $('admin-player-search').value='';}catch(e){msg(e.message,true)} }
$('next-random-button').addEventListener('click', async()=>{ try{ await api(adminUrl(`/api/auction/${auctionId}/next-random`),{method:'POST'}); }catch(e){msg(e.message,true)} });
$('advance-role-button').addEventListener('click', async()=>{ if(!confirm('Passare al ruolo successivo?'))return; try{ await api(adminUrl(`/api/auction/${auctionId}/advance-role`),{method:'POST'}); }catch(e){msg(e.message,true)} });
$('award-button').addEventListener('click',async()=>{if(!state?.current_player)return msg('Nessun giocatore in asta.',true);const version=state.call_version; if(!confirm('Confermi AGGIUDICA? Se non ci sono offerte il giocatore resterà svincolato.'))return; try{const r=await api(adminUrl(`/api/auction/${auctionId}/award?expected_version=${version}`),{method:'POST'}); if(r.needs_regularization)msg(`Aggiudicato. La squadra deve ora regolarizzare il ruolo ${r.regularization_role}.`,false);}catch(e){msg(e.message,true)} });
$('rollback-button').addEventListener('click',async()=>{if(!confirm('Annullare l’ultima aggiudicazione e rimettere il giocatore in asta da 0?'))return; try{const r=await api(adminUrl(`/api/auction/${auctionId}/rollback-last-award`),{method:'POST'}); msg(`Ripristinato ${r.player}.`,false);}catch(e){msg(e.message,true)} });
document.querySelectorAll('[data-self-step]').forEach(b=>b.addEventListener('click',()=>{const step=Number(b.dataset.selfStep);const base=Number(state?.opening_minimum||1);const amount=(state?.current_bid||0)===0?Math.max(step,base):(state.current_bid+step);selfBid(amount,false);}));
$('self-submit')?.addEventListener('click',()=>{const amount=Number($('self-amount').value);if(!Number.isInteger(amount)||amount<1)return selfMsg('Importo non valido.',true);if(!confirm(`Confermi l'offerta di ${amount} crediti per la tua squadra?`))return;selfBid(amount,true);});
async function selfBid(amount,confirmed){
  if(!auctioneerTeamId)return;
  if(!Number.isInteger(amount)||amount<1)return selfMsg('Importo non valido.',true);
  try{await api(`/api/auction/${auctionId}/bid`,{method:'POST',body:JSON.stringify({team_id:auctioneerTeamId,amount,source:'admin_self',admin_token:adminToken})});selfMsg('Offerta registrata.',false);}catch(e){selfMsg(e.message,true)}
}
function selfMsg(text,error){const el=$('self-bid-message');if(!el)return;el.textContent=text;el.classList.toggle('error',error);el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),3000)}

document.querySelectorAll('[data-admin-step]').forEach(b=>b.addEventListener('click',()=>{const step=Number(b.dataset.adminStep);const base=Number(state?.opening_minimum||1);const amount=(state?.current_bid||0)===0?Math.max(step,base):(state.current_bid+step);manualBid(amount);})); $('manual-submit').addEventListener('click',()=>manualBid(Number($('manual-amount').value)));
async function manualBid(amount){ const teamId=Number($('manual-team').value); if(!Number.isInteger(amount)||amount<1)return msg('Importo non valido.',true); try{await api(`/api/auction/${auctionId}/bid`,{method:'POST',body:JSON.stringify({team_id:teamId,amount,source:'admin_manual',admin_token:adminToken})});}catch(e){msg(e.message,true)} }
async function loadTeams(){ const teams=await api(adminUrl(`/api/auction/${auctionId}/teams`)); $('admin-teams').innerHTML=teams.map(t=>`<div class="team-row"><strong>${esc(t.name)}</strong><span>${t.credits_remaining} cr. · P${t.counts.P} D${t.counts.D} C${t.counts.C} A${t.counts.A}</span>${t.needs_regularization?`<span class="warning-pill">REGOLARIZZA ${t.regularization_role||''}</span>`:(t.auctioneer_team?'<span class="pill">Battitore</span>':'')}</div>`).join(''); }
function connect(){ const proto=location.protocol==='https:'?'wss':'ws'; ws=new WebSocket(`${proto}://${location.host}/ws/auction/${auctionId}?token=${encodeURIComponent(adminToken)}`); ws.onopen=()=>{conn(true);refresh().catch(e=>msg(e.message,true))}; ws.onmessage=async()=>{await refresh().catch(e=>msg(e.message,true));loadEventLog()}; ws.onclose=()=>{conn(false);setTimeout(connect,1500)}; }
function conn(ok){ $('admin-connection-dot').classList.toggle('online',ok); $('admin-connection-dot').classList.toggle('offline',!ok); $('admin-connection-label').textContent=ok?'Sincronizzato':'Disconnesso'; }
function msg(text,error){const el=$('admin-message');el.textContent=text;el.classList.toggle('error',error);el.classList.remove('hidden')} function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

async function loadFreeRanked(){
  const role=$('free-role-filter')?.value||'';
  const rows=await api(`/api/auction/${auctionId}/free-ranked?role=${encodeURIComponent(role)}`);
  $('free-ranked-list').innerHTML=rows.slice(0,100).map((p,i)=>`<div class="team-row"><strong>${i+1}. ${esc(p.name)}</strong><span>${esc(p.team)} · ${p.role} · Quot. ${p.quotation??'—'} · FVM ${p.fvm??'—'} · ID ${p.id}</span></div>`).join('')||'<div class="muted">Nessun giocatore svincolato.</div>';
}
$('refresh-free-button')?.addEventListener('click',loadFreeRanked);
$('free-role-filter')?.addEventListener('change',loadFreeRanked);
$('conclude-live-button')?.addEventListener('click',async()=>{try{showConclusion(await api(adminUrl(`/api/auction/${auctionId}/admin/validation`)))}catch(e){showConclusion({errors:[e.message],valid:false})}});
$('start-patching-button')?.addEventListener('click',async()=>{if(!confirm('Avviare la fase rappezzamenti?'))return;try{await api(adminUrl(`/api/auction/${auctionId}/start-patching`),{method:'POST'});await refresh();}catch(e){msg(e.message,true)}});
$('patch-release-button')?.addEventListener('click',async()=>{const team_id=Number($('patch-team').value),player_id=Number($('patch-owned-search').value);if(!player_id)return msg('Inserisci ID giocatore da svincolare.',true);try{const r=await api(adminUrl(`/api/auction/${auctionId}/patch-release`),{method:'POST',body:JSON.stringify({team_id,player_id})});$('patch-move-id').value=r.move_id;msg(`${r.player} svincolato. Movimento ${r.move_id}.`,false);await loadFreeRanked();}catch(e){msg(e.message,true)}});
$('patch-assign-button')?.addEventListener('click',async()=>{const payload={team_id:Number($('patch-team').value),move_id:Number($('patch-move-id').value),player_id:Number($('patch-new-player-id').value),price:Number($('patch-price').value)};try{const r=await api(adminUrl(`/api/auction/${auctionId}/patch-assign`),{method:'POST',body:JSON.stringify(payload)});msg(`${r.player} assegnato a ${r.price} crediti.`,false);await loadFreeRanked();}catch(e){msg(e.message,true)}});
$('conclude-patching-button')?.addEventListener('click',async()=>{if(!confirm('Concludere i rappezzamenti e rendere definitive le rose?'))return;try{await api(adminUrl(`/api/auction/${auctionId}/conclude-patching`),{method:'POST'});await refresh();}catch(e){msg(e.message,true)}});
$('final-reset-button')?.addEventListener('click',async()=>{if(!confirm('Hai già scaricato ENTRAMBI i file finali? Questa operazione cancella definitivamente la sessione.'))return;try{const r=await api(adminUrl(`/api/auction/${auctionId}/close-and-reset?exports_confirmed=true`),{method:'POST'});location.href=r.redirect||'/';}catch(e){msg(e.message,true)}});

const oldRender=render;
render=function(){oldRender();
  const st=state?.status;
  $('free-ranked-panel')?.classList.toggle('hidden', !['RIEPILOGO_SVINCOLATI','RAPPEZZAMENTI','ROSE_DEFINITIVE'].includes(st));
  $('patch-admin-panel')?.classList.toggle('hidden', st!=='RAPPEZZAMENTI');
  $('final-export-panel')?.classList.toggle('hidden', st!=='ROSE_DEFINITIVE');
  $('conclude-live-button').disabled=st!=='ASTA_LIVE';
  $('start-patching-button').disabled=st!=='RIEPILOGO_SVINCOLATI';
  $('conclude-patching-button').disabled=!['RAPPEZZAMENTI','RIEPILOGO_SVINCOLATI'].includes(st);
  $('export-leghe-link').href=adminUrl(`/api/auction/${auctionId}/export/leghe`);
  $('export-archive-link').href=adminUrl(`/api/auction/${auctionId}/export/archive`);
  $('final-reset-button').disabled = !(state?.export_leghe_generated && state?.export_archive_generated);
  $('final-reset-button').title = $('final-reset-button').disabled ? 'Scarica prima entrambi i file finali.' : '';
  $('export-leghe-link').classList.toggle('export-done', !!state?.export_leghe_generated);
  $('export-archive-link').classList.toggle('export-done', !!state?.export_archive_generated);
  if(['RIEPILOGO_SVINCOLATI','RAPPEZZAMENTI'].includes(st)) loadFreeRanked().catch(()=>{});
}

async function loadPresence(){
  const target=document.getElementById('admin-presence-list');
  if(!target)return;
  try{
    const rows=await api(`/api/auction/${auctionId}/admin/presence?admin_token=${encodeURIComponent(adminToken)}`);
    target.innerHTML=rows.map(r=>{
      if(!r.devices.length)return `<div class="presence-row"><strong>${esc(r.team)}</strong><span class="offline-badge">○ nessun dispositivo online</span></div>`;
      const labels=r.devices.map(d=>`<span class="device-badge ${d.presence_mode==='remote'?'remote':''}">${d.presence_mode==='remote'?'Da remoto':'In presenza'}</span>`).join(' ');
      return `<div class="presence-row"><strong>${esc(r.team)}</strong><span>${r.devices.length} dispositiv${r.devices.length===1?'o':'i'} ${labels}</span></div>`;
    }).join('');
  }catch(e){target.innerHTML=`<div class="muted">Presenze non disponibili.</div>`;}
}
setInterval(loadPresence,20000);
loadPresence();


async function loadEventLog(){
  const target=document.getElementById('admin-event-log');
  if(!target)return;
  try{
    const rows=await api(`/api/auction/${auctionId}/admin/events?admin_token=${encodeURIComponent(adminToken)}&limit=40`);
    target.innerHTML=rows.map(r=>`<div class="event-row"><span>${new Date(r.created_at+'Z').toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span><strong>${esc(r.event_type)}</strong><small>${esc(r.details)}</small></div>`).join('')||'<div class="muted">Nessun evento.</div>';
  }catch(e){target.innerHTML='<div class="muted">Registro non disponibile.</div>';}
}
setInterval(loadEventLog,15000);
loadEventLog();

$('export-leghe-link')?.addEventListener('click',()=>setTimeout(()=>refresh().catch(()=>{}),1200));
$('export-archive-link')?.addEventListener('click',()=>setTimeout(()=>refresh().catch(()=>{}),1200));

let clockOffset = 0;
let draftOrder = [];
let teamsById = {};
let rosterSequence = 0;
function showConclusion(summary){
  const el=$('conclusion-summary'); el.classList.remove('hidden'); el.classList.toggle('error',!summary.valid);
  el.innerHTML=`<strong>${summary.valid?'Pronta per la conclusione':'Impossibile concludere l’asta'}</strong><p>${summary.complete_rosters??'—'}/${summary.total_teams??'—'} rose complete · ${summary.irregular_teams??'—'} squadre da regolarizzare · ${summary.open_auctions??'—'} aste aperte</p><ul>${(summary.errors||[]).map(e=>`<li>${esc(e)}</li>`).join('')}</ul>`;
  $('confirm-conclusion').classList.toggle('hidden',!summary.valid);
}
$('confirm-conclusion').addEventListener('click',async()=>{try{await api(adminUrl(`/api/auction/${auctionId}/conclude-live`),{method:'POST'});$('confirm-conclusion').classList.add('hidden');$('conclusion-summary').textContent='Asta conclusa: Riepilogo svincolati.';await refresh();await loadFreeRanked()}catch(e){showConclusion(typeof e.validation==='object'?e.validation:{valid:false,errors:[e.message]})}});
const renderWithFeatures=render;
render=function(){renderWithFeatures();
  clockOffset=Date.parse(state.server_time)-Date.now();
  $('pause-button').textContent=state.paused?'RIPRENDI ASTA':'PAUSA';
  $('pause-button').disabled=state.status!=='ASTA_LIVE';
  $('cancel-call-button').disabled=!state.current_player;
  $('admin-dealer').textContent=state.participation_mode==='remote'?`Da remoto · Turno: ${state.dealer?.name||'—'}${state.paused?' · IN PAUSA':''}`:`In presenza${state.paused?' · IN PAUSA':''}`;
  $('dealer-controls').classList.toggle('hidden',state.participation_mode!=='remote');
  document.querySelectorAll('[data-admin-step],#manual-submit,#next-random-button,#advance-role-button,#admin-player-search-btn').forEach(b=>{if(state.paused||state.status!=='ASTA_LIVE')b.disabled=true;else if(b.id!=='next-random-button')b.disabled=false});
  updateAdminTimer();
};
function updateAdminTimer(){const remaining=state?.deadline?Math.max(0,Math.ceil((Date.parse(state.deadline)-(Date.now()+clockOffset))/1000)):state?.timer_remaining; $('admin-timer').textContent=state?.participation_mode==='remote'&&state?.current_player?`${state.paused?'In pausa · ':''}${remaining??60} s`:'';}
setInterval(updateAdminTimer,250);
$('cancel-call-button').addEventListener('click',async()=>{if(!confirm('Annullare la chiamata corrente? Il giocatore tornerà libero.'))return;try{await api(adminUrl(`/api/auction/${auctionId}/admin/cancel-call`),{method:'POST'});await refresh()}catch(e){msg(e.message,true)}});
$('pause-button').addEventListener('click',async()=>{try{await api(adminUrl(`/api/auction/${auctionId}/admin/pause`),{method:'POST',body:JSON.stringify({paused:!state.paused})});await refresh()}catch(e){msg(e.message,true)}});
async function loadCheckpoints(){try{const saves=await api(adminUrl(`/api/auction/${auctionId}/admin/checkpoints`));$('save-status').textContent=saves.length?`Ultimo checkpoint: ${new Date(saves[0].saved_at).toLocaleString('it-IT')}`:'Stato salvato nel database';$('checkpoint-list').innerHTML=saves.map(s=>`<p>${esc(new Date(s.saved_at).toLocaleString('it-IT'))} · ${Math.ceil(s.bytes/1024)} KB</p>`).join('')+'<p>In caso di database danneggiato, la riapertura recupera automaticamente la copia valida più recente. Per scegliere una copia precedente usa Ripristina checkpoint dopo aver chiuso il server.</p>'}catch(e){$('save-status').textContent=e.message}}
$('save-now-button').addEventListener('click',async()=>{try{await api(adminUrl(`/api/auction/${auctionId}/admin/save`),{method:'POST'});await loadCheckpoints();msg('Salvataggio completato.',false)}catch(e){msg(e.message,true)}});
function selectCorrectionPlayer(id,name,price){$('correction-player').value=id;$('correction-selected').textContent=name;if(price!=null)$('correction-price').value=price;}
async function loadAdminRoster(){
  const sequence=++rosterSequence; const teamId=Number($('correction-team').value);
  const data=await api(adminUrl(`/api/auction/${auctionId}/team/${teamId}/roster`));if(sequence!==rosterSequence)return;
  $('correction-credits').value=data.credits_remaining;
  $('admin-roster').innerHTML=Object.entries(data.players).map(([role,players])=>`<h3>${role} · ${players.length}/${data.slots[role]}</h3>`+players.map(p=>`<button type="button" class="player-choice" data-correction-id="${p.id}" data-name="${esc(p.name)}" data-price="${p.price}">${esc(p.name)} · ${esc(p.team)} · ${p.price} cr.</button>`).join('')).join('');
  $('admin-roster').querySelectorAll('[data-correction-id]').forEach(b=>b.addEventListener('click',()=>selectCorrectionPlayer(Number(b.dataset.correctionId),b.dataset.name,Number(b.dataset.price))));
  const teams=await api(adminUrl(`/api/auction/${auctionId}/teams`)); teamsById=Object.fromEntries(teams.map(t=>[t.id,t.name])); if(!draftOrder.length&&state){draftOrder=[...state.dealer_order];renderDealerOrder()}
}
$('correction-team').addEventListener('change',()=>loadAdminRoster().catch(e=>msg(e.message,true)));
$('correction-search-button').addEventListener('click',async()=>{try{const rows=await api(`/api/auction/${auctionId}/players?q=${encodeURIComponent($('correction-search').value)}`);$('correction-results').innerHTML=rows.map(p=>`<button type="button" class="player-choice" data-correction-id="${p.id}" data-name="${esc(p.name)}" data-price="${p.price??1}">${esc(p.name)} · ${p.role} · ${esc(p.owner_team||'libero')}</button>`).join('')||'Nessun risultato';$('correction-results').querySelectorAll('[data-correction-id]').forEach(b=>b.addEventListener('click',()=>selectCorrectionPlayer(Number(b.dataset.correctionId),b.dataset.name,Number(b.dataset.price))))}catch(e){msg(e.message,true)}});
async function submitCorrection(action){
 const force=$('correction-force').checked;
 if(!confirm(force?'FORZA COMUNQUE: confermi una correzione anche se non valida o con rimozione del ban?':'Confermi la correzione amministrativa?'))return;
 const payload={action,team_id:Number($('correction-team').value),player_id:Number($('correction-player').value)||null,price:Number($('correction-price').value),credits:Number($('correction-credits').value),force};
 try{const r=await api(adminUrl(`/api/auction/${auctionId}/admin/correction`),{method:'POST',body:JSON.stringify(payload)});const el=$('correction-message');el.textContent=r.description;el.className='message';$('correction-force').checked=false;await refresh();await loadEventLog()}catch(e){const el=$('correction-message');el.textContent=e.message;el.className='message error'}
}
$('correction-submit').addEventListener('click',()=>submitCorrection($('correction-action').value));
$('correction-recalculate').addEventListener('click',()=>submitCorrection('recalculate'));
$('undo-correction').addEventListener('click',async()=>{if(!confirm('Annullare l’ultima correzione admin, se non sono avvenute altre operazioni?'))return;try{const r=await api(adminUrl(`/api/auction/${auctionId}/admin/undo-correction`),{method:'POST'});msg(r.description,false);await refresh();await loadEventLog()}catch(e){msg(e.message,true)}});
function renderDealerOrder(){$('dealer-order').innerHTML=draftOrder.map((id,i)=>`<div class="team-row"><span>${i+1}. ${esc(teamsById[id]||id)}</span><button type="button" data-order-index="${i}" data-direction="-1" ${i===0?'disabled':''}>↑</button><button type="button" data-order-index="${i}" data-direction="1" ${i===draftOrder.length-1?'disabled':''}>↓</button></div>`).join('');$('dealer-order').querySelectorAll('[data-order-index]').forEach(b=>b.addEventListener('click',()=>{const i=Number(b.dataset.orderIndex),j=i+Number(b.dataset.direction);[draftOrder[i],draftOrder[j]]=[draftOrder[j],draftOrder[i]];renderDealerOrder()}))}
async function setDealer(order){try{await api(adminUrl(`/api/auction/${auctionId}/admin/dealer`),{method:'POST',body:JSON.stringify({team_id:Number($('dealer-team').value),...(order?{order:draftOrder}:{})})});await refresh()}catch(e){msg(e.message,true)}}
$('dealer-set').addEventListener('click',()=>setDealer(false));
$('dealer-order-save').addEventListener('click',()=>setDealer(true));
refresh().catch(e=>msg(e.message,true));connect();
