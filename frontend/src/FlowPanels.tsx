import './information-flow.css';
import type React from 'react';
import {AutoScroll} from './AutoScroll';
import {clock, sourceName, businessState, fullTime, type Item} from './types';
import {expandCargo,cargoKey,cargoText,fragmentColor,type Cargo} from './fragments';
import {StatusPill} from './StatusPill';
export function SourceFields({item,landed}: {item:Item;moving:Cargo|null;landed:Set<string>}) {
  const parts = expandCargo([item]);
  const mark = (part: Cargo) => <mark data-source-fragment={cargoKey(part)}
    className={landed.has(cargoKey(part)) ? 'fragment-picked' : ''}
    style={{'--fragment-color':fragmentColor(part.fragmentIndex)} as React.CSSProperties}>{cargoText(part)}</mark>;
  const field = (name: Cargo['field']) => parts.find(p => p.field === name);
  const title=field('title'), published=field('published_at'), captured=field('created_at'), url=field('url');
  return <div className="source-document">
    <h3>{title ? mark(title) : item.title}</h3>
    <div className="document-dates">
      {published && <p>发布时间　{mark(published)}</p>}
      {captured && <p>采集时间　{mark(captured)}</p>}
    </div>
    <h4>原文信息</h4>
    <ol>{parts.filter(p=>p.field==='fragments').map(part => {
      const fragment=item.fragments?.find(f=>f.index===part.fragmentIndex);
      return <li key={cargoKey(part)}><p>{fragment?.before}{mark(part)}{fragment?.after}</p></li>;
    })}</ol>
    {item.url && <><h4>原始网址</h4><p className="document-reference"><a href={item.url} target="_blank" rel="noopener noreferrer">{url ? mark(url) : item.url}</a></p></>}
  </div>;
}
export function Information({ items, open, autoScroll = false, lifecycle = true, slim = false }: { items: Item[]; open: (item: Item) => void; autoScroll?: boolean; lifecycle?: boolean; slim?: boolean }) {
  return <><AutoScroll enabled={autoScroll} label="信息库记录"><table className={"fragment-table information-flow-table" + (slim ? " slim-table" : "")}>
    <thead><tr><th scope="col" data-inbox-field="title">标题</th>{!slim && <><th scope="col">信息来源</th><th scope="col">状态</th></>}<th scope="col" data-inbox-field="fragments">信息片</th>{!slim && <th scope="col" data-inbox-field="url">原始网址</th>}<th scope="col" data-inbox-field="published_at">发布时间</th><th scope="col" data-inbox-field="created_at">采集时间</th>{lifecycle && <><th scope="col">推送时间</th><th scope="col">认领人</th><th scope="col">认领时间</th></>}</tr></thead>
    <tbody>{items.map(item => <tr key={item.id} data-library-item={item.id}>
      <td data-field="title"><button className="text-button" onClick={()=>open(item)}>{item.title || '—'}</button></td>
      {!slim && <><td>{sourceName(item)}</td><td><StatusPill item={item}/></td></>}
      <td data-field="fragments"><div className="fragment-tags">{(item.fragments || []).map(f => <button onClick={()=>open(item)}
        className="fragment-tag" key={f.index} data-landed-fragment={`${item.id}:fragments:${f.index}`}>{f.text}</button>)}</div></td>
      {!slim && <td data-field="url">{item.url ? <a className="single-line" href={item.url} target="_blank" rel="noopener noreferrer">{new URL(item.url).hostname}</a> : '—'}</td>}
      <td data-field="published_at">{item.published_at || '—'}</td><td data-field="created_at">{lifecycle?fullTime(item.created_at):item.created_at?clock(item.created_at):'—'}</td>
      {lifecycle && <><td>{fullTime(item.sent_at)}</td><td>{item.requires_claim===false?'—':item.claimed_by||'—'}</td><td>{item.requires_claim===false?'—':fullTime(item.claimed_at)}</td></>}
    </tr>)}</tbody>
  </table></AutoScroll>{!items.length && <p className="empty">暂无信息</p>}</>;
}
