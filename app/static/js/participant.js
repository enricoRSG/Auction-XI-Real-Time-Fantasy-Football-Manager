const root = document.getElementById('participant-app');
const auctionId = Number(root.dataset.auctionId);
const teamId = Number(root.dataset.teamId);
const accessToken = root.dataset.accessToken;
let state = null;
let soundsOn = false;
let ws;
const deviceId = localStorage.getItem('fantacalcio_device_id') || (()=>{const v=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random());localStorage.setItem('fantacalcio_device_id',v);return v;})();
let presenceMode = root.dataset.participationMode || 'presence';
let activeView='live', selectedPublicTeam=null, clockOffset=0, connected=false, publicSequence=0;

function $(id){ return document.getElementById(id); }
async function api(path, options={}) { const r = await fetch(path, {headers:{'Content-Type':'application/json', ...(options.headers||{})}, ...options}); const body = await r.json().catch(()=>({})); if (!r.ok) throw new Error(typeof body.detail==='string'?body.detail:(body.detail?.message||'Operazione non riuscita')); return body; }
async function refreshState(){ state = await api(`/api/auction/${auctionId}/state?team_id=${teamId}&access_token=${encodeURIComponent(accessToken)}`); clockOffset=Date.parse(state.server_time)-Date.now();renderState();if(activeView==='teams')await loadPublicTeams();if(activeView==='roster')await loadRoster(); }
function renderState(){
  const p = state.current_player;
  $('no-player').classList.toggle('hidden', !!p); $('player-active').classList.toggle('hidden', !p);
  if (p) { $('player-name').textContent = p.name; $('player-team').textContent = p.team; $('player-role').textContent = p.role; $('player-quotation').textContent=p.quotation??'—'; }
  $('current-bid').textContent = state.current_bid ?? 0; $('leader-name').textContent = state.leader?.name || '—'; $('credits-remaining').textContent = state.team?.credits_remaining ?? '—';
  const opening = Number(state.opening_minimum || 1); const openingLabel=$('opening-minimum-label'); if(openingLabel){ openingLabel.textContent = state.current_bid===0 && p ? `Offerta minima iniziale: ${opening}` : ''; openingLabel.classList.toggle('hidden', !(state.current_bid===0 && p && opening>1)); }
  const c = state.team?.counts || {P:0,D:0,C:0,A:0}; $('slot-summary').textContent = `P ${c.P} · D ${c.D} · C ${c.C} · A ${c.A}`;
  $('last-bids').innerHTML = (state.last_bids || []).map(b => `<div class="bid-row"><strong>${b.amount}</strong><span>${escapeHtml(b.team)}</span></div>`).join('') || '<div class="muted">Nessun rilancio</div>';
  const blocked = !connected || !p || state.paused || state.status!=='ASTA_LIVE' || state.team?.is_leader || state.team?.needs_regularization;
  document.querySelectorAll('[data-step]').forEach(btn => btn.disabled = blocked); $('custom-offer-button').disabled = blocked; $('custom-offer').value = state.current_bid===0 ? Math.max(Number(state.opening_minimum||1),1) : Math.max((state.current_bid || 0)+1, 1);
  if(state.team?.needs_regularization){ showPersistent(`Devi regolarizzare la rosa: svincola un giocatore del ruolo ${state.team.regularization_role}.`); } else { clearPersistent(); }
}
async function place(amount){ try { await api(`/api/auction/${auctionId}/bid`, {method:'POST', body:JSON.stringify({team_id:teamId, amount, access_token:accessToken})}); showMessage('bid-message', `Offerta ${amount} registrata.`, false); } catch(err){ showMessage('bid-message', err.message, true); } }
document.querySelectorAll('[data-step]').forEach(btn => btn.addEventListener('click', () => { const step=Number(btn.dataset.step); const base=Number(state?.opening_minimum||1); const amount=(state?.current_bid||0)===0?Math.max(step,base):(state.current_bid+step); place(amount); }));
$('custom-offer-button').addEventListener('click', async () => { const amount = Number($('custom-offer').value); if (!Number.isInteger(amount) || amount <= (state?.current_bid||0)) return showMessage('bid-message', `L'offerta deve superare ${state?.current_bid||0}.`, true); if (!confirm(`Confermi l'offerta di ${amount} crediti?`)) return; await place(amount); });
soundsOn = localStorage.getItem('fantacalcio_sounds') === 'on'; $('sound-toggle').textContent=soundsOn?'Suoni ON':'Suoni OFF';
$('sound-toggle').addEventListener('click', () => { soundsOn = !soundsOn; localStorage.setItem('fantacalcio_sounds',soundsOn?'on':'off'); $('sound-toggle').textContent = soundsOn ? 'Suoni ON' : 'Suoni OFF'; });
function renderPresence(){ $('presence-button').textContent=presenceMode==='remote'?'Da remoto':'In presenza'; }
async function savePresence(){ localStorage.setItem(`presence_${auctionId}_${teamId}`,presenceMode); renderPresence(); try{await api(`/api/auction/${auctionId}/presence?team_id=${teamId}&access_token=${encodeURIComponent(accessToken)}&device_id=${encodeURIComponent(deviceId)}&presence_mode=${presenceMode}`,{method:'POST'});}catch(_){} }
$('presence-button').disabled=true; renderPresence(); savePresence();
document.querySelectorAll('[data-view]').forEach(btn => btn.addEventListener('click', async () => { const v = btn.dataset.view; document.querySelectorAll('[data-view]').forEach(x => x.classList.toggle('active', x===btn)); $('roster-view').classList.add('hidden'); $('search-view').classList.add('hidden'); $('teams-view').classList.add('hidden'); document.querySelector('.live-player-panel').classList.remove('hidden'); document.querySelector('#offer-panel').classList.remove('hidden'); if (v==='roster') { document.querySelector('.live-player-panel').classList.add('hidden'); document.querySelector('#offer-panel').classList.add('hidden'); await loadRoster(); } if (v==='search') { document.querySelector('.live-player-panel').classList.add('hidden'); document.querySelector('#offer-panel').classList.add('hidden'); $('search-view').classList.remove('hidden'); } if (v==='teams') { document.querySelector('.live-player-panel').classList.add('hidden'); document.querySelector('#offer-panel').classList.add('hidden'); $('teams-view').classList.remove('hidden'); await loadPublicTeams(); } }));
async function loadRoster(){
  const data = await api(`/api/auction/${auctionId}/team/${teamId}/roster?access_token=${encodeURIComponent(accessToken)}`); const labels = {P:'PORTIERI',D:'DIFENSORI',C:'CENTROCAMPISTI',A:'ATTACCANTI'};
  let html = `<div class="roster-top"><div>Crediti residui <strong>${data.credits_remaining}</strong></div><div>Spesi <strong>${data.credits_spent}</strong></div></div>${data.credit_adjustment?`<p class="helper">Rettifica admin: ${data.credit_adjustment}</p>`:''}`;
  if(data.needs_regularization) html += `<div class="message error">Regolarizzazione obbligatoria: svincola un giocatore ${data.regularization_role}.</div>`;
  for (const role of ['P','D','C','A']) {
    const players = data.players[role] || []; html += `<div class="roster-role"><div class="section-title">${labels[role]} · svincoli residui ${data.release_remaining[role]}</div>`;
    const rows = Math.max(data.slots[role], players.length);
    for (let i=0; i<rows; i++) { const p = players[i]; html += `<div class="roster-row roster-row-actions"><span>${i+1}</span><strong>${p?escapeHtml(p.name):''}</strong><span>${p?escapeHtml(p.team):''}</span><strong>${p?p.price:''}</strong>${p&&p.can_release?`<button class="release-button" data-release-id="${p.id}" data-release-name="${escapeHtml(p.name)}" type="button">Svincola</button>`:'<span></span>'}</div>`; }
    html += '</div>';
  }
  $('roster-view').innerHTML = html; $('roster-view').classList.remove('hidden');
  document.querySelectorAll('[data-release-id]').forEach(btn=>btn.addEventListener('click',()=>releaseOwned(Number(btn.dataset.releaseId), btn.dataset.releaseName)));
}
async function releaseOwned(playerId, name){ if(!confirm(`Confermi lo svincolo di ${name}? Recupererai il prezzo pagato e non potrai più riacquistarlo in questa asta.`))return; try{ const r=await api(`/api/auction/${auctionId}/release`,{method:'POST',body:JSON.stringify({team_id:teamId,player_id:playerId,access_token:accessToken})}); showMessage('bid-message', `${r.player} svincolato: +${r.refund} crediti.`, false); await loadRoster(); }catch(e){showMessage('bid-message',e.message,true)} }
$('search-button').addEventListener('click', searchPlayers); $('player-search').addEventListener('keydown', e => {if(e.key==='Enter') searchPlayers();});
async function searchPlayers(){ const q = $('player-search').value.trim(); const rows = await api(`/api/auction/${auctionId}/players?q=${encodeURIComponent(q)}`); $('search-results').innerHTML = rows.map(p => `<div class="search-result"><div><strong>${escapeHtml(p.name)}</strong><span>${escapeHtml(p.team)} · ${p.role}</span></div><div><span class="pill">${p.state}</span>${p.owner_team?`<small>${escapeHtml(p.owner_team)} · ${p.price} cr.</small>`:(p.previous_owner?`<small>Prima: ${escapeHtml(p.previous_owner)} · ${p.previous_price} cr.</small>`:'')}</div></div>`).join('') || '<div class="muted">Nessun risultato</div>'; }
function connectWS(){ const proto = location.protocol === 'https:' ? 'wss' : 'ws'; ws = new WebSocket(`${proto}://${location.host}/ws/auction/${auctionId}?token=${encodeURIComponent(accessToken)}`); ws.onopen = () => {setConnection(true);refreshState().catch(e=>showMessage('bid-message',e.message,true))}; ws.onmessage = async (e) => { const msg = JSON.parse(e.data);if(msg.type==='reset'){location.href='/';return;} if (soundsOn && msg.type==='bid') beep(); await refreshState().catch(e=>showMessage('bid-message',e.message,true)); }; ws.onclose = () => { setConnection(false); setTimeout(connectWS, 1500); }; }
function setConnection(ok){ connected=ok;$('connection-dot').classList.toggle('online', ok); $('connection-dot').classList.toggle('offline', !ok); $('connection-label').textContent = ok?'Sincronizzato':'Disconnesso'; document.querySelectorAll('#offer-panel button').forEach(b=>b.disabled=!ok || !!state?.paused || state?.status!=='ASTA_LIVE' || !!state?.team?.needs_regularization || !!state?.team?.is_leader || !state?.current_player);if(state)renderRemote(); }
function beep(){ try{ const ctx=new (window.AudioContext||window.webkitAudioContext)(); const o=ctx.createOscillator(); const g=ctx.createGain(); o.connect(g); g.connect(ctx.destination); g.gain.value=.03; o.frequency.value=720; o.start(); o.stop(ctx.currentTime+.07);}catch(_){} }
function showMessage(id,text,error){ const el=$(id); el.textContent=text; el.classList.toggle('error',error); el.classList.remove('hidden'); setTimeout(()=>el.classList.add('hidden'),3000); }
function showPersistent(text){ let el=document.getElementById('regularization-message'); if(!el){el=document.createElement('div');el.id='regularization-message';el.className='message error';document.querySelector('.compact-summary').after(el);} el.textContent=text; }
function clearPersistent(){ const el=document.getElementById('regularization-message'); if(el)el.remove(); }
function escapeHtml(s){ return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }

