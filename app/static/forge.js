// Item forge: every enchantable item, which enchantments fit it, and the
// give-command builder. Pure data + pure functions (no DOM) so node --test
// covers the exact strings sent. Compatibility is deliberately not enforced
// beyond the per-item lists — give accepts any combination; you're the admin.
import { prettyId } from './stats.js';

// bare id -> {label, max}
export const ENCHANTS = {
  protection: { label: 'Protection', max: 4 },
  fire_protection: { label: 'Fire Protection', max: 4 },
  blast_protection: { label: 'Blast Protection', max: 4 },
  projectile_protection: { label: 'Projectile Protection', max: 4 },
  feather_falling: { label: 'Feather Falling', max: 4 },
  respiration: { label: 'Respiration', max: 3 },
  aqua_affinity: { label: 'Aqua Affinity', max: 1 },
  thorns: { label: 'Thorns', max: 3 },
  depth_strider: { label: 'Depth Strider', max: 3 },
  frost_walker: { label: 'Frost Walker', max: 2 },
  soul_speed: { label: 'Soul Speed', max: 3 },
  swift_sneak: { label: 'Swift Sneak', max: 3 },
  sharpness: { label: 'Sharpness', max: 5 },
  smite: { label: 'Smite', max: 5 },
  bane_of_arthropods: { label: 'Bane of Arthropods', max: 5 },
  knockback: { label: 'Knockback', max: 2 },
  fire_aspect: { label: 'Fire Aspect', max: 2 },
  looting: { label: 'Looting', max: 3 },
  sweeping_edge: { label: 'Sweeping Edge', max: 3 },
  efficiency: { label: 'Efficiency', max: 5 },
  silk_touch: { label: 'Silk Touch', max: 1 },
  fortune: { label: 'Fortune', max: 3 },
  unbreaking: { label: 'Unbreaking', max: 3 },
  mending: { label: 'Mending', max: 1 },
  power: { label: 'Power', max: 5 },
  punch: { label: 'Punch', max: 2 },
  flame: { label: 'Flame', max: 1 },
  infinity: { label: 'Infinity', max: 1 },
  multishot: { label: 'Multishot', max: 1 },
  piercing: { label: 'Piercing', max: 4 },
  quick_charge: { label: 'Quick Charge', max: 3 },
  loyalty: { label: 'Loyalty', max: 3 },
  riptide: { label: 'Riptide', max: 3 },
  impaling: { label: 'Impaling', max: 5 },
  channeling: { label: 'Channeling', max: 1 },
  luck_of_the_sea: { label: 'Luck of the Sea', max: 3 },
  lure: { label: 'Lure', max: 3 },
  density: { label: 'Density', max: 5 },
  breach: { label: 'Breach', max: 4 },
  wind_burst: { label: 'Wind Burst', max: 3 },
};

const KIND_ENCHANTS = {
  sword: ['sharpness', 'smite', 'bane_of_arthropods', 'fire_aspect', 'knockback', 'looting', 'sweeping_edge', 'unbreaking', 'mending'],
  axe: ['sharpness', 'smite', 'bane_of_arthropods', 'efficiency', 'silk_touch', 'fortune', 'unbreaking', 'mending'],
  tool: ['efficiency', 'silk_touch', 'fortune', 'unbreaking', 'mending'],
  helmet: ['protection', 'fire_protection', 'blast_protection', 'projectile_protection', 'respiration', 'aqua_affinity', 'thorns', 'unbreaking', 'mending'],
  chestplate: ['protection', 'fire_protection', 'blast_protection', 'projectile_protection', 'thorns', 'unbreaking', 'mending'],
  leggings: ['protection', 'fire_protection', 'blast_protection', 'projectile_protection', 'swift_sneak', 'thorns', 'unbreaking', 'mending'],
  boots: ['protection', 'fire_protection', 'blast_protection', 'projectile_protection', 'feather_falling', 'depth_strider', 'frost_walker', 'soul_speed', 'thorns', 'unbreaking', 'mending'],
  bow: ['power', 'punch', 'flame', 'infinity', 'unbreaking', 'mending'],
  crossbow: ['multishot', 'piercing', 'quick_charge', 'unbreaking', 'mending'],
  trident: ['loyalty', 'riptide', 'impaling', 'channeling', 'unbreaking', 'mending'],
  mace: ['density', 'breach', 'wind_burst', 'smite', 'bane_of_arthropods', 'fire_aspect', 'knockback', 'unbreaking', 'mending'],
  elytra: ['unbreaking', 'mending'],
  fishing_rod: ['luck_of_the_sea', 'lure', 'unbreaking', 'mending'],
  shield: ['unbreaking', 'mending'],
  shears: ['efficiency', 'unbreaking', 'mending'],
  ignition: ['unbreaking', 'mending'],
};

