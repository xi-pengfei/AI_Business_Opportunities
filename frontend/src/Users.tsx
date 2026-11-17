import {useEffect,useRef,useState} from 'react';
import type {Me} from './types';

type UserRow=Me;
const stamp=(t?:number)=>t?new Date(t*1000).toLocaleString('zh-CN',{year:'2-digit',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';

const PlusIcon=()=><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;

export function Users({request,me}:{request:(path:string,options?:RequestInit)=>Promise<any>;me:Me}) {
  const [rows,setRows]=useState<UserRow[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[message,setMessage]=useState('');
  // 新建账号抽屉
  const [open,setOpen]=useState(false);
  const [username,setUsername]=useState(''),[displayName,setDisplayName]=useState(''),[password,setPassword]=useState(''),[role,setRole]=useState<'admin'|'member'>('member');
  const form=useRef<HTMLFormElement>(null);
  const heading=useRef<HTMLHeadingElement>(null);
  // 行内重置密码
  const [resetting,setResetting]=useState<string|null>(null),[newPass,setNewPass]=useState('');
  // 钉钉邀请链接
  const [invite,setInvite]=useState<{name:string;url:string}|null>(null);
  const [query,setQuery]=useState('');
  async function load(){try{setRows(await request('/users'));}catch(e){setError(e instanceof Error?e.message:'读取用户失败');}}
  useEffect(()=>{void load();},[]);
  useEffect(()=>{
    if(!open)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy)cancel();};
    addEventListener('keydown',onKey);
    return()=>removeEventListener('keydown',onKey);
  },[open,busy]);
  async function run(fn:()=>Promise<void>,success:string){
    setBusy(true);setError('');setMessage('');
    try{await fn();setMessage(success);await load();}
    catch(e){setError(e instanceof Error?e.message:'操作失败');}
    finally{setBusy(false);}
  }
  function newAccount(){setUsername('');setDisplayName('');setPassword('');setRole('member');setError('');setMessage('');setOpen(true);requestAnimationFrame(()=>heading.current?.focus());}
  function cancel(){setOpen(false);}
  function create(){
    void run(async()=>{
      await request('/users',{method:'POST',body:JSON.stringify({username:username.trim(),password,display_name:displayName.trim(),role})});
      setOpen(false);
    },'账号已创建，把用户名和初始密码告诉对方即可登录。');
  }
  async function inviteDingtalk(u:UserRow){
    setBusy(true);setError('');setInvite(null);
    try{
      const d=await request(`/users/${u.id}/invite-link`,{method:'POST',body:JSON.stringify({provider:'dingtalk'})});
      setInvite({name:u.display_name||u.username,url:`${location.origin}/invite?k=${d.token}`});
    }catch(e){setError(e instanceof Error?e.message:'生成邀请失败');}
    finally{setBusy(false);}
  }
  const q=query.trim().toLowerCase();
  const filtered=rows.filter(u=>!q||u.username.toLowerCase().includes(q)||(u.display_name||'').toLowerCase().includes(q));
  const adminCount=rows.filter(u=>u.role==='admin').length;
  const dingtalkCount=rows.filter(u=>u.identities?.includes('dingtalk')).length;
  return <>
    {error&&<p className="error" role="alert">{error}</p>}
    {message&&<p className="success" role="status">{message}</p>}
    <div className="page-head">
      <div>
        <h1 className="page-title">用户管理</h1>
        <p className="page-sub">开通账号、重置密码、分配角色；员工也可以用钉钉扫码登录。</p>
      </div>
    </div>

    <div className="kpis">
      <div className="kpi"><div className="kpi-l">全部账号</div><div className="kpi-v num">{rows.length}<small>人</small></div><div className="kpi-d">含系统管理员与成员</div></div>
      <div className="kpi"><div className="kpi-l">系统管理员</div><div className="kpi-v num c-green">{adminCount}<small>人</small></div><div className="kpi-d">可修改全部配置与他人账号</div></div>
      <div className="kpi"><div className="kpi-l">钉钉绑定</div><div className="kpi-v num c-blue">{dingtalkCount}<small>人</small></div><div className="kpi-d">绑定后可用钉钉扫码登录并接收推送</div></div>
    </div>

    <div className="seg-tabs">
      <button type="button" className="btn btn-primary btn-sm seg-new" onClick={newAccount}><PlusIcon/>新增账号</button>
      <div className="search-box">
        <input type="search" aria-label="搜索账号" placeholder="搜索用户名或姓名…" value={query} onChange={e=>setQuery(e.target.value)}/>
      </div>
    </div>

    <div className="table-card">
      <div className="table-scroll no-fade">
        <table className="rule-table fit">
          <thead><tr>
            <th style={{width:'20%'}}>用户名</th><th style={{width:'12%'}}>姓名</th>
            <th style={{width:'10%'}}>角色</th><th style={{width:'10%'}}>状态</th>
            <th style={{width:'10%'}}>钉钉</th>
            <th style={{width:'12%'}}>创建时间</th><th style={{width:'26%'}}>操作</th>
          </tr></thead>
          <tbody>
            {filtered.map(u=><tr key={u.id}>
              <td><div className="cell-line"><span className="cell-name">{u.username}</span>{u.id===me.id&&<span className="muted">（我）</span>}</div></td>
              <td>{u.display_name||'—'}</td>
              <td><span className={'st '+(u.role==='admin'?'st-on':'st-queued')}>{u.role==='admin'?'管理员':'成员'}</span></td>
              <td><span className={'st '+(u.is_active!==false?'st-on':'st-off')}>{u.is_active!==false?'启用':'已停用'}</span></td>
              <td>{u.identities?.includes('dingtalk')?<span className="st st-on">已绑定</span>:<span className="muted">未绑定</span>}</td>
              <td className="muted">{stamp(u.created_at)}</td>
              <td>
                {resetting===u.id
                  ? <span className="reset-row">
                      <input type="text" placeholder="新密码（≥8位）" value={newPass} onChange={e=>setNewPass(e.target.value)} autoFocus/>
                      <button className="btn btn-sm btn-primary" disabled={busy||newPass.length<8}
                        onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({password:newPass})});setResetting(null);setNewPass('');},'密码已重置，请通知本人。')}>保存</button>
                      <button className="btn btn-sm" onClick={()=>{setResetting(null);setNewPass('');}}>取消</button>
                    </span>
                  : <>
                      <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>{setResetting(u.id);setNewPass('');}}>重置密码</button>
                      <button className="btn btn-sm btn-quiet" disabled={busy||u.is_active===false}
                        title={u.is_active===false?'账号已停用，先启用再发邀请':'生成一次性钉钉绑定链接'}
                        onClick={()=>inviteDingtalk(u)}>邀请绑定</button>
                      <button className="btn btn-sm btn-quiet" disabled={busy||u.id===me.id}
                        title={u.id===me.id?'不能停用自己':'切换启用/停用'}
                        onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({is_active:u.is_active===false})})},u.is_active===false?'账号已启用。':'账号已停用，对方将无法登录。')}>
                        {u.is_active===false?'启用':'停用'}
                      </button>
                      {u.role!=='admin'
                        ? <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({role:'admin'})})},'已提升为系统管理员。')}>设为管理员</button>
                        : u.id!==me.id&&<button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({role:'member'})})},'已改为成员角色。')}>改为成员</button>}
                    </>}
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
      {!filtered.length&&<div className="empty">{rows.length&&q?'没有符合条件的账号，试试换个搜索词。':'还没有其他账号，点「新增账号」创建第一个。'}</div>}
    </div>

    {invite&&
      <section className="panel invite-panel">
        <h2>钉钉邀请链接已生成 <button className="btn btn-sm" onClick={()=>setInvite(null)}>关闭</button></h2>
        <p className="page-sub">把下面的链接发给 <strong>{invite.name}</strong>：TA 用钉钉打开并扫码后即完成绑定，之后可以「钉钉扫码登录」直接进系统。链接 7 天内有效、只能用一次；重新生成会让旧链接立即作废。</p>
        <div className="screen-link">
          <input readOnly value={invite.url} onFocus={e=>e.currentTarget.select()}/>
          <button className="btn btn-primary" onClick={()=>{void navigator.clipboard.writeText(invite.url);setMessage('邀请链接已复制，去钉钉发给对方吧。');}}>复制链接</button>
        </div>
      </section>}

    {open&&<div className="drawer-layer">
      <div className="drawer-backdrop" onClick={cancel}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="user-editor-title">
        <button type="button" className="dr-close" onClick={cancel} aria-label="关闭新建账号">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">新增 · 用户管理</div>
          <h2 className="dr-title" id="user-editor-title" tabIndex={-1} ref={heading}>新增账号</h2>
          <p className="dr-sub">创建后把用户名和初始密码告诉对方即可登录。</p>
        </div>
        <div className="dr-body">
          <form ref={form} id="user-form" aria-labelledby="user-editor-title" onSubmit={e=>{e.preventDefault();if(password.length>=8)create();}}>
            <label htmlFor="user-username">用户名 <span className="opt">必填，2-64 字符，中英文均可，不含空格</span></label>
            <input id="user-username" name="username" required minLength={2} maxLength={64} value={username} disabled={busy} onChange={e=>setUsername(e.target.value)} placeholder="例如：zhangsan 或 张三"/>
            <label htmlFor="user-display">姓名 <span className="opt">选填，页面上显示的名字</span></label>
            <input id="user-display" name="display_name" maxLength={80} value={displayName} disabled={busy} onChange={e=>setDisplayName(e.target.value)} placeholder="例如：张三"/>
            <label htmlFor="user-password">初始密码 <span className="opt">必填，至少 8 位</span></label>
            <input id="user-password" name="password" required minLength={8} type="text" autoComplete="off" value={password} disabled={busy} onChange={e=>setPassword(e.target.value)}/>
            <label htmlFor="user-role">角色 <span className="opt">管理员可修改全部配置与他人账号</span></label>
            <select id="user-role" name="role" value={role} disabled={busy} onChange={e=>setRole(e.target.value as 'admin'|'member')}><option value="member">成员</option><option value="admin">系统管理员</option></select>
          </form>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={cancel} disabled={busy}>取消</button>
          <button type="submit" form="user-form" className="btn btn-primary" disabled={busy}>{busy?'创建中…':'创建账号'}</button>
        </div>
      </aside>
    </div>}
  </>;
}
