// Biome catalog structure + give-builder tests: node --test (bare).
// The ids themselves are additionally swept against a live Paper 26.2 server
// whenever the list changes (give @p <id> must parse) — see CLAUDE.md.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BIOME_ITEMS, findBiomeItem, buildBiomeGive } from '../app/static/biomes.js';

test('catalog is well-formed', () => {
  assert.ok(BIOME_ITEMS.length >= 15);
  const allIds = new Set();
  for (const group of BIOME_ITEMS) {
    assert.ok(group.biome, 'group name');
    assert.ok(group.items.length >= 3, group.biome);
    const inGroup = new Set();
    for (const item of group.items) {
      assert.match(item.id, /^minecraft:[a-z0-9_]+$/, `${group.biome}: ${item.id}`);
      assert.ok(item.label, item.id);
      assert.ok(!inGroup.has(item.id), `${group.biome} repeats ${item.id}`);
      inGroup.add(item.id);
      allIds.add(item.id);
    }
  }
  assert.ok(allIds.size >= 120, `${allIds.size} unique items`);
});

test('renamed-this-generation ids are the current ones', () => {
  assert.ok(findBiomeItem('minecraft:short_grass'), 'short_grass (was grass)');
  assert.ok(findBiomeItem('minecraft:turtle_scute'), 'turtle_scute (was scute)');
  assert.equal(findBiomeItem('minecraft:grass'), null);
});

test('buildBiomeGive emits plain give commands', () => {
  assert.equal(buildBiomeGive('RobGreen', 'minecraft:slime_ball'), 'give RobGreen minecraft:slime_ball');
  assert.equal(buildBiomeGive('alice', 'minecraft:sand', 64), 'give alice minecraft:sand 64');
});
