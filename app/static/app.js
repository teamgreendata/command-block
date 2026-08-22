import { QUICK_COMMANDS, PRESETS, SUGGESTIONS, findCommand, buildQuick, buildWaypointTp } from './quick-commands.js';
import { CARD_STATS, DEFAULT_CARD_STATS, fmtDuration } from './stats.js';

const $ = s => document.querySelector(s);
const stripCodes = s => String(s).replace(/§./g, '');

const GLOBAL_COMMANDS = QUICK_COMMANDS.filter(c => c.scope === 'global');
// Card action order: the common stuff first, destructive last.
const CARD_ORDER = ['tp', 'give', 'effect', 'gamemode', 'experience', 'msg', 'summon', 'clear', 'kill'];
const CARD_COMMANDS = CARD_ORDER.map(findCommand).filter(Boolean);

let restarting = false;
let statusTimer = null;
let logsTimer = null;
let clockTimer = null;
let infoTimer = null;
const history = [];
let histIdx = -1;

// ---------------------------------------------------------------- helpers

async function api(path, body) {
  const opts = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

let msgTimer = null;
function flash(text, isError) {
  const el = $('#msg');
  el.textContent = text;
  el.hidden = false;
  el.classList.toggle('error', !!isError);
  clearTimeout(msgTimer);
  msgTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

function row(name, buttons) {
  const li = document.createElement('li');
  const span = document.createElement('span');
  span.className = 'name';
  span.textContent = name;
  li.appendChild(span);
  for (const [label, cls, handler] of buttons) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.className = cls;
    b.addEventListener('click', handler);
    li.appendChild(b);
  }
  return li;
}

function fillList(ul, items, emptyText) {
  ul.replaceChildren();
  if (!items.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = emptyText;
    ul.appendChild(li);
    return;
  }
  for (const item of items) ul.appendChild(item);
}

// ---------------------------------------------------------------- tabs

const TABS = ['dashboard', 'server', 'console', 'whitelist', 'waypoints', 'settings', 'logs'];

function showTab(name) {
  if (!TABS.includes(name)) name = 'dashboard';
  for (const t of TABS) {
    document.getElementById(`page-${t}`).classList.toggle('active', t === name);
  }
  for (const b of document.querySelectorAll('#tabs .tab')) {
    b.classList.toggle('active', b.dataset.tab === name);
  }
}

for (const b of document.querySelectorAll('#tabs .tab')) {
  b.addEventListener('click', () => { location.hash = b.dataset.tab; });
}
window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));

// ---------------------------------------------------------------- status

async function refreshStatus() {
  try {
    const s = await api('/api/status');
    const dot = $('#status-dot');
    if (s.online) {
      if (restarting) {
        restarting = false;
        $('#btn-restart').disabled = false;
        flash('Server is back.');
        refreshPlayers();
        refreshWhitelist();
      }
      dot.className = 'dot online';
      $('#status-text').textContent = 'online';
      $('#st-players').textContent = `${s.players_online} / ${s.players_max}`;
      $('#st-version').textContent = s.version;
      $('#st-motd').textContent = s.motd || '–';
      $('#st-latency').textContent = `${s.latency_ms} ms`;
      refreshTps();
      refreshPlayers();
    } else {
      dot.className = restarting ? 'dot restarting' : 'dot offline';
      $('#status-text').textContent = restarting ? 'restarting…' : 'offline';
      for (const id of ['st-players', 'st-version', 'st-motd', 'st-latency', 'st-tps']) {
        $('#' + id).textContent = '–';
      }
      lastOnline = [];
      renderCards();
      refreshPlayerStats(); // file-based — works even with the server down
    }
  } catch {
    $('#status-dot').className = 'dot';
    $('#status-text').textContent = 'dashboard unreachable?';
  }
  clearTimeout(statusTimer);
  statusTimer = setTimeout(refreshStatus, restarting ? 3000 : 10000);
}

async function refreshTps() {
  try {
    const t = await api('/api/tps');
    $('#st-tps').textContent = 'tps_1m' in t
      ? `${t.tps_1m} / ${t.tps_5m} / ${t.tps_15m} (1m/5m/15m)`
      : stripCodes(t.raw);
  } catch { $('#st-tps').textContent = '–'; }
}

