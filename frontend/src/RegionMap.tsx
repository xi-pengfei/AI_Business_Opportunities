import { registerMap, use } from 'echarts/core';
import { MapChart, ScatterChart } from 'echarts/charts';
import { GeoComponent } from 'echarts/components';
import china from './assets/china-provinces.json';
import { Plot } from './Charts';
import type { ChartSelection } from './Charts';
import type { Snapshot } from './types';
use([MapChart, ScatterChart, GeoComponent]);
registerMap('china-provinces', china as Parameters<typeof registerMap>[1]);
export function RegionMap({data, onSelect, dark=false}: {data: Snapshot; dark?:boolean; onSelect?: (r: ChartSelection) => void}) {
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
      <div className="map-comparison"><Plot label="省级信息分布，点击省份查看信息；只使用原文地区依据，人员分配尚未接入。"
        onPick={i => { if(rows[i]?.value) open(rows[i].short); }}
        option={{ tooltip: {trigger: 'item', formatter: (p: {name: string; value: number | number[]}) => `${p.name} · ${Array.isArray(p.value) ? p.value[2] : p.value || 0} 条`},
          visualMap: {show: false, min: 0, max: Math.max(1,...regions.map(r=>r.count)), seriesIndex: 0,
            inRange: {color: [dark?'#24394c':'#e4eff5','#479fc3','#70c3ce']}},
          geo: {map: 'china-provinces', roam: false, layoutCenter: ['50%', '50%'], layoutSize: '100%',
            itemStyle: {areaColor:dark?'#24394c':'#e4eff5',borderColor:dark?'#5284a4':'#9ec1d3'}, emphasis:{itemStyle:{areaColor:'#FFBF00'},label:{color:'#fff'}}},
          series: [{type:'map',map:'china-provinces',geoIndex:0,data:rows.map(r=>({name:r.name,value:r.value}))},
            {type:'scatter',coordinateSystem:'geo',data:rows.map(r=>({name:r.name,value:[...(r.center || [0,0]),r.value]})),
              symbolSize:(v:number[])=>v[2] ? Math.min(35, 7+Math.sqrt(v[2])*2) : 0,
              itemStyle:{color:'#d8ba7c',opacity:0.9}}] }} />
      <div className="province-ranking" aria-label="省份信息数量排行">{[...regions].sort((a,b)=>b.count-a.count).map((r,i)=><div className="province-row" key={r.name}>
        <span>{r.name}</span><span className="province-track"><i style={{width:`${r.count/Math.max(1,...regions.map(x=>x.count))*100}%`,background:['#54b8ca','#e58aaa','#8ebd98','#e8bb69','#a5a0df'][i%5]}}/></span><b>{r.count}</b>
      </div>)}{!regions.length&&<span className="hint">暂无地区信息</span>}</div></div>
  </section>;
}
