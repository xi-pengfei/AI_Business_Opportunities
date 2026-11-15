import {Children, cloneElement, isValidElement, useRef, type ReactElement, type ReactNode} from 'react';
import {rotateRows, useUpwardLoop} from './useUpwardLoop';

function rotateBody(node: ReactNode, offset: number): ReactNode {
  if (!isValidElement<{children?: ReactNode}>(node)) return node;
  if (node.type === 'tbody') return cloneElement(node, {}, rotateRows(Children.toArray(node.props.children), offset));
  return cloneElement(node, {}, Children.map(node.props.children, child => rotateBody(child, offset)));
}
export function AutoScroll({children, enabled = false, label}: {
  children: ReactNode; enabled?: boolean; label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const offset = useUpwardLoop(ref, 'tbody > tr', enabled);
  return <div className="table-scroll auto-scroll" ref={ref} role="region" aria-label={label} tabIndex={0}>{rotateBody(children, offset) as ReactElement}</div>;
}