// ---------------------------------------------------------------- sky widget & server info

// Weather-app-style pixel condition icons (sun / moon / rain cloud / storm cloud)
const SUN_ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' shape-rendering='crispEdges'%3E%3Crect x='4' y='4' width='4' height='4' fill='%23ffd83d'/%3E%3Crect x='5' y='1' width='2' height='2' fill='%23ffd83d'/%3E%3Crect x='5' y='9' width='2' height='2' fill='%23ffd83d'/%3E%3Crect x='1' y='5' width='2' height='2' fill='%23ffd83d'/%3E%3Crect x='9' y='5' width='2' height='2' fill='%23ffd83d'/%3E%3Crect x='2' y='2' width='1' height='1' fill='%23ffb300'/%3E%3Crect x='9' y='2' width='1' height='1' fill='%23ffb300'/%3E%3Crect x='2' y='9' width='1' height='1' fill='%23ffb300'/%3E%3Crect x='9' y='9' width='1' height='1' fill='%23ffb300'/%3E%3C/svg%3E";
const MOON_ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' shape-rendering='crispEdges'%3E%3Crect x='3' y='2' width='6' height='8' fill='%23dfe6ff'/%3E%3Crect x='2' y='3' width='8' height='6' fill='%23dfe6ff'/%3E%3Crect x='4' y='4' width='2' height='2' fill='%239aa8d8'/%3E%3Crect x='7' y='6' width='1' height='1' fill='%239aa8d8'/%3E%3Crect x='5' y='7' width='1' height='1' fill='%239aa8d8'/%3E%3C/svg%3E";
const RAIN_ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' shape-rendering='crispEdges'%3E%3Crect x='3' y='1' width='5' height='1' fill='%23e8e8e8'/%3E%3Crect x='2' y='2' width='8' height='2' fill='%23e8e8e8'/%3E%3Crect x='1' y='4' width='10' height='2' fill='%23c9ced6'/%3E%3Crect x='2' y='7' width='1' height='2' fill='%2355aaff'/%3E%3Crect x='5' y='8' width='1' height='2' fill='%2355aaff'/%3E%3Crect x='8' y='7' width='1' height='2' fill='%2355aaff'/%3E%3C/svg%3E";
const THUNDER_ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' shape-rendering='crispEdges'%3E%3Crect x='3' y='1' width='5' height='1' fill='%23aab0b8'/%3E%3Crect x='2' y='2' width='8' height='2' fill='%23aab0b8'/%3E%3Crect x='1' y='4' width='10' height='2' fill='%23868c96'/%3E%3Crect x='6' y='6' width='2' height='2' fill='%23ffd83d'/%3E%3Crect x='5' y='8' width='2' height='2' fill='%23ffd83d'/%3E%3Crect x='4' y='10' width='2' height='1' fill='%23ffd83d'/%3E%3Crect x='2' y='7' width='1' height='2' fill='%2355aaff'/%3E%3Crect x='9' y='7' width='1' height='2' fill='%2355aaff'/%3E%3C/svg%3E";

let lastPhase = 'day';

// weather + day/night → a single weather-app condition (icon, label, css class)
function skyCondition(weather, phase) {
  if (weather === 'thunder') return [THUNDER_ICON, 'Thunderstorm', 'wx-thunder'];
  if (weather === 'rain') return [RAIN_ICON, 'Raining', 'wx-rain'];
  if (weather === 'clear') {
    return phase === 'night'
      ? [MOON_ICON, 'Clear night', 'wx-night']
      : [SUN_ICON, 'Sunny', 'wx-sunny'];
  }
  return [phase === 'night' ? MOON_ICON : SUN_ICON, '', ''];
}

function showWeather(kind, phase = lastPhase) {
  const [icon, label, cls] = skyCondition(kind, phase);
  const img = $('#sky-icon');
  img.src = icon;
  img.hidden = false;
  const wx = $('#sky-weather');
  wx.textContent = label;
  wx.className = cls;
}

