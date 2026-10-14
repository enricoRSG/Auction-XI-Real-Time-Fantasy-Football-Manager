const form = document.getElementById('setup-form');
const auctioneerType = document.getElementById('auctioneer_type');
const auctioneerWrap = document.getElementById('auctioneer-team-wrap');
const teamCount = document.getElementById('team_count');
const teamNames = document.getElementById('team_names');
const errorBox = document.getElementById('setup-error');

auctioneerType.addEventListener('change', () => {
  auctioneerWrap.classList.toggle('hidden', auctioneerType.value === 'external');
});

teamCount.addEventListener('change', () => {
  const n = Math.max(2, Number(teamCount.value || 2));
  const existing = teamNames.value.split('\n').filter(Boolean);
  const lines = [];
  for (let i = 0; i < n; i++) lines.push(existing[i] || `Squadra ${i + 1}`);
  teamNames.value = lines.join('\n');
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  errorBox.classList.add('hidden');
  const data = new FormData(form);
  if (!data.has('allow_overspend')) data.set('allow_overspend', 'false');
  try {
    const r = await fetch('/api/setup', {method: 'POST', body: data, headers:{'X-Setup-Key':document.getElementById('setup-key').value}});
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || 'Errore durante il setup.');
    window.location.href = body.admin_url;
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove('hidden');
  }
});

const participationMode=document.getElementById('participation-mode');
participationMode.addEventListener('change',()=>{const callMode=form.querySelector('[name="call_mode"]');callMode.disabled=participationMode.value==='remote';if(callMode.disabled)callMode.value='manual'});
if(teamNames.value.includes('\\n'))teamNames.value=teamNames.value.replaceAll('\\n','\n');
document.querySelectorAll('.local-time[datetime]').forEach(el=>{if(el.dateTime)el.textContent=new Date(el.dateTime).toLocaleString('it-IT')});
