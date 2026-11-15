import { businessState, type Item } from './types';

/* 状态胶囊：语义→颜色统一映射（配合 design-tokens.css 的 .pill-*）。
   绿=完成态，琥珀=等待/待处理，红=失败/限流，蓝=已推送，灰=其余。 */
const toneOf = (i: Item) => {
  const s = i.business_status || 'collected';
  if (s === 'failed') return 'dang';
  if (s === 'sent') return 'info';
  if (s === 'waiting_claim' || s === 'review_pending' || s === 'review_required' || s === 'sending' || s === 'unknown') return 'warn';
  if (s === 'claimed' || s === 'collected' || s === 'merged' || s === 'restored') return 'ok';
  return 'mute';
};

export function StatusPill({ item }: { item: Item }) {
  return <span className={`pill pill-${toneOf(item)}`}>{businessState(item)}</span>;
}
