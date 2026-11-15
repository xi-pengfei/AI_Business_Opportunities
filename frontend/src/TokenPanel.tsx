import {useEffect,useRef,useState} from 'react';

type Info={masked:string;source:string;token?:string;display?:{masked:string;source:string;present:boolean;token?:string}};

const KeyIcon=()=><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 21 2M15 8l3 3M18.5 4.5 21 7"/></svg>;

export function TokenPanel({open,request,onClose,onRotated}:{open:boolean;request:(path:string,options?:RequestInit)=>Promise<any>;onClose:()=>void;onRotated:(token:string)=>void}) {
  const [info,setInfo]=useState<Info|null>(null);
  const [revealed,setRevealed]=useState(false);
  const [revealedDisplay,setRevealedDisplay]=useState(false);
  const [confirming,setConfirming]=useState(false);
  const [created,setCreated]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{
    if(!open)return;
    setInfo(null);setRevealed(false);setRevealedDisplay(false);setConfirming(false);setCreated('');setError('');
    request('/console-token').then(setInfo).catch(e=>setError(e instanceof Error?e.message:'读取令牌失败'));
    requestAnimationFrame(()=>heading.current?.focus());
  },[open]);
  useEffect(()=>{
    if(!open)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy)onClose();};
    addEventListener('keydown',onKey);
    return()=>removeEventListener('keydown',onKey);
  },[open,busy,onClose]);
  async function loadFull(){
    const full:Info=await request('/console-token?reveal=1');
    setInfo(full);
    return full;
  }
  async function toggleReveal(which:'admin'|'display'){
    const already=which==='admin'?revealed:revealedDisplay;
    if(already){if(which==='admin')setRevealed(false);else setRevealedDisplay(false);return;}
    setBusy(true);setError('');
    try{await loadFull();if(which==='admin')setRevealed(true);else setRevealedDisplay(true);}
    catch(e){setError(e instanceof Error?e.message:'读取令牌失败');}
    finally{setBusy(false);}
  }
  async function copy(text:string){
    try{await navigator.clipboard.writeText(text);}catch{
      const el=document.querySelector('.token-value,.token-masked') as HTMLElement|null;
      if(el){const range=document.createRange();range.selectNodeContents(el);const sel=getSelection();sel?.removeAllRanges();sel?.addRange(range);document.execCommand('copy');sel?.removeAllRanges();}
    }
  }
  async function rotate(){
    setBusy(true);setError('');
    try{
      const res=await request('/console-token/rotate',{method:'POST'});
      setInfo(old=>old?{...old,masked:res.masked,source:'db',token:undefined}:old);
      setRevealed(false);setConfirming(false);setCreated(res.token);
    }
    catch(e){setError(e instanceof Error?e.message:'生成新令牌失败');}
    finally{setBusy(false);}
  }
  function done(){
    const token=created;
    setCreated('');
    if(token)onRotated(token);
    onClose();
  }
  return <>
    {open&&<div className="drawer-layer">
      <div className="drawer-backdrop" onClick={onClose}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="token-title">
        <button type="button" className="dr-close" onClick={onClose} aria-label="关闭令牌面板">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">本机 · 访问凭证</div>
          <h2 className="dr-title" id="token-title" tabIndex={-1} ref={heading}>本机令牌</h2>
          <p className="dr-sub">管理台只有两把本机令牌，没有账号体系。默认只显示掩码，明文保存在本机，不会上传。</p>
        </div>
        <div className="dr-body">
          {error&&<p className="error" role="alert">{error}</p>}
          {!info&&!error&&<p className="hint">正在读取令牌…</p>}
          {info&&<>
            <label htmlFor="token-value">管理令牌 <span className="opt">{revealed?'明文':'已掩码'}</span></label>
            <div className="token-row">
              <code id="token-value" className={revealed?'token-value':'token-masked'}>{revealed&&info.token?info.token:info.masked}</code>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={()=>toggleReveal('admin')}>{revealed?'隐藏':'显示'}</button>
              <button type="button" className="btn btn-sm" disabled={busy||!info.token} onClick={()=>copy(info.token!)}>复制</button>
            </div>
            <p className="hint">
              用于登录本管理台，可读写。来源：{info.source==='db'?'本机数据库（生成过新令牌，.env 中的旧值已失效）':'.env 配置（尚未生成过新令牌）'}。
            </p>
            {confirming
              ? <div className="token-confirm" role="alertdialog" aria-label="确认生成新令牌">
                  <p><b>确定生成新令牌？</b></p>
                  <p>旧令牌立即失效，本会话会自动切换到新令牌；如果有脚本或其他工具在用当前令牌，需要同步更新。</p>
                  <div className="actions">
                    <button type="button" className="btn btn-primary" disabled={busy} onClick={rotate}>{busy?'正在生成…':'确认生成'}</button>
                    <button type="button" className="btn" disabled={busy} onClick={()=>setConfirming(false)}>先不换</button>
                  </div>
                </div>
              : <button type="button" className="btn" disabled={busy} onClick={()=>setConfirming(true)}>生成新令牌</button>}
            <section className="token-other">
              <h3>展示令牌 <span className="opt">只读</span></h3>
              {info.display?.present
                ? <>
                    <div className="token-row">
                      <code className={revealedDisplay?'token-value':'token-masked'}>{revealedDisplay&&info.display.token?info.display.token:info.display.masked}</code>
                      <button type="button" className="btn btn-sm" disabled={busy} onClick={()=>toggleReveal('display')}>{revealedDisplay?'隐藏':'显示'}</button>
                      <button type="button" className="btn btn-sm" disabled={busy||!info.display.token} onClick={()=>copy(info.display!.token!)}>复制</button>
                    </div>
                    <p className="hint">给展示大屏用，只能看脱敏数据，不能改任何配置。更换需修改 .env 的 DISPLAY_TOKEN。</p>
                  </>
                : <p className="hint">未配置展示令牌，展示大屏需要登录 .env 中配置的 DISPLAY_TOKEN 才能打开。</p>}
            </section>
          </>}
          {created&&<div className="token-created" role="status">
            <p><b>新令牌已生成，旧令牌已失效。</b>明文仅显示这一次，请立即复制保存：</p>
            <div className="token-row">
              <code className="token-value">{created}</code>
              <button type="button" className="btn btn-sm" onClick={()=>copy(created)}>复制</button>
            </div>
            <p className="hint">关闭面板后本会话会自动改用新令牌，无需重新登录。此后面板里只会显示掩码。</p>
            <button type="button" className="btn btn-primary" onClick={done}>我已保存，继续</button>
          </div>}
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>关闭</button>
        </div>
      </aside>
    </div>}
  </>;
}

export {KeyIcon};
