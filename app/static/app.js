import { QUICK_COMMANDS, PRESETS, SUGGESTIONS, findCommand, buildQuick } from './quick-commands.js';

const $ = s => document.querySelector(s);
const stripCodes = s => String(s).replace(/§./g, '');

let restarting = false;
let statusTimer = null;
let logsTimer = null;
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

// ---------------------------------------------------------------- status card

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

// ---------------------------------------------------------------- players & whitelist

async function refreshPlayers() {
  const ul = $('#online-list');
  try {
    const p = await api('/api/players');
    updatePlayerDatalist(p.players);
    fillList(ul, p.players.map(name => row(name, [
      ['kick', 'small', () => kick(name)],
      ['ban', 'small danger', () => ban(name)],
    ])), 'nobody online');
  } catch {
    fillList(ul, [], '– rcon unavailable');
  }
}

async function refreshWhitelist() {
  const ul = $('#whitelist-list');
  try {
    const w = await api('/api/whitelist');
    fillList(ul, w.players.map(name => row(name, [
      ['remove', 'small', () => whitelistRemove(name)],
    ])), 'whitelist is empty');
  } catch {
    fillList(ul, [], '– rcon unavailable');
  }
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

// Single send path for the console and the quick panel: history, confirm,
// API call, scrollback.
async function sendRaw(command, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  history.push(command);
  histIdx = history.length;
  try {
    const r = await api('/api/command', { command });
    consoleLine(command, stripCodes(r.raw));
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

// ---------------------------------------------------------------- quick commands

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

function renderQuickFields(cmd) {
  const wrap = $('#quick-fields');
  wrap.replaceChildren();
  for (const f of cmd.fields) {
    const div = document.createElement('div');
    div.className = 'qf';
    const label = document.createElement('label');
    label.textContent = f.required ? `${f.label} *` : f.label;
    div.appendChild(label);
    let input;
    if (f.type === 'select') {
      input = document.createElement('select');
      for (const opt of f.options) {
        const o = document.createElement('option');
        o.value = o.textContent = opt;
        input.appendChild(o);
      }
    } else {
      input = document.createElement('input');
      input.type = 'text'; // stays text even for numbers: ticks/selectors are fine
      input.spellcheck = false;
      if (f.type === 'number') input.inputMode = 'numeric';
      if (f.type === 'player') input.setAttribute('list', 'dl-players');
      else if (f.suggest) {
        ensureDatalist(`dl-${f.suggest}`, SUGGESTIONS[f.suggest]);
        input.setAttribute('list', `dl-${f.suggest}`);
      }
      if (f.placeholder) input.placeholder = f.placeholder;
    }
    input.dataset.key = f.key;
    div.appendChild(input);
    wrap.appendChild(div);
  }
  $('#quick-desc').textContent = cmd.desc;
}

const quickSelect = $('#quick-cmd');
for (const c of QUICK_COMMANDS) {
  const o = document.createElement('option');
  o.value = c.name;
  o.textContent = c.label;
  quickSelect.appendChild(o);
}
quickSelect.addEventListener('change', () => renderQuickFields(findCommand(quickSelect.value)));

$('#quick-form').addEventListener('submit', e => {
  e.preventDefault();
  const cmd = findCommand(quickSelect.value);
  const values = {};
  for (const input of $('#quick-fields').querySelectorAll('[data-key]')) {
    values[input.dataset.key] = input.value;
  }
  const built = buildQuick(cmd, values);
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

updatePlayerDatalist([]);
renderQuickFields(QUICK_COMMANDS[0]);
refreshStatus();
refreshWhitelist();
refreshLogs();