async function refreshClock() {
  try {
    const c = await api('/api/clock');
    if (c.phase) lastPhase = c.phase;
    $('#sky-time').textContent = c.online && c.clock ? c.clock : '–';
    $('#sky-day').textContent = c.day ? `Day ${c.day}` : '';
    if (c.weather || c.online) {
      showWeather(c.weather, lastPhase);
    } else {
      $('#sky-icon').hidden = true;
      $('#sky-weather').textContent = '';
    }
  } catch { /* leave the widget as-is */ }
  clearTimeout(clockTimer);
  clockTimer = setTimeout(refreshClock, 10000);
}

async function refreshServerInfo() {
  try {
    const s = await api('/api/serverinfo');
    const rows = [
      ['Day', s.day ?? '–'],
      ['Uptime', s.uptime_s != null ? fmtDuration(s.uptime_s) : '–'],
      ['World size', s.world_size_mb != null
        ? (s.world_size_mb >= 1000 ? `${(s.world_size_mb / 1000).toFixed(2)} GB` : `${s.world_size_mb} MB`)
        : '–'],
      ['Seed', s.seed ?? '–'],
      ['Difficulty', s.difficulty ?? '–'],
      ['MSPT (1m)', s.mspt ? `${s.mspt.avg} avg (${s.mspt.min}–${s.mspt.max})` : '–'],
      ['View distance', s.view_distance ?? '–'],
      ['Sim. distance', s.simulation_distance ?? '–'],
      ['Whitelisted', s.whitelisted ?? '–'],
      ['Banned', s.bans ?? '–'],
    ];
    const dl = $('#world-facts');
    dl.replaceChildren();
    for (const [k, v] of rows) {
      const dt = document.createElement('dt');
      dt.textContent = k;
      const dd = document.createElement('dd');
      dd.textContent = v;
      dl.appendChild(dt);
      dl.appendChild(dd);
    }
  } catch { /* keep the last values */ }
  clearTimeout(infoTimer);
  infoTimer = setTimeout(refreshServerInfo, 30000);
}

// ---------------------------------------------------------------- player data

let lastOnline = [];
let whitelistNames = [];
let playerStats = {}; // name -> {last_seen, hours} from the mounted world files

async function refreshPlayers() {
  try {
    const p = await api('/api/players');
    lastOnline = p.players;
    updatePlayerDatalist(p.players);
  } catch {
    lastOnline = [];
  }
  updateGrabSelect(lastOnline);
  renderCards();
  refreshPlayerStats();
}

async function refreshPlayerStats() {
  try {
    const s = await api('/api/playerstats');
    playerStats = s.players || {};
  } catch { /* keep the last good values */ }
  applyStats();
}

let enabledStats = DEFAULT_CARD_STATS;

// Rebuild the stat rows on every card — cards only fully re-render when the
// player/online sets change, but these numbers tick along every poll. Safe to
// rebuild wholesale: no form state lives inside .pc-stats.
function applyStats() {
  const ctx = { now: Math.floor(Date.now() / 1000), online: false };
  const rows = CARD_STATS.filter(r => enabledStats.includes(r.key));
  for (const card of document.querySelectorAll('.player-card')) {
    const st = playerStats[card.dataset.name] || {};
    ctx.online = card.dataset.online === '1';
    const wrap = card.querySelector('.pc-stats');
    wrap.replaceChildren();
    for (const row of rows) {
      const out = row.fmt(st, ctx);
      const text = typeof out === 'string' ? out : out.text;
      const k = document.createElement('span');
      k.textContent = row.label;
      const v = document.createElement('span');
      v.className = 'pc-stat-v' + (out.warn ? ' warn' : '');
      v.textContent = text;
      wrap.appendChild(k);
      wrap.appendChild(v);
    }
  }
}

async function refreshWhitelist() {
  const ul = $('#whitelist-list');
  try {
    const w = await api('/api/whitelist');
    whitelistNames = w.players;
    fillList(ul, w.players.map(name => row(name, [
      ['remove', 'small', () => whitelistRemove(name)],
    ])), 'whitelist is empty');
  } catch {
    fillList(ul, [], '– rcon unavailable');
  }
  renderCards();
}

