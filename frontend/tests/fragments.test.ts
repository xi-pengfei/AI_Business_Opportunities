import {test} from 'node:test';
import assert from 'node:assert/strict';
import {expandCargo, landFragment,cargoText} from '../src/fragments.ts';
import type {Item} from '../src/types.ts';
const record: Item = {id:'test-only',title:'测试夹具',url:'https://example.com/news',published_at:'2026-11-14',is_demo:true,created_at:100,fragments:[
 {index:0,text:'打通 ERP 与 MES 数据',start:0,end:15,before:'',after:''},
 {index:1,text:'建设统一的数据看板',start:16,end:27,before:'',after:''}]};
test('fields land in their own columns, in order, without duplicate rows or fragments',()=>{
 const cargo = expandCargo([record]);
 assert.deepEqual(cargo.map(c=>c.field),['title','fragments','fragments','published_at','created_at']);
 let library = landFragment([],cargo[0]);
 assert.equal(library[0].title,record.title);
 // The URL rides with the title: same record's reference, no separate journey.
 assert.equal(library[0].url,record.url);
 assert.equal(library[0].created_at,0);
 assert.deepEqual(library[0].fragments,[]);
 library=landFragment(library,cargo[1]); library=landFragment(library,cargo[1]);
 assert.equal(library.length,1); assert.equal(library[0].fragments!.length,1);
 for(const c of cargo.slice(2)) library=landFragment(library,c);
 for(const key of ['title','url','published_at','created_at','fragments'] as const) assert.deepEqual(library[0][key],record[key]);
 assert.equal(cargoText(cargo[1]),record.fragments![0].text);
});
test('redacted evidence and absent publication dates are never invented',()=>{
 assert.deepEqual(expandCargo([{...record,fragments:undefined}]),[]);
 assert.equal(expandCargo([{...record,published_at:undefined}]).some(c=>c.field==='published_at'),false);
});
