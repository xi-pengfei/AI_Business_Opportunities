import {useEffect,useState} from 'react';
import type {Me} from './types';

type UserRow=Me;
const stamp=(t?:number)=>t?new Date(t*1000).toLocaleString('zh-CN',{year:'2-digit',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';

const PlusIcon=()=><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;

export function Users({request,me}:{request:(path:string,options?:RequestInit)=>Promise<any>;me:Me}) {
  const [rows,setRows]=useState<UserRow[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[message,setMessage]=useState('');
  // 新建表单
  const [username,setUsername]=useState(''),[displayName,setDisplayName]=useState(''),[password,setPassword]=useState(''),[role,setRole]=useState<'admin'|'member'>('member');
  // 行内重置密码
  const [resetting,setResetting]=useState<string|null>(null),[newPass,setNewPass]=useState('');
  async function load(){try{setRows(await request('/users'));}catch(e){setError(e instanceof Error?e.message:'读取用户失败');}}
  useEffect(()=>{void load();},[]);
  async function run(fn:()=>Promise<void>,success:string){
    setBusy(true);setError('');setMessage('');
    try{await fn();setMessage(success);await load();}
    catch(e){setError(e instanceof Error?e.message:'操作失败');}
    finally{setBusy(false);}
  }
  function create(){
    void run(async()=>{
      await request('/users',{method:'POST',body:JSON.stringify({username:username.trim(),password,display_name:displayName.trim(),role})});
      setUsername('');setDisplayName('');setPassword('');setRole('member');
    },'账号已创建，把用户名和初始密码告诉对方即可登录。');
  }
  return <>
    {error&&<p className="error" role="alert">{error}</p>}
    {message&&<p className="success" role="status">{message}</p>}
    <div className="page-head">
      <div>
        <h1 className="page-title">用户管理</h1>
        <p className="page-sub">管理员在此开通账号、重置密码、分配角色。员工账号也可在登录后自行修改密码。</p>
      </div>
    </div>
    <section className="panel">
      <h2>新建账号</h2>
      <form className="user-create" onSubmit={e=>{e.preventDefault();if(password.length>=8)create();}}>
        <label>用户名 <input required minLength={2} maxLength={64} pattern="[A-Za-z0-9_.@-]+" title="字母、数字、点、下划线、连字符、@" value={username} onChange={e=>setUsername(e.target.value)}/></label>
        <label>姓名 <input maxLength={80} value={displayName} onChange={e=>setDisplayName(e.target.value)}/></label>
        <label>初始密码（至少 8 位） <input required minLength={8} type="text" autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)}/></label>
        <label>角色 <select value={role} onChange={e=>setRole(e.target.value as 'admin'|'member')}><option value="member">成员</option><option value="admin">系统管理员</option></select></label>
        <button type="submit" className="btn btn-primary" disabled={busy}><PlusIcon/>创建账号</button>
      </form>
    </section>
    <section className="panel">
      <h2>全部账号 <small>{rows.length} 人</small></h2>
      <div className="table-scroll">
        <table>
          <thead><tr>
            <th style={{width:'18%'}}>用户名</th><th style={{width:'18%'}}>姓名</th>
            <th style={{width:'14%'}}>角色</th><th style={{width:'14%'}}>状态</th>
            <th style={{width:'18%'}}>创建时间</th><th style={{width:'18%'}}>操作</th>
          </tr></thead>
          <tbody>
            {rows.map(u=><tr key={u.id}>
              <td><code>{u.username}</code>{u.id===me.id&&<span className="muted">（我）</span>}</td>
              <td>{u.display_name||'—'}</td>
              <td><span className={'st '+(u.role==='admin'?'st-on':'st-queued')}>{u.role==='admin'?'管理员':'成员'}</span></td>
              <td><span className={'st '+(u.is_active!==false?'st-on':'st-off')}>{u.is_active!==false?'启用':'已停用'}</span></td>
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
                      <button className="btn btn-sm" disabled={busy} onClick={()=>{setResetting(u.id);setNewPass('');}}>重置密码</button>
                      <button className="btn btn-sm" disabled={busy||u.id===me.id}
                        title={u.id===me.id?'不能停用自己':'切换启用/停用'}
                        onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({is_active:u.is_active===false})})},u.is_active===false?'账号已启用。':'账号已停用，对方将无法登录。')}>
                        {u.is_active===false?'启用':'停用'}
                      </button>
                      {u.role!=='admin'
                        ? <button className="btn btn-sm" disabled={busy} onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({role:'admin'})})},'已提升为系统管理员。')}>设为管理员</button>
                        : u.id!==me.id&&<button className="btn btn-sm" disabled={busy} onClick={()=>run(async()=>{await request(`/users/${u.id}`,{method:'PATCH',body:JSON.stringify({role:'member'})})},'已改为成员角色。')}>改为成员</button>}
                    </>}
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
      {!rows.length&&<p className="empty">还没有其他账号。</p>}
    </section>
  </>;
}