async function kick(name) {
  if (!confirm(`Kick ${name}?`)) return;
  try {
    const r = await api('/api/kick', { name });
    flash(stripCodes(r.raw) || `Kicked ${name}.`);
  } catch (e) { flash(e.message, true); }
  refreshPlayers();
}

async function ban(name) {
  if (!confirm(`Ban ${name}? They stay banned until pardoned.`)) return;
  try {
    const r = await api('/api/ban', { name });
    flash(stripCodes(r.raw) || `Banned ${name}.`);
  } catch (e) { flash(e.message, true); }
  refreshPlayers();
}

async function whitelistRemove(name) {
  try {
    const r = await api('/api/whitelist', { action: 'remove', name });
    flash(stripCodes(r.raw) || `Removed ${name}.`);
  } catch (e) { flash(e.message, true); }
  refreshWhitelist();
}

$('#whitelist-form').addEventListener('submit', async e => {
  e.preventDefault();
  const name = $('#whitelist-name').value.trim();
  if (!name) return;
  try {
    const r = await api('/api/whitelist', { action: 'add', name });
    flash(stripCodes(r.raw) || `Added ${name}.`); // raw shows exact-case mismatches
    $('#whitelist-name').value = '';
  } catch (err) { flash(err.message, true); }
  refreshWhitelist();
});

$('#pardon-form').addEventListener('submit', async e => {
  e.preventDefault();
  const name = $('#pardon-name').value.trim();
  if (!name) return;
  try {
    const r = await api('/api/pardon', { name });
    flash(stripCodes(r.raw) || `Pardoned ${name}.`);
    $('#pardon-name').value = '';
  } catch (err) { flash(err.message, true); }
});

$('#broadcast-form').addEventListener('submit', async e => {
  e.preventDefault();
  const message = $('#broadcast-msg').value.trim();
  if (!message) return;
  try {
    await api('/api/broadcast', { message });
    flash('Broadcast sent.');
    $('#broadcast-msg').value = '';
  } catch (err) { flash(err.message, true); }
});

// ---------------------------------------------------------------- waypoints

let waypoints = [];
const DIM_LABEL = {
  'minecraft:overworld': 'overworld',
  'minecraft:the_nether': 'nether',
  'minecraft:the_end': 'end',
};

function setWaypoints(list) {
  waypoints = list;
  renderWaypointList();
  cardsKey = null; // the cards' Teleport dropdowns need a rebuild
  renderCards();
}

async function refreshWaypoints() {
  try {
    setWaypoints((await api('/api/waypoints')).waypoints);
  } catch {
    setWaypoints([]);
  }
}

function renderWaypointList() {
  fillList($('#waypoint-list'), waypoints.map(w =>
    row(`${w.name} — ${w.pos}${w.dim ? ` (${DIM_LABEL[w.dim] || w.dim})` : ''}`, [
      ['remove', 'small', () => waypointRemove(w.name)],
    ])), 'no waypoints yet');
}

async function waypointRemove(name) {
  try {
    const r = await api('/api/waypoints', { action: 'remove', name });
    setWaypoints(r.waypoints);
    flash(`Removed waypoint "${name}".`);
  } catch (e) { flash(e.message, true); }
}

$('#waypoint-form').addEventListener('submit', async e => {
  e.preventDefault();
  const name = $('#wp-name').value.trim();
  const pos = $('#wp-pos').value.trim();
  if (!name || !pos) { flash('A waypoint needs a name and a position.', true); return; }
  try {
    const r = await api('/api/waypoints', { action: 'add', name, pos, dim: $('#wp-dim').value });
    setWaypoints(r.waypoints);
    flash(`Saved waypoint "${name}".`);
    $('#wp-name').value = '';
    $('#wp-pos').value = '';
  } catch (err) { flash(err.message, true); }
});

function updateGrabSelect(names) {
  const sel = $('#wp-grab-player');
  const prev = sel.value;
  sel.replaceChildren(...names.map(n => {
    const o = document.createElement('option');
    o.value = o.textContent = n;
    return o;
  }));
  if (names.includes(prev)) sel.value = prev;
  $('#wp-grab-btn').disabled = !names.length;
}

