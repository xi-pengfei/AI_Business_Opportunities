import {AutoScroll} from './AutoScroll';
import {sourceName,businessState,fullTime,type Item,type Snapshot} from './types';
import {StatusPill} from './StatusPill';
import './information-flow.css';

export function BusinessFollowup({data,open}:{data:Snapshot;open:(item:Item)=>void}) {
  return <section className="panel business-followup">
    <div className="lib-aurora" aria-hidden="true"><i /><i /><i /><i /></div>
    <h2>商机跟进 <small>{data.pushed_count} 条 · 已认领 {data.assigned_count} 条</small></h2>
    <AutoScroll enabled label="商机推送与认领"><table className="followup-table"><thead><tr>{['标题','信息来源','状态','推送时间','认领人','认领时间'].map(t=><th scope="col" key={t}>{t}</th>)}</tr></thead>
      <tbody>{data.assigned_items.map(i=><tr key={i.id}><td><button className="text-button" onClick={()=>open(i)}>{i.title}</button></td><td>{sourceName(i)}</td><td><StatusPill item={i}/></td><td>{fullTime(i.sent_at)}</td><td>{i.claimed_by||'—'}</td><td>{fullTime(i.claimed_at)}</td></tr>)}</tbody>
    </table></AutoScroll>{!data.assigned_items.length&&<p className="empty">暂无已推送商机</p>}
  </section>;
}

export function FollowupPanels({data,open}:{data:Snapshot;open:(item:Item)=>void}) {
  return <div className="followup-panels">
    <BusinessFollowup data={data} open={open} />
  </div>;
}
