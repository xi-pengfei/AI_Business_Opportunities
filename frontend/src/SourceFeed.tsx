import {SourceFields} from './FlowPanels';
import type {Item} from './types';
import type {Cargo} from './fragments';

export function SourceFeed({items,moving,landed}: {items:Item[];moving:Cargo|null;landed:Set<string>}) {
  return <div className="terminal-feed" role="region" aria-label="信息来源原文" tabIndex={0}>
    {items.map(entry=><article className={`source-preview ${moving?.id===entry.id?'cargo-source':''}`} key={entry.id}>
      <SourceFields item={entry} moving={moving} landed={landed}/>
    </article>)}
  </div>;
}