$('#wp-grab-btn').addEventListener('click', async () => {
  const who = $('#wp-grab-player').value;
  if (!who) return;
  try {
    const p = await api(`/api/position/${who}`);
    $('#wp-pos').value = p.pos;
    if (p.dim) $('#wp-dim').value = p.dim;
    flash(`Grabbed ${who}’s position — name it and add.`);
    $('#wp-name').focus();
  } catch (e) { flash(e.message, true); }
});

// ---------------------------------------------------------------- settings

function renderSettingsChecklist() {
  const wrap = $('#settings-stats');
  wrap.replaceChildren();
  for (const row of CARD_STATS) {
    const label = document.createElement('label');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.value = row.key;
    box.checked = enabledStats.includes(row.key);
    label.appendChild(box);
    label.appendChild(document.createTextNode(` ${row.label}`));
    wrap.appendChild(label);
  }
}

async function refreshSettings() {
  try {
    const s = await api('/api/settings');
    if (Array.isArray(s.card_stats)) enabledStats = s.card_stats;
  } catch { /* keep defaults */ }
  renderSettingsChecklist();
  applyStats();
}

$('#settings-save').addEventListener('click', async () => {
  const picked = [...$('#settings-stats').querySelectorAll('input:checked')].map(b => b.value);
  try {
    const s = await api('/api/settings', { card_stats: picked });
    enabledStats = s.card_stats;
    applyStats();
    flash('Card stats saved.');
  } catch (e) { flash(e.message, true); }
});

$('#settings-defaults').addEventListener('click', () => {
  for (const box of $('#settings-stats').querySelectorAll('input')) {
    box.checked = DEFAULT_CARD_STATS.includes(box.value);
  }
});

// ---------------------------------------------------------------- player cards

// Pixel full-body placeholder for when the avatar proxy has nothing (offline,
// disabled, or an unknown name) — keeps the frontend free of external requests.
const FALLBACK_BODY = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 32' shape-rendering='crispEdges'%3E%3Crect x='4' width='8' height='8' fill='%23b6896c'/%3E%3Crect x='4' width='8' height='2' fill='%232a1f0e'/%3E%3Crect x='5' y='4' width='1' height='1' fill='%23ffffff'/%3E%3Crect x='6' y='4' width='1' height='1' fill='%234a3bb3'/%3E%3Crect x='9' y='4' width='1' height='1' fill='%234a3bb3'/%3E%3Crect x='10' y='4' width='1' height='1' fill='%23ffffff'/%3E%3Crect x='4' y='8' width='8' height='12' fill='%2300a8a8'/%3E%3Crect y='8' width='4' height='12' fill='%23b6896c'/%3E%3Crect x='12' y='8' width='4' height='12' fill='%23b6896c'/%3E%3Crect x='4' y='20' width='8' height='10' fill='%233c44aa'/%3E%3Crect x='4' y='30' width='8' height='2' fill='%236e6e6e'/%3E%3C/svg%3E";

let cardsKey = null; // change detection so open card forms aren't clobbered

function renderCards() {
  const online = new Set(lastOnline);
  const names = [...new Set([...whitelistNames, ...lastOnline])];
  names.sort((a, b) => (online.has(b) - online.has(a)) || a.localeCompare(b));
  const key = names.map(n => `${n}:${online.has(n) ? 1 : 0}`).join(',');
  if (key === cardsKey) return;
  cardsKey = key;
  const wrap = $('#player-cards');
  wrap.replaceChildren();
  if (!names.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = 'nobody on the whitelist yet — add players on the Whitelist tab';
    wrap.appendChild(p);
    return;
  }
  for (const name of names) wrap.appendChild(playerCard(name, online.has(name)));
  applyStats();
}

