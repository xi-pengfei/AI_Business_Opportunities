import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Spider} from '../src/Spider';
import {expandCargo, landFragment, cargoKey, fragmentColor} from '../src/fragments';
import type {Item} from '../src/types';
import '../src/style.css';
const item: Item = {id:'isolated-test',title:'隔离测试：制造业系统建设',is_demo:true,created_at:1,fragments:[
 {index:0,text:'打通 ERP 与 MES 数据，建设统一的数据看板。',start:0,end:28,before:'岗位职责包括：',after:'具有制造业项目经验者优先。'},
 {index:1,text:'负责信息化项目建设与系统集成。',start:29,end:45,before:'同时，',after:''}]};
const cargo=expandCargo([item]);
function Harness(){
 const [index,setIndex]=useState(-1),[library,setLibrary]=useState<Item[]>([]);
 const moving=index>=0&&index<cargo.length?cargo[index]:null;
 return <main className="screen"><h1>隔离测试 · 不连接正式数据</h1><button onClick={()=>{setLibrary([]);setIndex(0);}}>测试搬运</button><p role="status">已落地 {library[0]?.fragments?.length||0} / 2 片</p>
 <div className="workfield"><section className="panel terminal"><h2>来源终端</h2><div className="terminal-feed"><article className="source-preview"><h3>{item.title}</h3>{item.fragments!.map(f=><p className="source-context" key={f.index}>{f.before}<mark data-source-fragment={`${item.id}:${f.index}`} className={index>=f.index?'fragment-picked':''} style={{'--fragment-color':fragmentColor(f.index)} as React.CSSProperties}>{f.text}</mark>{f.after}</p>)}</article></div></section>
 <section className="panel library"><h2>信息库</h2><table><thead><tr><th>标题</th><th data-inbox-target>信息片</th></tr></thead><tbody>{library.map(i=><tr key={i.id}><td>{i.title}</td><td><div className="fragment-tags">{i.fragments?.map(f=><span className="fragment-tag" data-landed-fragment={`${i.id}:${f.index}`} key={f.index} style={{'--fragment-color':fragmentColor(f.index)} as React.CSSProperties}>{f.text}</span>)}</div></td></tr>)}</tbody></table></section>
 <Spider item={moving} onDelivered={()=>{if(moving){setLibrary(old=>landFragment(old,moving));setIndex(n=>n+1);}}}/></div>
 <p>{moving?cargoKey(moving):index<0?'尚未开始':'搬运结束'}</p></main>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Harness/></React.StrictMode>);
