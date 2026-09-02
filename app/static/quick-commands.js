// Declarative specs for the Quick commands panel. Pure data + pure build
// functions — no DOM — so node --test can exercise the exact strings the UI
// sends through /api/command.
//
// RCON has no executor (no position, no "self"), which shapes three commands:
// clear/kill require an explicit target, and summon needs a position — either
// coordinates or `execute at <player> run summon … ~ ~ ~`.

// Dropdown choices: `label` is what the user sees, `id` is the exact string
// the server gets. Every choice field also offers "Custom…" for anything not
// listed here.
export const SUGGESTIONS = {
  items: [
    { id: 'minecraft:diamond', label: 'Diamond' },
    { id: 'minecraft:iron_pickaxe', label: 'Iron Pickaxe' },
    { id: 'minecraft:diamond_pickaxe', label: 'Diamond Pickaxe' },
    { id: 'minecraft:diamond_sword', label: 'Diamond Sword' },
    { id: 'minecraft:netherite_ingot', label: 'Netherite Ingot' },
    { id: 'minecraft:golden_apple', label: 'Golden Apple' },
    { id: 'minecraft:enchanted_golden_apple', label: 'Enchanted Golden Apple' },
    { id: 'minecraft:elytra', label: 'Elytra' },
    { id: 'minecraft:ender_pearl', label: 'Ender Pearl' },
    { id: 'minecraft:shulker_box', label: 'Shulker Box' },
    { id: 'minecraft:experience_bottle', label: 'Bottle o’ Enchanting (XP)' },
    { id: 'minecraft:cooked_beef', label: 'Steak' },
    { id: 'minecraft:bread', label: 'Bread' },
    { id: 'minecraft:torch', label: 'Torch' },
    { id: 'minecraft:oak_planks', label: 'Oak Planks' },
  ],
  effects: [
    { id: 'speed', label: 'Speed' },
    { id: 'strength', label: 'Strength' },
    { id: 'regeneration', label: 'Regeneration' },
    { id: 'resistance', label: 'Resistance' },
    { id: 'fire_resistance', label: 'Fire Resistance' },
    { id: 'water_breathing', label: 'Water Breathing' },
    { id: 'night_vision', label: 'Night Vision' },
    { id: 'invisibility', label: 'Invisibility' },
    { id: 'jump_boost', label: 'Jump Boost' },
    { id: 'haste', label: 'Haste (mine faster)' },
    { id: 'saturation', label: 'Saturation (refill hunger)' },
    { id: 'slow_falling', label: 'Slow Falling' },
    { id: 'instant_health', label: 'Instant Health' },
    { id: 'glowing', label: 'Glowing' },
  ],
  entities: [
    { id: 'zombie', label: 'Zombie' },
    { id: 'skeleton', label: 'Skeleton' },
    { id: 'creeper', label: 'Creeper' },
    { id: 'spider', label: 'Spider' },
    { id: 'enderman', label: 'Enderman' },
    { id: 'villager', label: 'Villager' },
    { id: 'iron_golem', label: 'Iron Golem' },
    { id: 'wolf', label: 'Wolf' },
    { id: 'cat', label: 'Cat' },
    { id: 'horse', label: 'Horse' },
    { id: 'cow', label: 'Cow' },
    { id: 'pig', label: 'Pig' },
    { id: 'sheep', label: 'Sheep' },
    { id: 'chicken', label: 'Chicken' },
    { id: 'lightning_bolt', label: 'Lightning Bolt' },
  ],
  // Modern snake_case names, extracted from this server generation's
  // GameRules.class and verified over RCON (the old camelCase names are gone:
  // doDaylightCycle -> advance_time, doMobSpawning -> spawn_mobs, etc).
  gamerules: [
    { id: 'keep_inventory', label: 'Keep items on death' },
    { id: 'advance_time', label: 'Daylight cycle (time advances)' },
    { id: 'advance_weather', label: 'Weather cycle' },
    { id: 'mob_griefing', label: 'Mob block damage (creepers etc.)' },
    { id: 'spawn_mobs', label: 'Mob spawning' },
    { id: 'spawn_monsters', label: 'Monster spawning' },
    { id: 'spawn_phantoms', label: 'Phantom spawning' },
    { id: 'pvp', label: 'PvP' },
    { id: 'random_tick_speed', label: 'Random tick speed (crop growth)' },
    { id: 'players_sleeping_percentage', label: '% of players needed to sleep' },
    { id: 'fall_damage', label: 'Fall damage' },
    { id: 'show_death_messages', label: 'Death messages' },
    { id: 'tnt_explodes', label: 'TNT explodes' },
    { id: 'natural_health_regeneration', label: 'Natural health regen' },
    { id: 'immediate_respawn', label: 'Instant respawn (skip death screen)' },
  ],
  booleans: [
    { id: 'true', label: 'On (true)' },
    { id: 'false', label: 'Off (false)' },
  ],
  timeOfDay: [
    { id: 'day', label: 'Day (morning)' },
    { id: 'noon', label: 'Noon' },
    { id: 'night', label: 'Night' },
    { id: 'midnight', label: 'Midnight' },
  ],
};