function playerCard(name, isOnline) {
  const card = document.createElement('div');
  card.className = 'player-card';
  card.dataset.name = name;
  card.dataset.online = isOnline ? '1' : '0';

  const head = document.createElement('div');
  head.className = 'pc-head';
  const img = document.createElement('img');
  img.className = 'avatar';
  img.alt = '';
  img.src = `/api/avatar/${name}?full=1`;
  img.addEventListener('error', () => { img.src = FALLBACK_BODY; }, { once: true });
  head.appendChild(img);

  const id = document.createElement('div');
  id.className = 'pc-id';
  const nm = document.createElement('div');
  nm.className = 'pc-name';
  nm.textContent = name;
  const state = document.createElement('div');
  state.className = 'pc-state';
  const dot = document.createElement('span');
  dot.className = isOnline ? 'dot online' : 'dot';
  state.appendChild(dot);
  state.appendChild(document.createTextNode(isOnline ? ' online' : ' offline'));
  id.appendChild(nm);
  id.appendChild(state);

  const stats = document.createElement('div');
  stats.className = 'pc-stats'; // rows filled by applyStats()
  id.appendChild(stats);

  const mod = document.createElement('div');
  mod.className = 'pc-mod';
  const kickBtn = document.createElement('button');
  kickBtn.type = 'button';
  kickBtn.className = 'small';
  kickBtn.textContent = 'kick';
  kickBtn.disabled = !isOnline;
  kickBtn.addEventListener('click', () => kick(name));
  const banBtn = document.createElement('button');
  banBtn.type = 'button';
  banBtn.className = 'small danger';
  banBtn.textContent = 'ban';
  banBtn.addEventListener('click', () => ban(name));
  mod.appendChild(kickBtn);
  mod.appendChild(banBtn);
  id.appendChild(mod);
  head.appendChild(id);
  card.appendChild(head);

  const form = document.createElement('form');
  form.autocomplete = 'off';
  form.className = 'pc-form';
  const top = document.createElement('div');
  top.className = 'quick-top';
  const sel = document.createElement('select');
  for (const c of CARD_COMMANDS) {
    const o = document.createElement('option');
    o.value = c.name;
    o.textContent = c.label;
    sel.appendChild(o);
  }
  const send = document.createElement('button');
  send.textContent = 'Send';
  top.appendChild(sel);
  top.appendChild(send);
  form.appendChild(top);
  const fields = document.createElement('div');
  fields.className = 'quick-fields';
  form.appendChild(fields);

  const cardSkip = cmd => [cmd.playerField, ...(cmd.cardHide || [])];
  sel.addEventListener('change', () => renderFields(fields, findCommand(sel.value), cardSkip(findCommand(sel.value))));
  renderFields(fields, CARD_COMMANDS[0], cardSkip(CARD_COMMANDS[0]));

  form.addEventListener('submit', e => {
    e.preventDefault();
    const cmd = findCommand(sel.value);
    const values = collectValues(fields);
    values[cmd.playerField] = name;
    // a waypoint destination bypasses the generic builder (execute-in aware)
    const wp = cmd.name === 'tp' && String(values.dest || '').startsWith('wp:')
      ? waypoints.find(w => `wp:${w.name}` === values.dest)
      : null;
    const built = wp ? { command: buildWaypointTp(name, wp) } : buildQuick(cmd, values);
    if (built.error) { flash(built.error, true); return; }
    sendRaw(built.command, cmd.confirm ? cmd.confirm(built.args) : null);
  });

  card.appendChild(form);
  return card;
}

// ---------------------------------------------------------------- restart

const RESTART_CONFIRM =
  'Restart the server?\n\nSaves the world, stops the server; Docker brings it back in under a minute.';

async function doRestart() {
  if (!confirm(RESTART_CONFIRM)) return;
  try {
    await api('/api/restart', {});
    restarting = true;
    $('#btn-restart').disabled = true;
    $('#status-dot').className = 'dot restarting';
    $('#status-text').textContent = 'restarting…';
    consoleLine('stop', '(server is restarting — watch the status card)');
    clearTimeout(statusTimer);
    statusTimer = setTimeout(refreshStatus, 3000);
  } catch (e) { flash(e.message, true); }
}

$('#btn-restart').addEventListener('click', doRestart);

$('#btn-save').addEventListener('click', async () => {
  try {
    const r = await api('/api/save', {});
    flash(stripCodes(r.raw) || 'Saved.');
  } catch (e) { flash(e.message, true); }
});

// ---------------------------------------------------------------- console

function consoleLine(cmd, response, isError) {
  const out = $('#console-out');
  const c = document.createElement('div');
  c.className = 'cmd';
  c.textContent = `> ${cmd}`;
  out.appendChild(c);
  const r = document.createElement('div');
  if (isError) r.className = 'err';
  r.textContent = response || '(no output)';
  out.appendChild(r);
  out.scrollTop = out.scrollHeight;
}

