// Item-forge registry + give-builder tests: node --test (bare, from repo root).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ENCHANTS, FORGE_ITEMS, findForgeItem, forgeEnchants, buildForgeGive } from '../app/static/forge.js';

test('every forge item is unique, labeled and grouped', () => {
  assert.ok(FORGE_ITEMS.length >= 60);
  const ids = FORGE_ITEMS.map(i => i.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const i of FORGE_ITEMS) {
    assert.ok(i.id.startsWith('minecraft:'), i.id);
    assert.ok(i.label && i.group, i.id);
    assert.ok(forgeEnchants(i.id).length >= 2, `${i.id} has no enchant list`);
  }
});

test('every referenced enchantment exists with a sane max level', () => {
  for (const i of FORGE_ITEMS) {
    for (const e of forgeEnchants(i.id)) {
      assert.ok(ENCHANTS[e.id], `${i.id} -> ${e.id}`);
      assert.ok(e.max >= 1 && e.max <= 5, e.id);
    }
  }
});

test('item lists are sensible', () => {
  const sword = forgeEnchants('minecraft:netherite_sword').map(e => e.id);
  assert.ok(sword.includes('sharpness') && sword.includes('mending'));
  assert.ok(!sword.includes('protection'));
  const boots = forgeEnchants('minecraft:diamond_boots').map(e => e.id);
  assert.ok(boots.includes('feather_falling') && boots.includes('soul_speed'));
  assert.ok(forgeEnchants('minecraft:mace').map(e => e.id).includes('density'));
  assert.equal(findForgeItem('minecraft:turtle_helmet').kind, 'helmet');
});

test('buildForgeGive emits the exact validated component syntax', () => {
  assert.equal(
    buildForgeGive('RobGreen', 'minecraft:netherite_sword',
      [{ id: 'sharpness', level: 5 }, { id: 'mending', level: 1 }]),
    'give RobGreen minecraft:netherite_sword[minecraft:enchantments='
      + '{"minecraft:sharpness":5,"minecraft:mending":1}]');
  assert.equal(buildForgeGive('alice', 'minecraft:shield', []), 'give alice minecraft:shield');
  assert.equal(buildForgeGive('alice', 'minecraft:bow', [{ id: 'power', level: 3 }], 2),
    'give alice minecraft:bow[minecraft:enchantments={"minecraft:power":3}] 2');
});
