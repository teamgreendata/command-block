// Analytics-transform tests for the player detail page: node --test (bare).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { topEntries, deathAnalysis, movementRows, damageRows, fmtCustomValue, leftoverCustom } from '../app/static/detail.js';

test('topEntries sorts, cuts and scales bars to the max', () => {
  const top = topEntries({ 'minecraft:stone': 500, 'minecraft:diamond_ore': 5, 'minecraft:dirt': 250 }, 2);
  assert.deepEqual(top.rows.map(r => r.label), ['Stone', 'Dirt']);
  assert.equal(top.rows[0].pct, 100);
  assert.equal(top.rows[1].pct, 50);
  assert.equal(top.rows[0].text, '500');
  assert.equal(top.total, 755);
  assert.equal(top.more, 1);
});

test('tiny non-zero entries keep a visible sliver of bar', () => {
  const top = topEntries({ a: 10000, b: 1 }, 5);
  assert.equal(top.rows[1].pct, 2);
});

test('deathAnalysis derives the environmental remainder', () => {
  const d = deathAnalysis({
    'minecraft:custom': { 'minecraft:deaths': 12 },
    'minecraft:killed_by': { 'minecraft:skeleton': 4, 'minecraft:zombie': 3 },
  });
  assert.equal(d.total, 12);
  assert.equal(d.byMob.rows[0].label, 'Skeleton');
  assert.equal(d.environmental, 5); // fall/lava/drowning — not itemized by the game
});

test('deathAnalysis handles a spotless record', () => {
  const d = deathAnalysis({});
  assert.equal(d.total, 0);
  assert.equal(d.environmental, 0);
  assert.deepEqual(d.byMob.rows, []);
});

test('movementRows formats every _one_cm counter', () => {
  const rows = movementRows({
    'minecraft:walk_one_cm': 250000,
    'minecraft:swim_one_cm': 4500,
    'minecraft:jump': 99, // not a distance
  });
  assert.deepEqual(rows.map(r => [r.label, r.text]), [['Walk', '2.5 km'], ['Swim', '45 m']]);
  assert.equal(rows[0].pct, 100);
});

test('damageRows converts to hearts and skips zeros', () => {
  const rows = damageRows({ 'minecraft:damage_dealt': 12340, 'minecraft:damage_blocked_by_shield': 0 });
  assert.deepEqual(rows, [{ label: 'Dealt', text: '617 hearts' }]);
});

test('fmtCustomValue picks distance/duration/count by key shape', () => {
  assert.equal(fmtCustomValue('minecraft:climb_one_cm', 250000), '2.5 km');
  assert.equal(fmtCustomValue('minecraft:sneak_time', 72000), '1h 0m');
  assert.equal(fmtCustomValue('minecraft:time_since_rest', 24000), '20 min');
  assert.equal(fmtCustomValue('minecraft:jump', 1234), '1,234');
});

test('leftoverCustom excludes covered keys but keeps the long tail', () => {
  const rows = leftoverCustom({
    'minecraft:deaths': 5,               // covered by the deaths panel
    'minecraft:damage_taken': 100,       // covered by the combat panel
    'minecraft:walk_one_cm': 5,          // covered by movement
    'minecraft:open_chest': 321,
    'minecraft:animals_bred': 7,
  });
  assert.deepEqual(rows.map(r => r.label), ['Animals Bred', 'Open Chest']);
  assert.equal(rows.find(r => r.label === 'Open Chest').text, '321');
});