// Single send path for the console, the global panel and the player cards:
// history, confirm, API call, scrollback.
async function sendRaw(command, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  history.push(command);
  histIdx = history.length;
  try {
    const r = await api('/api/command', { command });
    consoleLine(command, stripCodes(r.raw));
    // keep the sky widget honest right away: time reflects live via RCON,
    // weather only hits disk on save — so show the just-set weather directly
    if (/^time /.test(command)) setTimeout(refreshClock, 500);
    const wx = command.match(/^weather (clear|rain|thunder)/);
    if (wx) showWeather(wx[1]);
  } catch (err) {
    consoleLine(command, err.message, true);
  }
}

$('#console-form').addEventListener('submit', e => {
  e.preventDefault();
  const input = $('#console-in');
  const cmd = input.value.trim();
  if (!cmd) return;
  input.value = '';
  if (cmd.replace(/^\//, '') === 'stop') {
    // stop IS the restart button — same confirm, same flow
    history.push(cmd);
    histIdx = history.length;
    doRestart();
    return;
  }
  sendRaw(cmd);
});

$('#console-in').addEventListener('keydown', e => {
  if (e.key === 'ArrowUp') {
    if (histIdx > 0) { histIdx--; e.target.value = history[histIdx]; }
    e.preventDefault();
  } else if (e.key === 'ArrowDown') {
    if (histIdx < history.length - 1) { histIdx++; e.target.value = history[histIdx]; }
    else { histIdx = history.length; e.target.value = ''; }
    e.preventDefault();
  }
});

// ---------------------------------------------------------------- command forms

function ensureDatalist(id, values) {
  let dl = document.getElementById(id);
  if (!dl) {
    dl = document.createElement('datalist');
    dl.id = id;
    document.body.appendChild(dl);
  }
  dl.replaceChildren(...values.map(v => {
    const o = document.createElement('option');
    o.value = v;
    return o;
  }));
}

function updatePlayerDatalist(names) {
  ensureDatalist('dl-players', names); // online players only — selectors can be typed
}

const CUSTOM = '__custom__';

// The "Custom…" free-text escape shared by choice and dest dropdowns.
function customEscape(sel, f) {
  const customInput = document.createElement('input');
  customInput.type = 'text';
  customInput.spellcheck = false;
  customInput.placeholder = f.placeholder || 'exact id';
  customInput.hidden = true;
  customInput.dataset.customFor = f.key;
  sel.addEventListener('change', () => {
    customInput.hidden = sel.value !== CUSTOM;
    if (!customInput.hidden) customInput.focus();
  });
  return customInput;
}

// Renders a command's argument fields into `wrap`, skipping keys in `skip`
// (cards use that to hide the auto-filled player arg). Shared by the global
// panel and every player card.
function renderFields(wrap, cmd, skip = []) {
  wrap.replaceChildren();
  for (const f of cmd.fields) {
    if (skip.includes(f.key)) continue;
    const div = document.createElement('div');
    div.className = 'qf';
    const label = document.createElement('label');
    label.textContent = f.required ? `${f.label} *` : f.label;
    div.appendChild(label);
    if (f.type === 'dest') {
      // teleport destination: online players + saved waypoints + Custom
      const sel = document.createElement('select');
      const blank = document.createElement('option');
      blank.value = '';
      blank.textContent = 'choose…';
      sel.appendChild(blank);
      const groups = [['Players', lastOnline.map(n => [n, n])],
                      ['Waypoints', waypoints.map(w => [`wp:${w.name}`, w.name])]];
      for (const [title, opts] of groups) {
        if (!opts.length) continue;
        const g = document.createElement('optgroup');
        g.label = title;
        for (const [value, text] of opts) {
          const o = document.createElement('option');
          o.value = value;
          o.textContent = text;
          g.appendChild(o);
        }
        sel.appendChild(g);
      }
      const custom = document.createElement('option');
      custom.value = CUSTOM;
      custom.textContent = 'Custom…';
      sel.appendChild(custom);
      sel.dataset.key = f.key;
      div.appendChild(sel);
      const customInput = customEscape(sel, f);
      customInput.setAttribute('list', 'dl-players');
      div.appendChild(customInput);
      wrap.appendChild(div);
      continue;
    }
    if (f.type === 'select' || f.type === 'choice') {
      const sel = document.createElement('select');
      if (f.type === 'choice') {
        // friendly labels, exact-id values, plus a Custom escape hatch
        const blank = document.createElement('option');
        blank.value = '';
        blank.textContent = f.required ? 'choose…' : '—';
        sel.appendChild(blank);
        for (const c of SUGGESTIONS[f.choices]) {
          const o = document.createElement('option');
          o.value = c.id;
          o.textContent = c.label;
          sel.appendChild(o);
        }
        const custom = document.createElement('option');
        custom.value = CUSTOM;
        custom.textContent = 'Custom…';
        sel.appendChild(custom);
      } else {
        for (const opt of f.options) {
          const o = document.createElement('option');
          o.value = o.textContent = opt;
          sel.appendChild(o);
        }
      }
      sel.dataset.key = f.key;
      div.appendChild(sel);
      if (f.type === 'choice') {
        div.appendChild(customEscape(sel, f));
      }
    } else {
      const input = document.createElement('input');
      input.type = 'text'; // stays text even for numbers: ticks/selectors are fine
      input.spellcheck = false;
      if (f.type === 'number') input.inputMode = 'numeric';
      if (f.type === 'player') input.setAttribute('list', 'dl-players');
      if (f.placeholder) input.placeholder = f.placeholder;
      input.dataset.key = f.key;
      div.appendChild(input);
    }
    wrap.appendChild(div);
  }
}

// Collects {key: value} from a fields container, resolving the Custom… escape.
function collectValues(wrap) {
  const values = {};
  for (const el of wrap.querySelectorAll('[data-key]')) {
    let v = el.value;
    if (v === CUSTOM) {
      const custom = wrap.querySelector(`[data-custom-for="${el.dataset.key}"]`);
      v = custom ? custom.value : '';
    }
    values[el.dataset.key] = v;
  }
  return values;
}

// ---------------------------------------------------------------- global panel

const quickSelect = $('#quick-cmd');
for (const c of GLOBAL_COMMANDS) {
  const o = document.createElement('option');
  o.value = c.name;
  o.textContent = c.label;
  quickSelect.appendChild(o);
}

function renderGlobalFields(cmd) {
  renderFields($('#quick-fields'), cmd);
  $('#quick-desc').textContent = cmd.desc;
}

quickSelect.addEventListener('change', () => renderGlobalFields(findCommand(quickSelect.value)));

$('#quick-form').addEventListener('submit', e => {
  e.preventDefault();
  const cmd = findCommand(quickSelect.value);
  const built = buildQuick(cmd, collectValues($('#quick-fields')));
  if (built.error) { flash(built.error, true); return; }
  sendRaw(built.command, cmd.confirm ? cmd.confirm(built.args) : null);
});

for (const p of PRESETS) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'small';
  b.textContent = p.label;
  b.addEventListener('click', () => sendRaw(p.command, p.confirm));
  $('#preset-row').appendChild(b);
}

// ---------------------------------------------------------------- logs

async function refreshLogs() {
  try {
    const l = await api('/api/logs?lines=100');
    const out = $('#logs-out');
    out.textContent = l.error ? l.error : l.lines.join('\n');
    out.scrollTop = out.scrollHeight;
  } catch (e) { $('#logs-out').textContent = e.message; }
}

$('#logs-refresh').addEventListener('click', refreshLogs);
$('#logs-auto').addEventListener('change', e => {
  clearInterval(logsTimer);
  if (e.target.checked) logsTimer = setInterval(refreshLogs, 5000);
});

// ---------------------------------------------------------------- boot

showTab(location.hash.slice(1));
updatePlayerDatalist([]);
updateGrabSelect([]);
renderGlobalFields(GLOBAL_COMMANDS[0]);
renderCards();
refreshSettings();
refreshWaypoints();
refreshStatus();
refreshClock();
refreshServerInfo();
refreshWhitelist();
refreshLogs();