const TOOL_MATERIALS = ['wooden', 'stone', 'iron', 'golden', 'diamond', 'netherite'];
const ARMOR_MATERIALS = ['leather', 'chainmail', 'iron', 'golden', 'diamond', 'netherite'];

function variants(group, kind, materials, piece) {
  return materials.map(m => ({
    id: `minecraft:${m}_${piece}`, label: prettyId(`${m}_${piece}`), group, kind,
  }));
}

export const FORGE_ITEMS = [
  ...variants('Swords', 'sword', TOOL_MATERIALS, 'sword'),
  ...variants('Pickaxes', 'tool', TOOL_MATERIALS, 'pickaxe'),
  ...variants('Axes', 'axe', TOOL_MATERIALS, 'axe'),
  ...variants('Shovels', 'tool', TOOL_MATERIALS, 'shovel'),
  ...variants('Hoes', 'tool', TOOL_MATERIALS, 'hoe'),
  ...variants('Helmets', 'helmet', ARMOR_MATERIALS, 'helmet'),
  { id: 'minecraft:turtle_helmet', label: 'Turtle Helmet', group: 'Helmets', kind: 'helmet' },
  ...variants('Chestplates', 'chestplate', ARMOR_MATERIALS, 'chestplate'),
  ...variants('Leggings', 'leggings', ARMOR_MATERIALS, 'leggings'),
  ...variants('Boots', 'boots', ARMOR_MATERIALS, 'boots'),
  { id: 'minecraft:bow', label: 'Bow', group: 'Ranged & other', kind: 'bow' },
  { id: 'minecraft:crossbow', label: 'Crossbow', group: 'Ranged & other', kind: 'crossbow' },
  { id: 'minecraft:trident', label: 'Trident', group: 'Ranged & other', kind: 'trident' },
  { id: 'minecraft:mace', label: 'Mace', group: 'Ranged & other', kind: 'mace' },
  { id: 'minecraft:elytra', label: 'Elytra', group: 'Ranged & other', kind: 'elytra' },
  { id: 'minecraft:fishing_rod', label: 'Fishing Rod', group: 'Ranged & other', kind: 'fishing_rod' },
  { id: 'minecraft:shield', label: 'Shield', group: 'Ranged & other', kind: 'shield' },
  { id: 'minecraft:shears', label: 'Shears', group: 'Ranged & other', kind: 'shears' },
  { id: 'minecraft:flint_and_steel', label: 'Flint and Steel', group: 'Ranged & other', kind: 'ignition' },
];

export function findForgeItem(id) {
  return FORGE_ITEMS.find(i => i.id === id);
}

// applicable enchantments for one item -> [{id, label, max}]
export function forgeEnchants(itemId) {
  const item = findForgeItem(itemId);
  if (!item) return [];
  return KIND_ENCHANTS[item.kind].map(id => ({ id, ...ENCHANTS[id] }));
}

// picks: [{id: bare enchant id, level: int}] -> the exact give command
export function buildForgeGive(target, itemId, picks, count = 1) {
  let part = itemId;
  if (picks.length) {
    const levels = picks.map(p => `"minecraft:${p.id}":${p.level}`).join(',');
    part += `[minecraft:enchantments={${levels}}]`;
  }
  return `give ${target} ${part}${count > 1 ? ` ${count}` : ''}`;
}