// Field types: select (fixed options) · player (online-players datalist +
// selectors) · choice (friendly dropdown into SUGGESTIONS) · text · number.
//
// scope: 'player' commands render on the per-player dashboard cards, with the
// field named by `playerField` auto-filled with the card's player and hidden
// (cardHide lists any extra fields a card should drop); 'global' commands
// render in the Global commands panel.
export const QUICK_COMMANDS = [
  {
    name: 'gamemode',
    label: 'Game mode',
    desc: 'Change a player’s game mode.',
    scope: 'player',
    playerField: 'player',
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
    scope: 'player',
    playerField: 'player',
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'item', label: 'item', type: 'choice', choices: 'items', required: true, placeholder: 'minecraft:iron_pickaxe' },
      { key: 'count', label: 'count', type: 'number' },
    ],
    build: a => `give ${a.player} ${a.item}${a.count ? ` ${a.count}` : ''}`,
  },
  {
    name: 'tp',
    label: 'Teleport',
    desc: 'Teleport a player to another player or to x y z coordinates.',
    scope: 'player',
    playerField: 'player',
    fields: [
      { key: 'player', label: 'who', type: 'player', required: true },
      // dest: rendered as online players + saved waypoints + Custom; waypoint
      // picks bypass build() and go through buildWaypointTp instead
      { key: 'dest', label: 'to', type: 'dest', required: true, placeholder: 'alice — or — 100 64 -200' },
    ],
    build: a => `tp ${a.player} ${a.dest}`,
  },
  {
    name: 'time',
    label: 'Set time',
    desc: 'Set the time of day (word or tick value 0–24000).',
    scope: 'global',
    fields: [
      { key: 'value', label: 'time', type: 'choice', choices: 'timeOfDay', required: true, placeholder: 'tick value 0–24000' },
    ],
    build: a => `time set ${a.value}`,
  },
  {
    name: 'weather',
    label: 'Weather',
    desc: 'Change the weather, optionally for a duration in seconds.',
    scope: 'global',
    fields: [
      { key: 'kind', label: 'weather', type: 'select', options: ['clear', 'rain', 'thunder'], required: true },
      { key: 'duration', label: 'seconds', type: 'number' },
    ],
    build: a => `weather ${a.kind}${a.duration ? ` ${a.duration}` : ''}`,
  },
  {
    name: 'gamerule',
    label: 'Game rule',
    scope: 'global',
    desc: 'Set a game rule (keep_inventory true = keep items on death; advance_time false = freeze time; mob_griefing false = no creeper damage). Blank value queries it.',
    fields: [
      { key: 'rule', label: 'rule', type: 'choice', choices: 'gamerules', required: true, placeholder: 'keep_inventory' },
      { key: 'value', label: 'value (blank = check current)', type: 'choice', choices: 'booleans', placeholder: 'number, e.g. 3' },
    ],
    build: a => `gamerule ${a.rule}${a.value ? ` ${a.value}` : ''}`,
  },
  {
    name: 'difficulty',
    label: 'Difficulty',
    desc: 'Set the server difficulty.',
    scope: 'global',
    fields: [
      { key: 'level', label: 'level', type: 'select', options: ['peaceful', 'easy', 'normal', 'hard'], required: true },
    ],
    build: a => `difficulty ${a.level}`,
  },
  {
    name: 'effect',
    label: 'Apply effect',
    desc: 'Give a player a status effect (seconds default 30 if only an amplifier is set).',
    scope: 'player',
    playerField: 'player',
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'effect', label: 'effect', type: 'choice', choices: 'effects', required: true, placeholder: 'speed' },
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
    scope: 'player',
    playerField: 'player',
    confirm: a => `Clear ${a.item || 'the ENTIRE inventory'} from ${a.player}?`,
    fields: [
      { key: 'player', label: 'player', type: 'player', required: true },
      { key: 'item', label: 'only this item (blank = everything)', type: 'choice', choices: 'items' },
      { key: 'count', label: 'max count', type: 'number' },
    ],
    build: a => `clear ${a.player}${a.item ? ` ${a.item}` : ''}${a.item && a.count ? ` ${a.count}` : ''}`,
  },
  {
    name: 'kill',
    label: 'Kill',
    desc: 'Kill players or entities. @e[type=!player] = every non-player entity (mobs, but also dropped items etc).',
    scope: 'player',
    playerField: 'target',
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
    scope: 'player',
    playerField: 'at',
    cardHide: ['pos'], // a card always summons at its player
    fields: [
      { key: 'entity', label: 'entity', type: 'choice', choices: 'entities', required: true, placeholder: 'zombie' },
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
    scope: 'player',
    playerField: 'player',
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
    scope: 'player',
    playerField: 'player',
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
  // deliberately no "keep inventory OFF" preset — turning it off is a
  // considered act, done via the Game rule builder, not a one-click button
  { label: 'Keep inventory ON', command: 'gamerule keep_inventory true' },
];

export function findCommand(name) {
  return QUICK_COMMANDS.find(c => c.name === name);
}

// Teleport to a saved waypoint {name, pos, dim}. When the waypoint recorded a
// dimension, go through `execute in` so it works from anywhere (plain tp only
// moves players within their current dimension).
export function buildWaypointTp(player, wp) {
  return wp.dim
    ? `execute in ${wp.dim} run tp ${player} ${wp.pos}`
    : `tp ${player} ${wp.pos}`;
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
