// The Biomes catalog: items you find in the world or take from its mobs,
// grouped by where they come from. Curated, not exhaustive — crafted and
// smelted things don't belong here. Pure data (node-tested; every id is also
// swept against a live Paper 26.2 server — see tests + CLAUDE.md).
import { prettyId } from './stats.js';

const i = (id, note) => ({ id: `minecraft:${id}`, label: prettyId(id), note });

export const BIOME_ITEMS = [
  { biome: 'Plains & meadows', items: [
    i('short_grass'), i('dandelion'), i('poppy'), i('oxeye_daisy'), i('cornflower'),
    i('wheat_seeds'), i('egg', 'chickens'), i('feather', 'chickens'),
    i('leather', 'cows & horses'), i('beef', 'cows'), i('porkchop', 'pigs'),
    i('mutton', 'sheep'), i('white_wool', 'sheep'), i('honeycomb', 'bee nests'),
  ] },
  { biome: 'Forests', items: [
    i('oak_log'), i('birch_log'), i('dark_oak_log'), i('apple', 'oak leaves'),
    i('oak_sapling'), i('red_mushroom'), i('brown_mushroom'),
    i('lily_of_the_valley'), i('allium'), i('bone_meal', 'skeletons via bones'),
  ] },
  { biome: 'Taiga & cherry grove', items: [
    i('spruce_log'), i('cherry_log'), i('sweet_berries'), i('fern'), i('large_fern'),
    i('pink_petals', 'cherry groves'), i('rabbit', 'rabbits'), i('rabbit_hide'),
    i('rabbit_foot', 'rare drop'),
  ] },
  { biome: 'Snowy & mountains', items: [
    i('snowball'), i('ice'), i('packed_ice'), i('blue_ice'),
    i('powder_snow_bucket', 'needs a bucket'), i('goat_horn', 'ramming goats'),
    i('emerald', 'mountain ore'), i('raw_iron', 'ore'), i('raw_copper', 'ore'),
  ] },
  { biome: 'Desert & badlands', items: [
    i('sand'), i('red_sand'), i('sandstone'), i('cactus'), i('dead_bush'),
    i('terracotta', 'badlands'), i('raw_gold', 'badlands ore'),
    i('bone', 'husks & fossils'),
  ] },
  { biome: 'Savanna', items: [
    i('acacia_log'), i('armadillo_scute', 'armadillos'), i('cocoa_beans', 'also jungle'),
  ] },
  { biome: 'Jungle', items: [
    i('jungle_log'), i('bamboo'), i('cocoa_beans'), i('melon_slice'), i('vine'),
    i('moss_block', 'also lush caves'),
  ] },
  { biome: 'Swamp & mangrove', items: [
    i('slime_ball', 'slimes'), i('lily_pad'), i('blue_orchid'), i('mangrove_log'),
    i('mangrove_propagule'), i('mud'), i('clay_ball'),
  ] },
  { biome: 'Rivers & beaches', items: [
    i('sugar_cane'), i('clay_ball'), i('gravel'), i('flint', 'from gravel'),
    i('turtle_scute', 'baby turtles growing up'), i('turtle_egg'),
  ] },
  { biome: 'Ocean', items: [
    i('kelp'), i('seagrass'), i('sea_pickle'), i('cod'), i('salmon'),
    i('pufferfish'), i('tropical_fish'), i('ink_sac', 'squid'),
    i('glow_ink_sac', 'glow squid'), i('prismarine_shard', 'guardians'),
    i('prismarine_crystals', 'guardians'), i('sponge', 'elder guardians'),
    i('nautilus_shell', 'drowned'), i('copper_ingot', 'drowned'),
    i('trident', 'drowned, rare'),
  ] },
  { biome: 'Lush caves', items: [
    i('glow_berries'), i('moss_block'), i('spore_blossom'), i('big_dripleaf'),
    i('small_dripleaf'), i('flowering_azalea'),
  ] },
  { biome: 'Caves & deep dark', items: [
    i('coal', 'ore'), i('raw_iron', 'ore'), i('raw_copper', 'ore'), i('raw_gold', 'ore'),
    i('redstone', 'ore'), i('lapis_lazuli', 'ore'), i('diamond', 'ore'),
    i('amethyst_shard', 'geodes'), i('pointed_dripstone'), i('dripstone_block'),
    i('glow_lichen'), i('sculk', 'deep dark'), i('sculk_sensor', 'deep dark'),
  ] },
  { biome: 'Mushroom island', items: [
    i('mycelium', 'silk touch'), i('red_mushroom'), i('brown_mushroom'),
  ] },
  { biome: 'The Nether', items: [
    i('netherrack'), i('soul_sand'), i('soul_soil'), i('quartz', 'ore'),
    i('glowstone_dust'), i('nether_wart', 'fortresses'), i('blaze_rod', 'blazes'),
    i('ghast_tear', 'ghasts'), i('magma_cream', 'magma cubes'),
    i('gold_nugget', 'zombified piglins'), i('wither_skeleton_skull', 'rare drop'),
    i('ancient_debris', 'netherite ore'), i('crimson_fungus'), i('warped_fungus'),
    i('shroomlight'), i('weeping_vines'),
  ] },
  { biome: 'The End', items: [
    i('end_stone'), i('ender_pearl', 'endermen'), i('chorus_fruit'),
    i('chorus_flower'), i('shulker_shell', 'shulkers'), i('dragon_egg', 'one per world'),
  ] },
  { biome: 'Hostile mobs (anywhere)', items: [
    i('rotten_flesh', 'zombies'), i('bone', 'skeletons'), i('arrow', 'skeletons'),
    i('string', 'spiders'), i('spider_eye', 'spiders'), i('gunpowder', 'creepers'),
    i('phantom_membrane', 'phantoms'), i('slime_ball', 'slimes'),
    i('totem_of_undying', 'evokers'), i('emerald', 'raid pillagers'),
    i('breeze_rod', 'breezes'),
  ] },
];

export function findBiomeItem(id) {
  for (const group of BIOME_ITEMS) {
    const hit = group.items.find(item => item.id === id);
    if (hit) return hit;
  }
  return null;
}

export function buildBiomeGive(target, id, count = 1) {
  return `give ${target} ${id}${count > 1 ? ` ${count}` : ''}`;
}
