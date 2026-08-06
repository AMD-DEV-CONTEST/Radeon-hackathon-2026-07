import type { BiomeAssetKind } from "./BiomeAssetRegistry";

export type ProductionEnvironmentAsset = {
  id: string;
  kind: BiomeAssetKind;
  biomes: string[];
  url: string;
  scale: [number, number];
  targetHeight: number;
  density: number;
  minRadius: number;
  maxRadius: number;
  lodDistance: number;
  source: "local";
};

const root = "/worldforge/assets/environment";

export const PRODUCTION_ENVIRONMENT_ASSETS: ProductionEnvironmentAsset[] = [
{ id:"desert-rock-glb", kind:"rock", biomes:["desert"], url:`${root}/desert/rock.glb`, scale:[0.8,2.2], targetHeight:1.5, density:18, minRadius:9, maxRadius:45, lodDistance:34, source:"local" },
{ id:"desert-shrub-glb", kind:"vegetation", biomes:["desert"], url:`${root}/desert/shrub.glb`, scale:[0.7,1.4], targetHeight:1.0, density:18, minRadius:10, maxRadius:44, lodDistance:30, source:"local" },
{ id:"arctic-rock-glb", kind:"rock", biomes:["arctic"], url:`${root}/arctic/rock.glb`, scale:[0.8,2.0], targetHeight:1.5, density:16, minRadius:9, maxRadius:44, lodDistance:34, source:"local" },
{ id:"forest-rock-glb", kind:"rock", biomes:["forest"], url:`${root}/forest/rock.glb`, scale:[0.7,1.7], targetHeight:1.5, density:18, minRadius:9, maxRadius:43, lodDistance:34, source:"local" },
{ id:"grassland-tree-glb", kind:"vegetation", biomes:["grassland"], url:`${root}/grassland/tree.glb`, scale:[1.0,2.0], targetHeight:5.5, density:18, minRadius:13, maxRadius:45, lodDistance:38, source:"local" },
{ id:"mountain-boulder-glb", kind:"rock", biomes:["mountain"], url:`${root}/mountain/boulder.glb`, scale:[1.0,3.0], targetHeight:2.5, density:30, minRadius:9, maxRadius:46, lodDistance:38, source:"local" },
{ id:"coastal-palm-glb", kind:"vegetation", biomes:["coastal"], url:`${root}/coastal/palm.glb`, scale:[1.0,1.9], targetHeight:6.0, density:18, minRadius:13, maxRadius:44, lodDistance:38, source:"local" },
{ id:"coastal-rock-glb", kind:"rock", biomes:["coastal"], url:`${root}/coastal/rock.glb`, scale:[0.8,1.8], targetHeight:1.5, density:20, minRadius:9, maxRadius:45, lodDistance:34, source:"local" },
{ id:"urban-tree-glb", kind:"vegetation", biomes:["urban"], url:`${root}/urban/tree.glb`, scale:[0.9,1.4], targetHeight:5.5, density:12, minRadius:13, maxRadius:42, lodDistance:34, source:"local" }, { id:"arctic-pine-glb", kind:"vegetation", biomes:["arctic"],targetHeight: 5.5, url:"/worldforge/assets/environment/shared/pine_tree_01/pine_tree_01_1k.gltf", scale:[0.9,1.1], density:1, minRadius:10, maxRadius:14, lodDistance:36, source:"local" },
{ id:"forest-tree-glb", kind:"vegetation", biomes:["forest"],targetHeight: 5.5, url:"/worldforge/assets/environment/shared/pine_tree_01/pine_tree_01_1k.gltf", scale:[0.9,1.1], density:1, minRadius:10, maxRadius:14, lodDistance:38, source:"local" },
{ id:"mountain-pine-glb", kind:"vegetation", biomes:["mountain"], targetHeight: 5.5, url:"/worldforge/assets/environment/shared/pine_tree_01/pine_tree_01_1k.gltf", scale:[0.9,1.1], density:1, minRadius:10, maxRadius:14, lodDistance:38, source:"local" },
];

export function productionAssetsForBiome(biome: string) {
  return PRODUCTION_ENVIRONMENT_ASSETS.filter(
    (asset) =>
      asset.biomes.includes(biome) &&
      asset.url.includes("pine_tree_01"),
  );
}
