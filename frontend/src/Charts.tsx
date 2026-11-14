import { useEffect, useRef, useState } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart, ScatterChart, SankeyChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import type { Snapshot } from "./types";
import { clock } from "./types";
import { RegionMap } from "./RegionMap";
use([
  LineChart,
  BarChart,
  ScatterChart,
  SankeyChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  VisualMapComponent,
  CanvasRenderer,
]);
export type ChartSelection = { start: number; end: number; provider?: string; region?: string; label: string };
export function Plot({ option, label, onPick }: { option: EChartsCoreOption; label: string;
  onPick?: (index: number, series: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [dark,setDark]=useState(!!document.fullscreenElement);
  useEffect(()=>{const update=()=>setDark(!!document.fullscreenElement);document.addEventListener("fullscreenchange",update);return()=>document.removeEventListener("fullscreenchange",update);},[]);
  const chart = useRef<ReturnType<typeof init> | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const instance = init(ref.current);
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption(
      {
        ...option,
        animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
        aria: { enabled: true, label: { description: label } },
        backgroundColor: "transparent",
        textStyle: {
          color: dark ? "#a6afb9" : "#53616f",
          fontFamily: '"PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
          fontSize: 12,
        },
        tooltip: {
          trigger: "axis",
          renderMode: "richText",
          backgroundColor: dark ? "#24292f" : "#ffffff",
          borderColor: dark ? "#353b43" : "#dbe2e8",
          textStyle: { color: dark ? "#e5e8ec" : "#203040" },
          ...(option.tooltip as Record<string, unknown> | undefined),
        },
        grid: {
          top: 16,
          right: 24,
          bottom: 52,
          left: 40,
          ...(option.grid as Record<string, unknown> | undefined),
        },
      },
      true,
    );
  }, [option,dark]);
  useEffect(() => {
    const instance = chart.current;
    const click = (params: unknown) => {
      const p = params as { dataIndex?: number; seriesName?: string };
      if (typeof p.dataIndex === "number") onPick?.(p.dataIndex, p.seriesName || "");
    };
    instance?.on("click", click);
    return () => { instance?.off("click", click); };
  }, [onPick]);
  return <div className="plot" ref={ref} role="img" aria-label={label} />;
}
export function Charts({ data, onSelect, dark = false }: { data: Snapshot; onSelect: (range: ChartSelection) => void; dark?:boolean }) {
  const ink=dark?'#afbbc8':'#53616f', grid=dark?'#303b46':'#e8edf2';
  const colors=['#54b8ca','#e58aaa','#8ebd98','#e8bb69','#a5a0df'];
  const sources=[...new Set(['网络商机','小红书','客户监测',...Object.keys(data.information_sources||{})])].map(name=>[name,data.information_sources?.[name]||0] as const);
  const flows=data.information_flows||[];
  const nodes=[...new Set(flows.flatMap(f=>[f.source,f.target]))];
  const history=data.backlog_history||[];
  // Preserve gaps in observations; a stopped scheduler must not imply a flat backlog.
  const samples:number[][]=[];
  history.forEach((row,i)=>{if(i&&row[0]-history[i-1][0]>90)samples.push([row[0]-60,NaN,NaN]);samples.push(row);});
  const axis={axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ink,fontSize:11,hideOverlap:true},splitLine:{lineStyle:{color:grid}}};
  return <>
    <section className="panel chart-panel"><h2>来源分布 <small>有效入库 / 条</small></h2><Plot label={sources.map(([s,n])=>`${s} ${n}条`).join('，')} option={{
      grid:{left:70,right:30,bottom:26,top:12},xAxis:{...axis,type:'value',minInterval:1,splitNumber:3},
      yAxis:{...axis,type:'category',inverse:true,data:sources.map(s=>s[0]),splitLine:{show:false}},
      series:[{type:'bar',barMaxWidth:18,label:{show:true,position:'right',color:ink},data:sources.map(([,value],i)=>({value,itemStyle:{color:colors[i%colors.length],borderRadius:5}}))}]
    }}/></section>
    <section className="panel chart-panel"><h2>任务积压 <small>未认领 {data.backlog_count} 条</small></h2><div className="plot-wrap"><Plot label="最近一小时实际未认领商机，按待推送与已推送待认领堆叠；客户资讯不计入" option={{
      color:['#54b8ca','#e58aaa'],grid:{left:32,right:12,top:32,bottom:26},
      legend:{top:0,itemWidth:10,itemHeight:5,textStyle:{color:ink,fontSize:11}},
      xAxis:{...axis,type:'time',min:(data.server_time-3600)*1000,max:data.server_time*1000,splitNumber:3,splitLine:{show:false},axisLabel:{...axis.axisLabel,formatter:(v:number)=>clock(v/1000).slice(0,5)}},
      yAxis:{...axis,type:'value',min:0,minInterval:1,splitNumber:3},
      series:['待推送','已推送待认领'].map((name,i)=>({name,type:'line',stack:'backlog',smooth:.3,showSymbol:history.length<2,symbolSize:6,connectNulls:false,lineStyle:{width:2},
        areaStyle:{opacity:.65,color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:i?'#e58aaa':'#54b8ca'},{offset:1,color:i?'rgba(229,138,170,0.04)':'rgba(84,184,202,0.04)'}]}},
        data:samples.map(r=>[r[0]*1000,Number.isNaN(r[i+1])?null:r[i+1]])}))
    }}/>{!history.length&&<span className="chart-empty">等待首次积压记录</span>}</div></section>
    <section className="panel chart-panel"><h2>信息流向 <small>来源 → 去向</small></h2><div className="plot-wrap"><Plot label="已推送信息从采集来源流向待认领、认领人或客户播报" option={{
      tooltip:{trigger:'item'},series:[{type:'sankey',left:8,right:90,top:16,bottom:12,nodeWidth:9,nodeGap:18,draggable:false,
        label:{color:ink,fontSize:11},data:nodes.map((name,i)=>({name,itemStyle:{color:colors[i%colors.length]}})),links:flows,
        lineStyle:{color:'source',curveness:.5,opacity:.28},emphasis:{focus:'adjacency'}}]
    }}/>{!flows.length&&<span className="chart-empty">等待信息推送</span>}</div></section>
    <RegionMap data={data} onSelect={onSelect} dark={dark}/>
  </>;
}
