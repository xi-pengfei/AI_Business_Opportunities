import {useEffect,useRef,useState} from 'react';
import type {Me} from './types';

type DisplayInfo={masked:string;source:string;present:boolean;token?:string};
type ApiKeyRow={id:string;name:string;prefix:string;created_at:number;last_used_at:number|null};

const KeyIcon=()=><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 21 2M15 8l3 3M18.5 4.5 21 7"/></svg>;

export function TokenPanel({open,request,user,onClose}:{open:boolean;request:(path:string,options?:RequestInit)=>Promise<any>;user:Me|null;onClose:()=>void}) {
  const isAdmin=user?.role==='admin';
  const [display,setDisplay]=useState<DisplayInfo|null>(null);
  const [revealedDisplay,setRevealedDisplay]=useState(false);
  const [keys,setKeys]=useState<ApiKeyRow[]>([]);
  const [keyName,setKeyName]=useState('');
  const [freshKey,setFreshKey]=useState('');
  const [confirming,setConfirming]=useState(false);
  // 修改密码
  const [oldPass,setOldPass]=useState(''),[newPass,setNewPass]=useState(''),[newPass2,setNewPass2]=useState('');
  const [pwdMsg,setPwdMsg]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{
    if(!open)return;
    setDisplay(null);setRevealedDisplay(false);setConfirming(false);setFreshKey('');setError('');setPwdMsg('');
    setOldPass('');setNewPass('');setNewPass2('');setKeyName('');
    request('/api-keys').then(setKeys).catch(()=>{});
    if(isAdmin) request('/console-token').then(setDisplay).catch(()=>{});
    requestAnimationFrame(()=>heading.current?.focus());
  },[open]);
  useEffect(()=>{
    if(!open)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy)onClose();};
    addEventListener('keydown',onKey);
    return()=>removeEventListener('keydown',onKey);
  },[open,busy,onClose]);
  async function copy(text:string){
    try{await navigator.clipboard.writeText(text);}catch{/* 剪贴板不可用时忽略，明文仍展示在面板里 */}
  }
  async function toggleReveal(){
    if(revealedDisplay){setRevealedDisplay(false);return;}
    setBusy(true);setError('');
    try{const full:DisplayInfo=await request('/console-token?reveal=1');setDisplay(full);setRevealedDisplay(true);}
    catch(e){setError(e instanceof Error?e.message:'读取令牌失败');}
    finally{setBusy(false);}
  }
  async function rotate(){
    setBusy(true);setError('');
    try{
      const res=await request('/console-token/rotate',{method:'POST'});
      setDisplay({masked:res.masked,source:'db',present:true});setRevealedDisplay(false);setConfirming(false);setFreshKey(res.token);
    }
    catch(e){setError(e instanceof Error?e.message:'生成新令牌失败');}
    finally{setBusy(false);}
  }
  async function addKey(){
    setBusy(true);setError('');
    try{
      const res=await request('/api-keys',{method:'POST',body:JSON.stringify({name:keyName})});
      setFreshKey(res.key);setKeyName('');
      setKeys(await request('/api-keys'));
    }
    catch(e){setError(e instanceof Error?e.message:'生成密钥失败');}
    finally{setBusy(false);}
  }
  async function revoke(id:string){
    setBusy(true);setError('');
    try{await request(`/api-keys/${id}`,{method:'DELETE'});setKeys(await request('/api-keys'));}
    catch(e){setError(e instanceof Error?e.message:'吊销失败');}
    finally{setBusy(false);}
  }
  async function changePassword(){
    setBusy(true);setError('');setPwdMsg('');
    if(newPass!==newPass2){setError('两次输入的新密码不一致');setBusy(false);return;}
    try{
      await request('/auth/change-password',{method:'POST',body:JSON.stringify({old_password:oldPass,new_password:newPass})});
      setPwdMsg('密码已更新，下次登录请使用新密码。');setOldPass('');setNewPass('');setNewPass2('');
    }
    catch(e){setError(e instanceof Error?e.message:'修改失败');}
    finally{setBusy(false);}
  }
  return <>
    {open&&<div className="drawer-layer">
      <div className="drawer-backdrop" onClick={onClose}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="token-title">
        <button type="button" className="dr-close" onClick={onClose} aria-label="关闭账号中心">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">账号 · 安全</div>
          <h2 className="dr-title" id="token-title" tabIndex={-1} ref={heading}>账号中心</h2>
          <p className="dr-sub">{user?`${user.display_name}（${user.username}）· ${user.role==='admin'?'管理员权限':'成员'}`:''}</p>
        </div>
        <div className="dr-body">
          {error&&<p className="error" role="alert">{error}</p>}
          <section className="token-section">
            <h3>修改密码</h3>
            <label>原密码
              <input type="password" autoComplete="current-password" value={oldPass} onChange={e=>setOldPass(e.target.value)}/>
            </label>
            <label>新密码（至少 8 位）
              <input type="password" autoComplete="new-password" value={newPass} onChange={e=>setNewPass(e.target.value)}/>
            </label>
            <label>确认新密码
              <input type="password" autoComplete="new-password" value={newPass2} onChange={e=>setNewPass2(e.target.value)}/>
            </label>
            <div className="actions"><button type="button" className="btn btn-primary" disabled={busy||!oldPass||newPass.length<8} onClick={changePassword}>更新密码</button></div>
            {pwdMsg&&<p className="success" role="status">{pwdMsg}</p>}
          </section>
          <section className="token-section">
            <h3>API 密钥 <span className="opt">脚本接入用</span></h3>
            <p className="hint">给脚本（如 curl、CI）用的个人密钥。明文只显示一次，请妥善保存。</p>
            <div className="token-row">
              <input className="token-input" placeholder="用途备注，如 CI 发布脚本" value={keyName} onChange={e=>setKeyName(e.target.value)}/>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={addKey}>生成密钥</button>
            </div>
            {!!keys.length&&<ul className="key-list">
              {keys.map(k=><li key={k.id} className="key-row">
                <code>{k.prefix}…</code>
                <span className="key-name">{k.name||'未命名'}</span>
                <span className="key-used">{k.last_used_at?`最近使用 ${new Date(k.last_used_at*1000).toLocaleDateString('zh-CN')}`:'从未使用'}</span>
                <button type="button" className="btn btn-sm" disabled={busy} onClick={()=>revoke(k.id)}>吊销</button>
              </li>)}
            </ul>}
            {freshKey&&<div className="token-created" role="status">
              <p><b>新密钥已生成。</b>明文仅显示这一次，请立即复制保存：</p>
              <div className="token-row">
                <code className="token-value">{freshKey}</code>
                <button type="button" className="btn btn-sm" onClick={()=>copy(freshKey)}>复制</button>
              </div>
            </div>}
          </section>
          {isAdmin&&<section className="token-section">
            <h3>大屏令牌 <span className="opt">屏幕免登录</span></h3>
            {display?.present
              ? <>
                  <div className="token-row">
                    <code className={revealedDisplay?'token-value':'token-masked'}>{revealedDisplay&&display.token?display.token:display.masked}</code>
                    <button type="button" className="btn btn-sm" disabled={busy} onClick={toggleReveal}>{revealedDisplay?'隐藏':'显示'}</button>
                    {revealedDisplay&&display.token&&<button type="button" className="btn btn-sm" onClick={()=>copy(display.token!)}>复制</button>}
                  </div>
                  <p className="hint">大屏链接免登录：把链接放到大屏机器的浏览器打开即可。链接泄露可在下方重新生成。</p>
                  <div className="token-row">
                    <code className="token-value screen-link">{`${location.origin}/display?k=`}{revealedDisplay&&display.token?display.token:display.masked}</code>
                    {revealedDisplay&&display.token&&<button type="button" className="btn btn-sm" onClick={()=>copy(`${location.origin}/display?k=${display.token}`)}>复制链接</button>}
                  </div>
                  {confirming
                    ? <div className="token-confirm" role="alertdialog" aria-label="确认生成新的大屏令牌">
                        <p><b>确定生成新的大屏令牌？</b></p>
                        <p>旧令牌和旧链接立即失效，已打开的大屏需要换用新链接。</p>
                        <div className="actions">
                          <button type="button" className="btn btn-primary" disabled={busy} onClick={rotate}>{busy?'正在生成…':'确认生成'}</button>
                          <button type="button" className="btn" disabled={busy} onClick={()=>setConfirming(false)}>先不换</button>
                        </div>
                      </div>
                    : <button type="button" className="btn" disabled={busy} onClick={()=>setConfirming(true)}>重新生成令牌</button>}
                </>
              : <p className="hint">尚未配置大屏令牌，大屏免登录暂不可用，请联系管理员。</p>}
          </section>}
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>关闭</button>
        </div>
      </aside>
    </div>}
  </>;
}

export {KeyIcon};
