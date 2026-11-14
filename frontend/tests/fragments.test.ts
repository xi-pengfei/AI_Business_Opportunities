import {test} from 'node:test';
import assert from 'node:assert/strict';
import {expandCargo, landFragment} from '../src/fragments.ts';
import type {Item} from '../src/types.ts';
const record: Item = {id:'test-only',title:'测试夹具',is_demo:true,created_at:1,fragments:[
 {index:0,text:'打通 ERP 与 MES 数据',start:0,end:15,before:'',after:''},
 {index:1,text:'建设统一的数据看板',start:16,end:27,before:'',after:''}]};
test('only a delivered source fragment enters the library; retries do not duplicate',()=>{
 const cargo = expandCargo([record]);
 let library = landFragment([],cargo[0]);
 assert.deepEqual(library[0].fragments,[record.fragments![0]]);
 library = landFragment(library,cargo[0]);
 assert.equal(library.length,1); assert.equal(library[0].fragments!.length,1);
 library = landFragment(library,cargo[1]);
 assert.deepEqual(library[0].fragments,record.fragments);
});
test('missing or redacted evidence never becomes fabricated cargo',()=>{
 assert.deepEqual(expandCargo([{...record,fragments:undefined}]),[]);
});
