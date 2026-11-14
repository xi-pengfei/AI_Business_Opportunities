import { registerMap, use } from 'echarts/core';
import { MapChart, ScatterChart, TreemapChart } from 'echarts/charts';
import { GeoComponent } from 'echarts/components';
import china from './assets/china-provinces.json';
import { Plot } from './Charts';
import type { ChartSelection } from './Charts';
import type { Snapshot } from './types';
use([MapChart, ScatterChart, TreemapChart, GeoComponent]);
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
      <div className="province-treemap">
        <Plot label={`各省份信息数量，色块面积代表条数：${regions.map(r=>`${r.name}${r.count}条`).join('，')}`}
          option={{tooltip:{trigger:'item',formatter:(p:{name:string;value:number})=>`${p.name} · ${p.value} 条`},
            series:[{type:'treemap',name:'省份分布',left:0,right:0,top:0,bottom:0,
              roam:false,nodeClick:false,squareRatio:1,breadcrumb:{show:false},visibleMin:0,childrenVisibleMin:0,
              label:{show:true,formatter:'{b}\n{c} 条',fontSize:10,lineHeight:12,padding:0,color:'#162a39',overflow:'truncate'},
              upperLabel:{show:false},itemStyle:{borderColor:dark?'#1b2128':'#fff',borderWidth:1,gapWidth:3},
              levels:[{itemStyle:{borderWidth:0,gapWidth:3}}],
              data:[...regions].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')).map((r,i)=>({name:r.name,value:r.count,
                itemStyle:{color:['#77c7d5','#eda2ba','#a8cda6','#edc779','#b7afe6','#7fc9b7'][i%6]}}))}]
          }}/>
        {!regions.length&&<span className="chart-empty">暂无地区信息</span>}
      </div></div>
  </section>;
}
