// Card stat registry + formatter tests: node --test (bare, from repo root).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CARD_STATS, DEFAULT_CARD_STATS, fmtDuration, fmtDistance, prettyId, timeAgo } from '../app/static/stats.js';

const row = key => CARD_STATS.find(r => r.key === key);

test('registry is well-formed with unique keys', () => {
  assert.ok(CARD_STATS.length >= 18);
  const keys = CARD_STATS.map(r => r.key);
  assert.equal(new Set(keys).size, keys.length);
  for (const r of CARD_STATS) {
    assert.ok(r.key && r.label, r.key);
    assert.equal(typeof r.fmt, 'function', r.key);
  }
});

test('defaults are a subset of the registry', () => {
  const keys = new Set(CARD_STATS.map(r => r.key));
  for (const k of DEFAULT_CARD_STATS) assert.ok(keys.has(k), k);
  assert.ok(DEFAULT_CARD_STATS.includes('last_seen'));
  assert.ok(DEFAULT_CARD_STATS.includes('hours'));
});

test('every row degrades to a dash on empty stats', () => {
  const ctx = { online: false, now: 1_700_000_000 };
  for (const r of CARD_STATS) {
    const out = r.fmt({}, ctx);
    const text = typeof out === 'string' ? out : out.text;
    assert.ok(typeof text === 'string' && text.length, r.key);
  }
});

test('formatters', () => {
  assert.equal(fmtDuration(90), '1 min');
  assert.equal(fmtDuration(3700), '1h 1m');
  assert.equal(fmtDuration(90000), '1d 1h');
  assert.equal(fmtDistance(250000), '2.5 km');
  assert.equal(fmtDistance(4500), '45 m');
  assert.equal(prettyId('minecraft:cave_spider'), 'Cave Spider');
  assert.equal(timeAgo(30), 'just now');
  assert.equal(timeAgo(2 * 86400 + 60), '2 days ago');
});

test('stat rows format real values', () => {
  const ctx = { online: false, now: 1000 };
  assert.equal(row('last_seen').fmt({ last_seen: 1000 - 120 }, ctx), '2 min ago');
  assert.equal(row('last_seen').fmt({ last_seen: 5 }, { online: true, now: 1000 }), 'now');
  assert.equal(row('nemesis').fmt({ nemesis: { id: 'minecraft:zombie', count: 12 } }, ctx), 'Zombie (12)');
  assert.equal(row('damage').fmt({ damage_dealt: 12340, damage_taken: 4680 }, ctx), '617 / 234 hearts');
  assert.equal(row('crafted').fmt({ crafted_total: 1234, enchanted: 56 }, ctx), '1,234 / 56');
  assert.equal(row('vitals').fmt({ health: 9.5, food: 18 }, ctx), '9.5/20 · 18/20');
  assert.equal(row('mined').fmt({ mined_total: 100000 }, ctx), '100,000');
});

test('since-sleep flags phantom danger past one real hour', () => {
  const ctx = { online: true, now: 0 };
  assert.equal(row('since_sleep').fmt({ since_sleep_s: 120 }, ctx).warn, false);
  assert.equal(row('since_sleep').fmt({ since_sleep_s: 4000 }, ctx).warn, true);
});
