import {useEffect, useState} from 'react';
import {errors} from './types';
import type {Rule} from './types';
import './xiaohongshu.css';

type Request = (path:string, options?:RequestInit)=>Promise<any>;
const defaults='寻找软件开发团队\nERP系统改造 求推荐\nAI智能体开发需求';
export function Xiaohongshu({request}:{request:Request}) {
  const [rules,setRules]=useState<Rule[]|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [qr,setQr]=useState(''),[logged,setLogged]=useState<boolean|null>(null);
  const [expires,setExpires]=useState(0);
  const [collectors,setCollectors]=useState<any[]>([]);
  const [revision,setRevision]=useState(0);
  const explain=(e:unknown)=>{const text=e instanceof Error?e.message:'操作失败，请重试';return errors[text]||text;};
  useEffect(()=>{
    let alive=true;let timer:ReturnType<typeof setTimeout>;
    const load=async()=>{try{const r=await request('/xiaohongshu');if(alive){setRules(r.rules);setCollectors(r.collectors);}}catch(e){if(alive)setError(explain(e));}finally{if(alive)timer=setTimeout(load,10000);}};
    void load();return()=>{alive=false;clearTimeout(timer);};
  },[request,revision]);
  async function check() {
    const data=await request('/xiaohongshu/login/status',{method:'POST',signal:AbortSignal.timeout(50000)});
    setLogged(data.is_logged_in);
    if(data.is_logged_in){setQr('');setMessage('登录成功，已恢复等待登录的采集任务。');setRevision(n=>n+1);}
    else setMessage('尚未登录，请使用小红书 App 扫码并确认。');
  }
  useEffect(()=>{
    if(!qr)return;
    let alive=true;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      if(Date.now()>expires){if(alive){setQr('');setMessage('二维码已过期，请重新获取。');}return;}
      try{const r=await request('/xiaohongshu/login/status',{method:'POST',signal:AbortSignal.timeout(50000)});if(alive&&r.is_logged_in){setLogged(true);setQr('');setMessage('登录成功，采集会自动继续。');setRevision(n=>n+1);return;}}
      catch(e){if(alive)setError(explain(e));}
      if(alive)timer=setTimeout(poll,15000);
    };
    timer=setTimeout(poll,15000);return()=>{alive=false;clearTimeout(timer);};
  },[qr,expires,request]);
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');setMessage('');try{await fn();}catch(e){setError(explain(e));}finally{setBusy(false);}}
  return <div className="xhs-layout">
    <section className="panel"><h2>小红书账号</h2>
      <p className="xhs-status">{logged===true?'已登录':logged===false?'等待扫码登录':'登录状态待检查'}</p>
      <div className="actions"><button disabled={busy} onClick={()=>action(async()=>{
        const r=await request('/xiaohongshu/login/qrcode',{method:'POST',signal:AbortSignal.timeout(50000)});
        setLogged(r.is_logged_in);setQr(r.img||'');setExpires(Date.now()+120000);
        if(r.is_logged_in)await check();else setMessage('请用小红书 App 扫码，在手机上确认登录。');
      })}>{busy?'正在连接…':'扫码登录'}</button><button disabled={busy} onClick={()=>action(check)}>检查登录</button></div>
      {qr&&<img className="xhs-qr" src={qr} alt="小红书登录二维码，请使用小红书 App 扫描"/>}
      <p className="hint">只读取搜索结果和笔记，不发布、不评论、不点赞。遇到验证或登录失效时，小红书采集暂停，其他采集继续。</p>
      {error&&<p className="error" role="alert">{error}</p>}
      {message&&<p className="success" role="status">{message}</p>}
    </section>
    <section className="panel"><h2 id="xhs-rules-title">需求关键词</h2>
      {rules===null?<p className="empty">正在读取配置…</p>:<form aria-labelledby="xhs-rules-title" onSubmit={e=>{
        e.preventDefault();const query=String(new FormData(e.currentTarget).get('query')||'');
        void action(async()=>{
          if(rules[0])await request(`/rules/${rules[0].id}`,{method:'PATCH',body:JSON.stringify({query,enabled:true,interval_seconds:0})});
          else await request('/rules',{method:'POST',body:JSON.stringify({name:'小红书需求',query,provider:'xiaohongshu',enabled:true,interval_seconds:0,max_results:20})});
          setRevision(n=>n+1);setMessage('关键词已保存，登录后自动持续采集。');
        });
      }}><label htmlFor="xhs-query">搜索关键词（每行一组）</label><textarea key={rules[0]?.id||'new'} id="xhs-query" name="query" required maxLength={500} defaultValue={rules[0]?.query||defaults}/>
        <button type="submit" disabled={busy}>保存并持续采集</button>
      </form>}
      <p className="hint">保留近30天提出软件或信息化需求的帖子，过滤接单广告和教程。去重后：来源终端 → 蜘蛛搬运 → 信息库。入库后按商机流程推送钉钉，等待群成员认领。</p>
      {rules?.map(r=>{const c=collectors.find(c=>c.id===r.id);return <article className="rule" key={r.id}><div><h3>{r.name}</h3><p>{!r.enabled?'已停止':c?.error_code?(errors[c.error_code]||c.error_code):c?.state==='running'?'正在搜索':c?.state==='cleaning'?'正在读取笔记':'等待下一批'}</p>{c?.query&&<small>当前搜索：{c.query}</small>}</div><button disabled={busy} onClick={()=>action(async()=>{await request(`/rules/${r.id}`,{method:'PATCH',body:JSON.stringify({enabled:!r.enabled})});setRevision(n=>n+1);})}>{r.enabled?'停止采集':'继续采集'}</button></article>})}
    </section>
  </div>;
}