async function loadPostAuctionFree(){
  const role=$('participant-free-role')?.value||'';
  const rows=await api(`/api/auction/${auctionId}/free-ranked?role=${encodeURIComponent(role)}`);
  $('participant-free-list').innerHTML=rows.map((p,i)=>`<div class="search-result"><div><strong>${i+1}. ${escapeHtml(p.name)}</strong><span>${escapeHtml(p.team)} · ${p.role}</span></div><div><strong>Quot. ${p.quotation??'—'}</strong><small>FVM ${p.fvm??'—'}</small></div></div>`).join('')||'<div class="muted">Nessuno svincolato.</div>';
}
$('participant-free-refresh')?.addEventListener('click',loadPostAuctionFree);
$('participant-free-role')?.addEventListener('change',loadPostAuctionFree);
const originalRenderState=renderState;
renderState=function(){originalRenderState();
  const post=['RIEPILOGO_SVINCOLATI','RAPPEZZAMENTI','ROSE_DEFINITIVE'].includes(state.status);
  $('post-auction-view')?.classList.toggle('hidden',!post);
  if(post){ $('offer-panel').classList.add('hidden'); document.querySelector('.live-player-panel').classList.add('hidden'); loadPostAuctionFree().catch(()=>{}); }
}

async function loadPublicTeams(){
  try{
    const data=await api(`/api/auction/${auctionId}/public-teams?access_token=${encodeURIComponent(accessToken)}`);
    $('teams-visibility-note').textContent=data.show_all_credits
      ? "Crediti residui e spesi sono pubblici perché il battitore partecipa all'asta."
      : 'Con battitore esterno, ogni squadra vede i propri crediti; per gli avversari restano nascosti.';
    $('teams-public-list').innerHTML=data.teams.map(t=>{
      const counts=t.counts||{P:0,D:0,C:0,A:0};
      const credits=t.credits_remaining==null?'—':t.credits_remaining;
      const spent=t.credits_spent==null?'—':t.credits_spent;
      const status=t.online_devices>0?`<span class="online-badge">● ${t.online_devices} online</span>`:'<span class="offline-badge">○ offline</span>';
      const remote=t.remote_devices>0?`<span class="remote-badge">${t.remote_devices} remoto</span>`:'';
      return `<div class="team-public-card ${t.id===teamId?'my-team-card':''}"><button type="button" data-roster-team="${t.id}">Apri rosa</button>
        <div class="team-public-head"><strong>${escapeHtml(t.name)}</strong><div>${status} ${remote}</div></div>
        <div class="team-public-metrics"><span><small>Crediti</small><strong>${credits}</strong></span><span><small>Spesi</small><strong>${spent}</strong></span><span><small>P</small><strong>${counts.P}</strong></span><span><small>D</small><strong>${counts.D}</strong></span><span><small>C</small><strong>${counts.C}</strong></span><span><small>A</small><strong>${counts.A}</strong></span></div>
      </div>`;
    }).join('');
    $('teams-public-list').querySelectorAll('[data-roster-team]').forEach(b=>b.addEventListener('click',()=>{selectedPublicTeam=Number(b.dataset.rosterTeam);loadPublicRoster().catch(e=>{$('public-roster').textContent=e.message})}));
    if(selectedPublicTeam)await loadPublicRoster();
  }catch(e){ $('teams-public-list').innerHTML=`<div class="message error">${escapeHtml(e.message)}</div>`; }
}

