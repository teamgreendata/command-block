// Declarative specs for the Quick commands panel. Pure data + pure build
// functions — no DOM — so node --test can exercise the exact strings the UI
// sends through /api/command.
//
// RCON has no executor (no position, no "self"), which shapes three commands:
// clear/kill require an explicit target, and summon needs a position — either
// coordinates or `execute at <player> run summon … ~ ~ ~`.

export const SUGGESTIONS = {
  players: ['@a', '@r', '@e[type=!player]'],
  items: [
    'minecraft:diamond', 'minecraft:iron_pickaxe', 'minecraft:diamond_pickaxe',
    'minecraft:diamond_sword', 'minecraft:netherite_ingot', 'minecraft:golden_apple',
    'minecraft:enchanted_golden_apple', 'minecraft:elytra', 'minecraft:ender_pearl',
    'minecraft:shulker_box', 'minecraft:experience_bottle', 'minecraft:cooked_beef',
    'minecraft:bread', 'minecraft:torch', 'minecraft:oak_planks',
  ],
  effects: [
    'speed', 'strength', 'regeneration', 'resistance', 'fire_resistance',
    'water_breathing', 'night_vision', 'invisibility', 'jump_boost', 'haste',
    'saturation', 'slow_falling', 'instant_health', 'glowing',
  ],
  entities: [
    'zombie', 'skeleton', 'creeper', 'spider', 'enderman', 'villager',
    'iron_golem', 'wolf', 'cat', 'horse', 'cow', 'pig', 'sheep', 'chicken',
    'lightning_bolt',
  ],
  // Modern snake_case names, extracted from this server generation's
  // GameRules.class and verified over RCON (the old camelCase names are gone:
  // doDaylightCycle -> advance_time, doMobSpawning -> spawn_mobs, etc).
  gamerules: [
    'keep_inventory', 'advance_time', 'advance_weather', 'mob_griefing',
    'spawn_mobs', 'spawn_monsters', 'spawn_phantoms', 'pvp',
    'random_tick_speed', 'players_sleeping_percentage', 'fall_damage',
    'show_death_messages', 'tnt_explodes', 'natural_health_regeneration',
    'immediate_respawn',
  ],
  booleans: ['true', 'false'],
  timeOfDay: ['day', 'noon', 'night', 'midnight'],
};

