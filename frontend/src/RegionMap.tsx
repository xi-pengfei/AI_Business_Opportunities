import { registerMap, use } from 'echarts/core';
import { MapChart, ScatterChart } from 'echarts/charts';
import { GeoComponent } from 'echarts/components';
import china from './assets/china-provinces.json';
import { Plot } from './Charts';
import type { ChartSelection } from './Charts';
import type { Snapshot } from './types';
use([MapChart, ScatterChart, GeoComponent]);
registerMap('china-provinces', china as Parameters<typeof registerMap>[1]);
export function RegionMap({data, onSelect}: {data: Snapshot; onSelect?: (r: ChartSelection) => void}) {
  const regions = data.regions || [];
  const features = china.features.filter(f => f.properties.name);
  const rows = features.map(f => {
    const name = f.properties.name;
    const region = regions.find(r => name.startsWith(r.name));
    return {name, short: region?.name || name, value: region?.count || 0,
      center: f.properties.center || f.properties.centroid};
  });
  const open = (name: string) => onSelect?.({ start: Math.max(0, data.server_time - 90 * 86400), end: data.server_time,
    region: name, label: `${name} · 地区信息` });
  return <section className="panel chart-panel map-panel">
    <h2>商机地图</h2>
      <Plot label="省级信息分布，点击省份查看信息；只使用原文地区依据，人员分配尚未接入。"
        onPick={i => { if(rows[i]?.value) open(rows[i].short); }}
        option={{ tooltip: {trigger: 'item', formatter: (p: {name: string; value: number | number[]}) => `${p.name} · ${Array.isArray(p.value) ? p.value[2] : p.value || 0} 条`},
          visualMap: {show: false, min: 0, max: Math.max(1,...regions.map(r=>r.count)), seriesIndex: 0,
            inRange: {color: ['#24394c','#167db1','#70c3ce']}},
          geo: {map: 'china-provinces', roam: false, layoutCenter: ['50%', '50%'], layoutSize: '100%',
            itemStyle: {areaColor:'#24394c',borderColor:'#5284a4'}, emphasis:{itemStyle:{areaColor:'#FFBF00'},label:{color:'#fff'}}},
          series: [{type:'map',map:'china-provinces',geoIndex:0,data:rows.map(r=>({name:r.name,value:r.value}))},
            {type:'scatter',coordinateSystem:'geo',data:rows.map(r=>({name:r.name,value:[...(r.center || [0,0]),r.value]})),
              symbolSize:(v:number[])=>v[2] ? Math.min(35, 7+Math.sqrt(v[2])*2) : 0,
              itemStyle:{color:'#d8ba7c',opacity:0.9}}] }} />
  </section>;
}
