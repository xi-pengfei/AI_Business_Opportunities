import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Spider} from '../src/Spider';
import {SourceFields,Information} from '../src/FlowPanels';
import {expandCargo, landFragment, cargoKey} from '../src/fragments';
import type {Item} from '../src/types';
import '../src/style.css';
const item: Item = {id:'isolated-test',title:'隔离测试：制造业 ERP 与 MES 系统建设和数据看板集成',url:'https://example.com/test-only',published_at:'2026-11-14',is_demo:true,created_at:1794614400,fragments:[
 {index:0,text:'打通 ERP 与 MES 数据，建设统一的数据看板。',start:0,end:28,before:'岗位职责包括：',after:'具有制造业项目经验者优先。'},
 {index:1,text:'负责信息化项目建设与系统集成。',start:29,end:45,before:'同时，',after:''}]};
const cargo=expandCargo([item]);
function Harness(){
 const [index,setIndex]=useState(-1),[library,setLibrary]=useState<Item[]>([]),[landed,setLanded]=useState(new Set<string>());
 const moving=index>=0&&index<cargo.length?cargo[index]:null;
 return <main className="screen"><h1>隔离测试 · 不连接正式数据</h1><button onClick={()=>{setLibrary([]);setLanded(new Set());setIndex(0);}}>测试搬运</button><p role="status">已落地 {landed.size} / {cargo.length} 个字段片</p>
 <div className="workfield"><section className="panel terminal"><h2>来源终端</h2><div className="terminal-feed"><article className="source-preview"><SourceFields item={item} moving={moving} landed={landed}/></article></div></section>
 <section className="panel library"><h2>信息库</h2><Information items={library} open={i=>alert(JSON.stringify(i,null,2))}/></section>
 <Spider item={moving} onDelivered={()=>{if(moving){setLibrary(old=>landFragment(old,moving));setLanded(old=>new Set([...old,cargoKey(moving)]));setIndex(n=>n+1);}}}/></div>
 <p>{moving?cargoKey(moving):index<0?'尚未开始':'搬运结束'}</p></main>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Harness/></React.StrictMode>);
