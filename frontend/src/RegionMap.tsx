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
  const regionTones = ['#294650','#345862','#406A73','#447177','#48767A'];
  const located = regions.reduce((sum, r) => sum + r.count, 0);
  const maxCount = Math.max(1,...regions.map(r=>r.count));
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
    <div className="map-heading"><h2>商机地图</h2><span>已定位 {located} / 待定位 {data.region_unknown || 0}</span></div>
      <div className="map-comparison"><Plot label="商机项目或采购单位省级分布，点击省份查看信息。"
        onPick={i => { if(rows[i]?.value) open(rows[i].short); }}
        option={{ tooltip: {trigger: 'item', formatter: (p: {name: string; value: number | number[]}) => `${p.name} · ${Array.isArray(p.value) ? p.value[2] : p.value || 0} 条`},
          visualMap: {show: false, min: 0, max: Math.max(1,...regions.map(r=>r.count)), seriesIndex: 0,
            inRange: {color: [dark?'#14242B':'#e4eff5','#345862','#48767A']}},
          geo: {map: 'china-provinces', roam: false, layoutCenter: ['50%', '50%'], layoutSize: '100%',
            itemStyle: {areaColor:dark?'#14242B':'#e4eff5',borderColor:dark?'#42606C':'#9ec1d3'}, emphasis:{itemStyle:{areaColor:'#78A9C4'},label:{color:'#101A20'}}},
          series: [{type:'map',map:'china-provinces',geoIndex:0,data:rows.map(r=>({name:r.name,value:r.value}))},
            {type:'scatter',coordinateSystem:'geo',data:rows.map(r=>({name:r.name,value:[...(r.center || [0,0]),r.value]})),
              symbolSize:(v:number[])=>v[2] ? Math.min(35, 7+Math.sqrt(v[2])*2) : 0,
              itemStyle:{color:'#C8AD78',opacity:0.9}}] }} />
      <div className="province-treemap">
        <Plot label={`各省份信息数量，色块面积代表条数：${regions.map(r=>`${r.name}${r.count}条`).join('，')}`}
          option={{tooltip:{trigger:'item',formatter:(p:{name:string;value:number})=>`${p.name} · ${p.value} 条`},
            series:[{type:'treemap',name:'省份分布',left:0,right:0,top:0,bottom:0,
              roam:false,nodeClick:false,squareRatio:1,breadcrumb:{show:false},visibleMin:0,childrenVisibleMin:0,
              label:{show:true,formatter:'{b}\n{c} 条',fontSize:10,lineHeight:12,padding:0,color:'#F1F5F5',overflow:'truncate'},
              upperLabel:{show:false},itemStyle:{borderColor:dark?'#000':'#fff',borderWidth:1,gapWidth:3},
              levels:[{itemStyle:{borderWidth:0,gapWidth:3}}],
              data:[...regions].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')).map(r=>({name:r.name,value:r.count,
                itemStyle:{color:regionTones[Math.round((r.count/maxCount)*(regionTones.length-1))]}}))}]
          }}/>
        {!regions.length&&<span className="chart-empty">暂无地区信息</span>}
      </div></div>
  </section>;
}
