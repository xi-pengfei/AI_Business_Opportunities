import type React from 'react';
import {clock, type Item} from './types';
import {expandCargo,cargoKey,cargoText,fragmentColor,type Cargo} from './fragments';
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
      {published && <p>新闻时间　{mark(published)}</p>}
      {captured && <p>采集时间　{mark(captured)}</p>}
    </div>
    <h4>原文信息</h4>
    <ol>{parts.filter(p=>p.field==='fragments').map(part => {
      const fragment=item.fragments?.find(f=>f.index===part.fragmentIndex);
      return <li key={cargoKey(part)}><p>{fragment?.before}{mark(part)}{fragment?.after}</p></li>;
    })}</ol>
    {url && <><h4>来源引用</h4><p className="document-reference"><a href={item.url} target="_blank" rel="noopener noreferrer">{mark(url)}</a></p></>}
  </div>;
}
export function Information({ items, open }: { items: Item[]; open: (item: Item) => void }) {
  return <><div className="table-scroll"><table className="fragment-table">
    <thead><tr><th data-inbox-field="title">标题</th><th data-inbox-field="fragments">信息片</th><th data-inbox-field="url">原始网址</th><th data-inbox-field="published_at">新闻时间</th><th data-inbox-field="created_at">采集时间</th></tr></thead>
    <tbody>{items.map(item => <tr key={item.id} data-library-item={item.id}>
      <td data-field="title"><button className="text-button" onClick={()=>open(item)}>{item.title || '—'}</button></td>
      <td data-field="fragments"><div className="fragment-tags">{(item.fragments || []).map(f => <button onClick={()=>open(item)}
        className="fragment-tag" key={f.index} data-landed-fragment={`${item.id}:fragments:${f.index}`}>{f.text}</button>)}</div></td>
      <td data-field="url">{item.url ? <a className="single-line" href={item.url} target="_blank" rel="noopener noreferrer">{item.url}</a> : '—'}</td>
      <td data-field="published_at">{item.published_at || '—'}</td><td data-field="created_at">{item.created_at?clock(item.created_at):'—'}</td>
    </tr>)}</tbody>
  </table></div>{!items.length && <p className="empty">暂无待分配信息</p>}</>;
}
