// Analytics transforms for the per-player detail page. Pure functions over the
// raw stat sections from /api/playerdetail — no DOM, so node --test covers the
// breakdown math and the exact strings rendered.
import { fmtDistance, fmtDuration, prettyId } from './stats.js';

const num = v => (v ?? 0).toLocaleString('en-US');

// One stat section ({id: count}) -> bar-table rows. pct is relative to the
// largest entry (bar width); total/more summarize what the cut hides.
export function topEntries(section = {}, n = 12) {
  const entries = Object.entries(section).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  const max = entries.length ? entries[0][1] : 0;
  return {
    rows: entries.slice(0, n).map(([id, count]) => ({
      id,
      label: prettyId(id),
      count,
      text: num(count),
      pct: max ? Math.max(2, Math.round(count / max * 100)) : 0,
    })),
    total,
    more: Math.max(0, entries.length - n),
  };
}

// Vanilla only itemizes deaths caused by entities (killed_by); the remainder
// is environmental (fall, lava, drowning, void…) — derived, not itemized.
export function deathAnalysis(sections = {}) {
  const total = (sections['minecraft:custom'] || {})['minecraft:deaths'] || 0;
  const byMob = topEntries(sections['minecraft:killed_by'] || {}, 12);
  return { total, byMob, environmental: Math.max(0, total - byMob.total) };
}

export function movementRows(custom = {}) {
  const entries = Object.entries(custom)
    .filter(([k]) => k.endsWith('_one_cm'))
    .sort((a, b) => b[1] - a[1]);
  const max = entries.length ? entries[0][1] : 0;
  return entries.map(([k, cm]) => ({
    label: prettyId(k.replace(/_one_cm$/, '')),
    cm,
    text: fmtDistance(cm),
    pct: max ? Math.max(2, Math.round(cm / max * 100)) : 0,
  }));
}

// Damage counters, shown in hearts (10 stat units = 1 heart).
const DAMAGE_ROWS = [
  ['minecraft:damage_dealt', 'Dealt'],
  ['minecraft:damage_taken', 'Taken'],
  ['minecraft:damage_blocked_by_shield', 'Blocked by shield'],
  ['minecraft:damage_absorbed', 'Absorbed'],
  ['minecraft:damage_resisted', 'Resisted'],
];

export function damageRows(custom = {}) {
  return DAMAGE_ROWS
    .filter(([k]) => custom[k])
    .map(([k, label]) => ({ label, text: `${num(Math.round(custom[k] / 20))} hearts` }));
}

// World-object interactions get their own panel: chests opened, workstations
// used, villagers talked to, note blocks played…
const INTERACTION_KEYS = new Set([
  'talked_to_villager', 'traded_with_villager', 'bell_ring', 'play_noteblock',
  'tune_noteblock', 'play_record', 'pot_flower', 'eat_cake_slice',
  'trigger_trapped_chest', 'use_cauldron', 'fill_cauldron',
  'clean_armor', 'clean_banner', 'clean_shulker_box',
]);

function isInteraction(bare) {
  return bare.startsWith('interact_with_') || bare.startsWith('open_')
    || bare.startsWith('inspect_') || INTERACTION_KEYS.has(bare);
}

export function interactionRows(custom = {}, n = 12) {
  const section = {};
  for (const [k, v] of Object.entries(custom)) {
    if (isInteraction(k.replace(/^minecraft:/, ''))) section[k] = v;
  }
  const top = topEntries(section, n);
  for (const r of top.rows) {
    // "interact_with_crafting_table" → "Crafting Table"; others keep the verb
    r.label = prettyId(r.id.replace(/^minecraft:/, '').replace(/^interact_with_/, ''));
  }
  return top;
}

// Custom counters in ticks (20/s) that read as durations.
const TICK_KEYS = /(^|_)(time|one_minute)($|_)|_since_/;
// Covered by a dedicated spot on the page — everything else lands in "More".
const COVERED = new Set([
  'minecraft:deaths', 'minecraft:play_time', 'minecraft:play_one_minute',
  'minecraft:mob_kills', 'minecraft:player_kills',
]);

export function fmtCustomValue(key, v) {
  if (key.endsWith('_one_cm')) return fmtDistance(v);
  if (TICK_KEYS.test(key.replace(/^minecraft:/, ''))) return fmtDuration(Math.floor(v / 20));
  return num(v);
}

export function leftoverCustom(custom = {}) {
  return Object.entries(custom)
    .filter(([k]) => !k.endsWith('_one_cm') && !k.startsWith('minecraft:damage_')
      && !COVERED.has(k) && !isInteraction(k.replace(/^minecraft:/, '')))
    .map(([k, v]) => ({
      label: prettyId(k.replace(/^minecraft:/, '')),
      text: fmtCustomValue(k, v),
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}
