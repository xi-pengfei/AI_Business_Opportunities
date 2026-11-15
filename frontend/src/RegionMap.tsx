import { use } from 'echarts/core';
import { ScatterChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { Plot } from './Charts';
import type { ChartSelection } from './Charts';
import type { Snapshot } from './types';
use([ScatterChart, GridComponent, TooltipComponent, LegendComponent, AriaComponent, VisualMapComponent, CanvasRenderer]);
const regionTones = ['#74d7e8','#9be3b1','#C8AD78','#db72ce','#e99183','#78A9C4'];
/* 商机地图：以散点气泡呈现各省信息量，点的大小与颜色代表条数，点击可下钻该地区信息。 */
export function RegionMap({data, onSelect, dark=false}: {data: Snapshot; dark?:boolean; onSelect?: (r: ChartSelection) => void}) {
  const regions = [...(data.regions || [])].sort((a, b) => b.count - a.count);
  const located = regions.reduce((sum, r) => sum + r.count, 0);
  const ink = dark ? '#D9E0E4' : '#53616f';
  const grid = dark ? 'rgba(255,255,255,.12)' : '#e8edf2';
  const axis = {
    axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ink,fontSize:11,hideOverlap:true},
    splitLine:{lineStyle:{color:grid}},
  };
  const open = (name: string) => onSelect?.({ start: Math.max(0, data.server_time - 90 * 86400), end: data.server_time,
    region: name, label: `${name} · 地区信息` });
  return <section className="panel chart-panel map-panel">
    <div className="map-heading"><h2>商机地图</h2><span>已定位 {located} / 待定位 {data.region_unknown || 0}</span></div>
    <div className="map-scatter">
      <Plot
        label={`各省商机信息数量散点图：${regions.map(r=>`${r.name}${r.count}条`).join('，')}`}
        onPick={i => { if (regions[i]?.count) open(regions[i].name); }}
        option={{
          tooltip: {trigger: 'item', formatter: (p: {name: string; value: number}) => `${p.name} · ${p.value} 条`},
          grid: {left: 70, right: 44, bottom: 24, top: 14},
          xAxis: {...axis, type: 'value', minInterval: 1, splitNumber: 3, splitLine: {show: false}},
          yAxis: {...axis, type: 'category', inverse: true, data: regions.map(r => r.name), splitLine: {show: false}},
          series: [{
            type: 'scatter',
            symbolSize: (v: number) => Math.min(34, 8 + Math.sqrt(v) * 2.2),
            label: {show: true, position: 'right', formatter: (p: {value: number}) => `${p.value} 条`, color: ink, fontSize: 10},
            itemStyle: {opacity: 0.9},
            emphasis: {focus: 'self'},
            data: regions.map((r, i) => ({name: r.name, value: r.count,
              itemStyle: {color: regionTones[i % regionTones.length], borderRadius: 999}})),
          }],
        }} />
      {!regions.length && <span className="chart-empty">暂无地区信息</span>}
    </div>
  </section>;
}
