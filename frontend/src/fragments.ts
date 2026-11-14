import type { Item } from './types';
export type Cargo = Item & { fragmentIndex: number };
const colors = ['#d8ba7c', '#70c3ce', '#e393b0', '#9bbb92'];
export function fragmentColor(index: number) { return colors[index % colors.length]; }
export function cargoKey(item: Cargo) { return `${item.id}:${item.fragmentIndex}`; }
export function expandCargo(items: Item[]): Cargo[] {
  return items.flatMap(item => (item.fragments || []).map(f => ({...item, fragmentIndex: f.index})));
}
export function landFragment(library: Item[], cargo: Cargo): Item[] {
  const fragment = cargo.fragments?.find(f => f.index === cargo.fragmentIndex);
  if (!fragment) return library;
  const old = library.find(i => i.id === cargo.id);
  const fragments = [...(old?.fragments || []).filter(f => f.index !== fragment.index), fragment].sort((a,b)=>a.index-b.index);
  return [{...cargo, fragments}, ...library.filter(i => i.id !== cargo.id)].slice(0, 30);
}
