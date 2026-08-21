// Frontend command-builder tests: node --test tests/
// Asserts the exact strings the Quick commands panel sends to /api/command.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { QUICK_COMMANDS, PRESETS, SUGGESTIONS, findCommand, buildQuick } from '../app/static/quick-commands.js';

const cases = [
  ['gamemode', { mode: 'creative', player: 'alice' }, 'gamemode creative alice'],
  ['give', { player: 'alice', item: 'minecraft:iron_pickaxe', count: '3' }, 'give alice minecraft:iron_pickaxe 3'],
  ['give', { player: 'alice', item: 'minecraft:diamond' }, 'give alice minecraft:diamond'],
  ['tp', { player: 'alice', dest: 'bob' }, 'tp alice bob'],
  ['tp', { player: 'alice', dest: '100 64 -200' }, 'tp alice 100 64 -200'],
  ['time', { value: 'day' }, 'time set day'],
  ['time', { value: '6000' }, 'time set 6000'],
  ['weather', { kind: 'thunder', duration: '120' }, 'weather thunder 120'],
  ['weather', { kind: 'clear' }, 'weather clear'],
  ['gamerule', { rule: 'keep_inventory', value: 'true' }, 'gamerule keep_inventory true'],
  ['gamerule', { rule: 'keep_inventory' }, 'gamerule keep_inventory'],
  ['difficulty', { level: 'hard' }, 'difficulty hard'],
  ['effect', { player: 'alice', effect: 'speed', seconds: '60', amplifier: '1' }, 'effect give alice speed 60 1'],
  ['effect', { player: 'alice', effect: 'speed' }, 'effect give alice speed'],
  ['effect', { player: 'alice', effect: 'speed', amplifier: '2' }, 'effect give alice speed 30 2'],
  ['clear', { player: 'alice' }, 'clear alice'],
  ['clear', { player: 'alice', item: 'minecraft:torch', count: '5' }, 'clear alice minecraft:torch 5'],
  ['clear', { player: 'alice', count: '5' }, 'clear alice'], // count without item is dropped
  ['kill', { target: '@e[type=!player]' }, 'kill @e[type=!player]'],
  ['summon', { entity: 'zombie', at: 'alice' }, 'execute at alice run summon zombie ~ ~ ~'],
  ['summon', { entity: 'creeper', pos: '100 64 -200' }, 'summon creeper 100 64 -200'],
  ['msg', { player: 'alice', message: 'restarting in 5 minutes' }, 'msg alice restarting in 5 minutes'],
  ['experience', { player: 'alice', amount: '10', unit: 'levels' }, 'experience add alice 10 levels'],
];

for (const [name, args, expected] of cases) {
  test(`${name} → "${expected}"`, () => {
    const r = buildQuick(findCommand(name), args);
    assert.equal(r.error, undefined);
    assert.equal(r.command, expected);
  });
}

test('required fields are enforced', () => {
  assert.match(buildQuick(findCommand('give'), { player: 'alice' }).error, /required/);
  assert.match(buildQuick(findCommand('kill'), {}).error, /required/);
  // gamemode without a player fails over RCON ("A player is required") — the
  // UI must require it up front
  assert.match(buildQuick(findCommand('gamemode'), { mode: 'survival' }).error, /required/);
});

test('summon demands a position (RCON has no executor)', () => {
  assert.match(buildQuick(findCommand('summon'), { entity: 'zombie' }).error, /at player.*coordinates/i);
});

test('all 13 commands are well-formed', () => {
  assert.equal(QUICK_COMMANDS.length, 13);
  for (const c of QUICK_COMMANDS) {
    assert.ok(c.name && c.label && c.desc, c.name);
    assert.ok(Array.isArray(c.fields) && c.fields.length > 0, c.name);
    assert.equal(typeof c.build, 'function', c.name);
  }
});

test('every suggestion entry pairs an exact id with a friendly label', () => {
  for (const [key, list] of Object.entries(SUGGESTIONS)) {
    assert.ok(list.length > 0, key);
    for (const e of list) assert.ok(e.id && e.label, `${key}: ${JSON.stringify(e)}`);
  }
});

test('choice fields reference real suggestion lists', () => {
  for (const c of QUICK_COMMANDS) {
    for (const f of c.fields) {
      if (f.type === 'choice') assert.ok(Array.isArray(SUGGESTIONS[f.choices]), `${c.name}.${f.key}`);
    }
  }
});

test('scopes split 9 player / 4 global, with valid card wiring', () => {
  const counts = { player: 0, global: 0 };
  for (const c of QUICK_COMMANDS) {
    assert.ok(c.scope === 'player' || c.scope === 'global', `${c.name} scope`);
    counts[c.scope]++;
    if (c.scope === 'player') {
      // the card auto-fills and hides this field — it must exist
      assert.ok(c.fields.some(f => f.key === c.playerField), `${c.name} playerField`);
      for (const h of c.cardHide || []) {
        assert.ok(c.fields.some(f => f.key === h), `${c.name} cardHide ${h}`);
      }
    } else {
      assert.equal(c.playerField, undefined, c.name);
      assert.ok(!c.fields.some(f => f.type === 'player'), `${c.name}: global command with a player field`);
    }
  }
  assert.equal(counts.player, 9);
  assert.equal(counts.global, 4);
});

test('presets are well-formed and kill-all is confirm-gated', () => {
  for (const p of PRESETS) assert.ok(p.label && p.command, p.label);
  assert.ok(PRESETS.find(p => p.command === 'kill @e[type=!player]').confirm);
});