// Heartbeat: mantiene aggiornato lo stato presenza/remoto del dispositivo senza richiedere azioni manuali.
setInterval(()=>savePresence().catch(()=>{}),20000);

document.querySelectorAll('[data-view]').forEach(btn=>btn.addEventListener('click',()=>{activeView=btn.dataset.view}));
async function loadPublicRoster(){
 const sequence=++publicSequence,id=selectedPublicTeam;
 const data=await api(`/api/auction/${auctionId}/team/${id}/roster?access_token=${encodeURIComponent(accessToken)}`);
 if(sequence!==publicSequence||id!==selectedPublicTeam)return;
 $('public-roster').innerHTML=`<h2>${escapeHtml(data.team)}</h2><p>Crediti ${data.credits_remaining??'—'} · Spesi ${data.credits_spent??'—'}${data.credit_adjustment?` · Rettifica admin ${data.credit_adjustment}`:''}</p>`+Object.entries(data.players).map(([role,players])=>`<h3>${role} · ${players.length}/${data.slots[role]} · ${Math.max(0,data.slots[role]-players.length)} liberi</h3>`+players.map(p=>`<div class="search-result"><strong>${escapeHtml(p.name)}</strong><span>${escapeHtml(p.team)} · ${p.price} cr.</span></div>`).join('')).join('');
}
function renderRemote(){
 const remote=state?.participation_mode==='remote';$('remote-panel').classList.toggle('hidden',!remote);
 $('remote-dealer').textContent=`Turno: ${state?.dealer?.name||'—'}${state?.paused?' · IN PAUSA':''}`;
 const blocked=!connected||state?.paused||state?.status!=='ASTA_LIVE'||!!state?.current_player||state?.dealer?.id!==teamId;
 $('remote-choose').disabled=blocked;$('remote-pass').disabled=blocked;
 if(blocked)$('remote-picker').classList.add('hidden');
 updateTimer();
}
function updateTimer(){const remaining=state?.deadline?Math.max(0,Math.ceil((Date.parse(state.deadline)-(Date.now()+clockOffset))/1000)):state?.timer_remaining;$('participant-timer').textContent=state?.current_player&&state?.participation_mode==='remote'?`${state.paused?'In pausa · ':''}${remaining??60} s`:'';}
const renderAll=renderState;renderState=function(){renderAll();renderRemote()};
setInterval(updateTimer,250);
$('remote-choose').addEventListener('click',()=>{$('remote-picker').classList.remove('hidden');searchRemote()});
async function searchRemote(){try{const params=new URLSearchParams({free_only:'true',q:$('remote-search').value,role:$('remote-role').value,club:$('remote-club').value});const rows=await api(`/api/auction/${auctionId}/players?${params}`);$('remote-results').innerHTML=rows.map(p=>`<button type="button" class="player-choice" data-remote-player="${p.id}" data-player-name="${escapeHtml(p.name)}">${escapeHtml(p.name)} · ${escapeHtml(p.team)} · ${p.role} · Qt.A ${p.quotation??'—'}</button>`).join('')||'Nessun giocatore libero';$('remote-results').querySelectorAll('[data-remote-player]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm(`Mettere all’asta ${b.dataset.playerName}?`))return;try{await api(`/api/auction/${auctionId}/select-player`,{method:'POST',body:JSON.stringify({team_id:teamId,access_token:accessToken,player_id:Number(b.dataset.remotePlayer)})});$('remote-picker').classList.add('hidden');await refreshState()}catch(e){remoteMessage(e.message)}}))}catch(e){remoteMessage(e.message)}}
function remoteMessage(text){const el=$('remote-message');el.textContent=text;el.className='message error';}
$('remote-search-button').addEventListener('click',searchRemote);$('remote-role').addEventListener('change',searchRemote);
$('remote-pass').addEventListener('click',async()=>{try{await api(`/api/auction/${auctionId}/pass`,{method:'POST',body:JSON.stringify({team_id:teamId,access_token:accessToken})});await refreshState()}catch(e){remoteMessage(e.message)}});
refreshState().catch(e=>showMessage('bid-message',e.message,true));connectWS();
