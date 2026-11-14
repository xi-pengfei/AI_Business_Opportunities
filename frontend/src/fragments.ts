import type {Item} from './types';
export type CargoField = 'title' | 'fragments' | 'url' | 'published_at' | 'created_at';
export type Cargo = Item & {field: CargoField; fragmentIndex: number};
const colors = ['#e99183', '#74d7e8', '#db72ce', '#9be3b1'];
export function fragmentColor(index: number) { return colors[Math.abs(index) % colors.length]; }
export function cargoKey(item: Cargo) { return `${item.id}:${item.field}:${item.fragmentIndex}`; }
export function cargoText(item: Cargo) {
  if (item.field === 'fragments') return item.fragments?.find(f=>f.index===item.fragmentIndex)?.text || '';
  if (item.field === 'created_at') return new Date(item.created_at*1000).toLocaleString('zh-CN',{hour12:false});
  return item[item.field] || '';
}
export function expandCargo(items: Item[]): Cargo[] {
  return items.flatMap(item => {
    // A redacted item has no source evidence to animate.
    if (!item.fragments?.length) return [];
    const fields: Cargo[] = [{...item,field:'title',fragmentIndex:-1},
      ...item.fragments.map(f=>({...item,field:'fragments' as const,fragmentIndex:f.index}))];
    if(item.url) fields.push({...item,field:'url',fragmentIndex:-2});
    if(item.published_at) fields.push({...item,field:'published_at',fragmentIndex:-3});
    fields.push({...item,field:'created_at',fragmentIndex:-4});
    return fields;
  });
}
export function landFragment(library: Item[], cargo: Cargo): Item[] {
  const old = library.find(i=>i.id===cargo.id);
  const row: Item = old || {...cargo,title:'',url:undefined,published_at:undefined,created_at:0,fragments:[],received_fields:[]};
  const next = {...row,received_fields:[...new Set([...(row.received_fields || []),cargo.field])]};
  if(cargo.field === 'fragments') {
    const fragment=cargo.fragments?.find(f=>f.index===cargo.fragmentIndex);
    if(!fragment) return library;
    next.fragments=[...(row.fragments || []).filter(f=>f.index!==fragment.index),fragment].sort((a,b)=>a.index-b.index);
  } else if(cargo.field==='created_at') next.created_at=cargo.created_at;
  else next[cargo.field]=cargo[cargo.field] as string;
  return [next,...library.filter(i=>i.id!==cargo.id)].slice(0,30);
}
