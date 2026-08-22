// Player-card stat registry: every stat the dashboard can show, with its
// formatting. Pure data + pure functions (no DOM) so node --test covers the
// exact strings the cards render. The Settings tab checks/unchecks these keys;
// the chosen set persists server-side via /api/settings.

export function fmtDuration(s) {
  const d = Math.floor(s / 86400);
  const h = Math.floor(s % 86400 / 3600);
  const m = Math.floor(s % 3600 / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m} min`;
}

export function timeAgo(secondsAgo) {
  if (secondsAgo < 60) return 'just now';
  const m = Math.floor(secondsAgo / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? 'yesterday' : `${d} days ago`;
}

export function fmtDistance(cm) {
  return cm >= 100000 ? `${(cm / 100000).toFixed(1)} km` : `${Math.round(cm / 100)} m`;
}

export function prettyId(id) {
  return String(id)
    .replace(/^minecraft:/, '')
    .replace(/_/g, ' ')
    .replace(/\b[a-z]/g, c => c.toUpperCase());
}

const num = v => v != null ? v.toLocaleString('en-US') : '–';
const hearts = units => Math.round(units / 20).toLocaleString('en-US'); // 10 units = ½ heart
const topEntry = e => e ? `${prettyId(e.id)} (${num(e.count)})` : '–';

// fmt(stats, ctx) -> string, or {text, warn} for values worth flagging red.
// stats may be {} (no data yet) — every formatter must degrade to '–'.
export const CARD_STATS = [
  { key: 'last_seen', label: 'Last seen',
    fmt: (s, c) => c.online ? 'now' : (s.last_seen ? timeAgo(c.now - s.last_seen) : '–') },
  { key: 'hours', label: 'Played', fmt: s => s.hours != null ? `${s.hours} h` : '–' },
  { key: 'deaths', label: 'Deaths', fmt: s => num(s.deaths) },
  { key: 'life', label: 'This life',
    fmt: s => s.life_s != null ? fmtDuration(s.life_s) : '–' },
  { key: 'since_sleep', label: 'Since sleep',
    // 3600s real = 3 in-game days = phantoms incoming
    fmt: s => s.since_sleep_s != null
      ? { text: fmtDuration(s.since_sleep_s), warn: s.since_sleep_s >= 3600 }
      : '–' },
  { key: 'sleeps', label: 'Times slept', fmt: s => num(s.sleep_count) },
  { key: 'mob_kills', label: 'Mob kills', fmt: s => num(s.mob_kills) },
  { key: 'player_kills', label: 'Player kills', fmt: s => num(s.player_kills) },
  { key: 'damage', label: 'Dmg dealt/taken',
    fmt: s => s.damage_dealt != null
      ? `${hearts(s.damage_dealt)} / ${hearts(s.damage_taken)} hearts`
      : '–' },
  { key: 'nemesis', label: 'Nemesis', fmt: s => topEntry(s.nemesis) },
  { key: 'top_victim', label: 'Top victim', fmt: s => topEntry(s.top_victim) },
  { key: 'distance', label: 'Traveled',
    fmt: s => s.distance_cm != null ? fmtDistance(s.distance_cm) : '–' },
  { key: 'elytra', label: 'Elytra flown',
    fmt: s => s.aviate_cm != null ? fmtDistance(s.aviate_cm) : '–' },
  { key: 'mined', label: 'Blocks mined', fmt: s => num(s.mined_total) },
  { key: 'diamonds', label: 'Diamonds mined', fmt: s => num(s.diamonds) },
  { key: 'crafted', label: 'Crafted/ench.',
    fmt: s => s.crafted_total != null ? `${num(s.crafted_total)} / ${num(s.enchanted)}` : '–' },
  { key: 'husbandry', label: 'Fish/bred/trades',
    fmt: s => s.fish_caught != null
      ? `${num(s.fish_caught)} / ${num(s.animals_bred)} / ${num(s.trades)}`
      : '–' },
  { key: 'xp', label: 'XP level', fmt: s => s.xp_level != null ? String(s.xp_level) : '–' },
  { key: 'vitals', label: 'HP / food',
    fmt: s => s.health != null ? `${s.health}/20 · ${s.food}/20` : '–' },
];

// what cards show until the user saves a selection on the Settings tab
export const DEFAULT_CARD_STATS = [
  'last_seen', 'hours', 'deaths', 'life', 'since_sleep', 'mob_kills',
  'nemesis', 'top_victim', 'distance', 'mined', 'diamonds', 'crafted',
];