// Field types: select (fixed options) · player (online-players datalist +
// selectors) · text (optional `suggest` key into SUGGESTIONS) · number.
export const QUICK_COMMANDS = [
  {
    name: 'gamemode',
    label: 'Game mode',
    desc: 'Change a player’s game mode.',
    fields: [
      { key: 'mode', label: 'mode', type: 'select', options: ['survival', 'creative', 'adventure', 'spectator'], required: true },
      // required: over RCON there is no "self" for gamemode to default to
      { key: 'player', label: 'player', type: 'player', required: true },
    ],
    build: a => `gamemode ${a.mode} ${a.player}`,
  },
  {
    name: 'give',
    label: 'Give item',
    desc: 'Spawn an item into a player’s inventory.',
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'item', label: 'item id', type: 'text', suggest: 'items', required: true, placeholder: 'minecraft:iron_pickaxe' },
      { key: 'count', label: 'count', type: 'number' },
    ],
    build: a => `give ${a.player} ${a.item}${a.count ? ` ${a.count}` : ''}`,
  },
  {
    name: 'tp',
    label: 'Teleport',
    desc: 'Teleport a player to another player or to x y z coordinates.',
    fields: [
      { key: 'player', label: 'who', type: 'player', required: true },
      { key: 'dest', label: 'to (player or x y z)', type: 'player', required: true, placeholder: 'alice — or — 100 64 -200' },
    ],
    build: a => `tp ${a.player} ${a.dest}`,
  },
  {
    name: 'time',
    label: 'Set time',
    desc: 'Set the time of day (word or tick value 0–24000).',
    fields: [
      { key: 'value', label: 'time', type: 'text', suggest: 'timeOfDay', required: true, placeholder: 'day / night / 6000' },
    ],
    build: a => `time set ${a.value}`,
  },
  {
    name: 'weather',
    label: 'Weather',
    desc: 'Change the weather, optionally for a duration in seconds.',
    fields: [
      { key: 'kind', label: 'weather', type: 'select', options: ['clear', 'rain', 'thunder'], required: true },
      { key: 'duration', label: 'seconds', type: 'number' },
    ],
    build: a => `weather ${a.kind}${a.duration ? ` ${a.duration}` : ''}`,
  },
  {
    name: 'gamerule',
    label: 'Game rule',
    desc: 'Set a game rule (keep_inventory true = keep items on death; advance_time false = freeze time; mob_griefing false = no creeper damage). Blank value queries it.',
    fields: [
      { key: 'rule', label: 'rule', type: 'text', suggest: 'gamerules', required: true, placeholder: 'keep_inventory' },
      { key: 'value', label: 'value', type: 'text', suggest: 'booleans', placeholder: 'true / false / number' },
    ],
    build: a => `gamerule ${a.rule}${a.value ? ` ${a.value}` : ''}`,
  },
  {
    name: 'difficulty',
    label: 'Difficulty',
    desc: 'Set the server difficulty.',
    fields: [
      { key: 'level', label: 'level', type: 'select', options: ['peaceful', 'easy', 'normal', 'hard'], required: true },
    ],
    build: a => `difficulty ${a.level}`,
  },
  {
    name: 'effect',
    label: 'Apply effect',
    desc: 'Give a player a status effect (seconds default 30 if only an amplifier is set).',
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'effect', label: 'effect', type: 'text', suggest: 'effects', required: true, placeholder: 'speed' },
      { key: 'seconds', label: 'seconds', type: 'number' },
      { key: 'amplifier', label: 'amplifier', type: 'number' },
    ],
    // amplifier is positional after seconds — supply a default duration if needed
    build: a => {
      const seconds = a.seconds || (a.amplifier ? '30' : '');
      return `effect give ${a.player} ${a.effect}`
        + (seconds ? ` ${seconds}` : '')
        + (a.amplifier ? ` ${a.amplifier}` : '');
    },
  },
  {
    name: 'clear',
    label: 'Clear inventory',
    desc: 'Clear a player’s inventory — everything, or only a given item.',
    confirm: a => `Clear ${a.item || 'the ENTIRE inventory'} from ${a.player}?`,
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'item', label: 'only this item', type: 'text', suggest: 'items' },
      { key: 'count', label: 'max count', type: 'number' },
    ],
    build: a => `clear ${a.player}${a.item ? ` ${a.item}` : ''}${a.item && a.count ? ` ${a.count}` : ''}`,
  },
  {
    name: 'kill',
    label: 'Kill',
    desc: 'Kill players or entities. @e[type=!player] = every non-player entity (mobs, but also dropped items etc).',
    confirm: a => `Kill ${a.target}?`,
    fields: [
      { key: 'target', label: 'target', type: 'player', required: true, placeholder: '@e[type=!player]' },
    ],
    build: a => `kill ${a.target}`,
  },
  {
    name: 'summon',
    label: 'Summon',
    desc: 'Spawn an entity at a player or at coordinates (RCON has no “here”).',
    fields: [
      { key: 'entity', label: 'entity', type: 'text', suggest: 'entities', required: true, placeholder: 'zombie' },
      { key: 'at', label: 'at player', type: 'player' },
      { key: 'pos', label: 'or at x y z', type: 'text', placeholder: '100 64 -200' },
    ],
    validate: a => (a.at || a.pos) ? null : 'Give either "at player" or coordinates.',
    build: a => a.at
      ? `execute at ${a.at} run summon ${a.entity} ~ ~ ~`
      : `summon ${a.entity} ${a.pos}`,
  },
  {
    name: 'msg',
    label: 'Private message',
    desc: 'Send a private message to a player (appears as a whisper from Server).',
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'message', label: 'message', type: 'text', required: true },
    ],
    build: a => `msg ${a.player} ${a.message}`,
  },
  {
    name: 'experience',
    label: 'Give XP',
    desc: 'Add experience — raw points or whole levels.',
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'amount', label: 'amount', type: 'number', required: true },
      { key: 'unit', label: 'unit', type: 'select', options: ['points', 'levels'], required: true },
    ],
    build: a => `experience add ${a.player} ${a.amount} ${a.unit}`,
  },
];

export const PRESETS = [
  { label: 'Day', command: 'time set day' },
  { label: 'Night', command: 'time set night' },
  { label: 'Clear weather', command: 'weather clear' },
  { label: 'Kill all mobs', command: 'kill @e[type=!player]', confirm: 'Kill every non-player entity? (mobs, but also dropped items, armor stands…)' },
  { label: 'Keep inventory ON', command: 'gamerule keep_inventory true' },
  { label: 'Keep inventory OFF', command: 'gamerule keep_inventory false' },
];

export function findCommand(name) {
  return QUICK_COMMANDS.find(c => c.name === name);
}

// Returns {command} or {error} — the single path the UI (and tests) go through.
export function buildQuick(cmd, rawValues) {
  const a = {};
  for (const f of cmd.fields) a[f.key] = (rawValues[f.key] || '').trim();
  for (const f of cmd.fields) {
    if (f.required && !a[f.key]) return { error: `"${f.label}" is required.` };
  }
  if (cmd.validate) {
    const problem = cmd.validate(a);
    if (problem) return { error: problem };
  }
  return { command: cmd.build(a), args: a };
}
