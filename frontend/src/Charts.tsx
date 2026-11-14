import { useEffect, useRef } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart, ScatterChart } from "echarts/charts";
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
use([
  LineChart,
  BarChart,
  ScatterChart,
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
          color: "#a6afb9",
          fontFamily: '"PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
          fontSize: 12,
        },
        tooltip: {
          trigger: "axis",
          renderMode: "richText",
          backgroundColor: "#24292f",
          borderColor: "#353b43",
          textStyle: { color: "#e5e8ec" },
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
  }, [option]);
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
export function Charts({ data, onOpenItem }: { data: Snapshot; onSelect?: (range: ChartSelection) => void; onOpenItem?: (id:string)=>void }) {
  const history = data.collection_history || [];
  const axis = {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: "#a6afb9", fontSize: 12, margin: 14 },
    splitLine: { lineStyle: { color: "#30363e", width: 1 } },
  };
  const x = {
    ...axis,
    type: "category",
    data: history.map((r) => clock(r[0]).slice(0, 5)),
    boundaryGap: false,
    splitLine: { show: false },
    axisLabel: { ...axis.axisLabel, hideOverlap: true },
  };
  const y = { ...axis, type: "value", min: 0, minInterval: 1, splitNumber: 3 };
  const line = (name: string, column: number, color: string) => ({
    name,
    type: "line",
    data: history.map((r) => r[column]),
    smooth: 0.35,
    smoothMonotone: "x",
    showSymbol: false,
    symbol: "circle",
    symbolSize: 5,
    lineStyle: { color, width: 2 },
    itemStyle: { color },
    emphasis: { focus: "series" },
  });
  const sources = Object.entries(data.category_counts || {}).sort(
    (a, b) => b[1] - a[1],
  );
  const names: Record<string, string> = {
    demo: "演示来源",
    tavily: "全网搜索",
  };
  const colors = ["#70c3ce", "#9bbb92", "#e393b0", "#d8ba7c", "#a5a4d4"];
  return (
    <>
      <section className="panel chart-panel">
        <h2>
          采集趋势 <small>累计 / 条</small>
        </h2>
        <Plot
          label="近30分钟累计采集结果与去重归集信息"
          option={{
            xAxis: x,
            yAxis: y,
            legend: {
              bottom: 0,
              icon: "roundRect",
              itemWidth: 16,
              itemHeight: 3,
              itemGap: 24,
              textStyle: { color: "#a6afb9", fontSize: 12 },
            },
            series: [line("采集", 1, "#70c3ce"), line("归集", 2, "#e393b0")],
          }}
        />
      </section>
      <section className="panel chart-panel">
        <h2>
          来源分布 <small>归集 / 条</small>
        </h2>
        <div className="plot-wrap">
          <Plot
            label={
              sources.length
                ? sources
                    .map(([name, n]) => `${names[name] || name} ${n}条`)
                    .join("，")
                : "暂无归集来源"
            }
            option={{
              grid: { left: 82, bottom: 32 },
              xAxis: y,
              yAxis: {
                ...axis,
                type: "category",
                inverse: true,
                data: sources.map(([name]) => names[name] || name),
                splitLine: { show: false },
              },
              series: [
                {
                  type: "bar",
                  barMaxWidth: 24,
                  label: { show: true, position: "right", color: "#a6afb9" },
                  data: sources.map(([, value], i) => ({
                    value,
                    itemStyle: {
                      color: colors[i % colors.length],
                      borderRadius: 8,
                    },
                  })),
                },
              ],
            }}
          />
          {!sources.length && <span className="chart-empty">等待来源归集</span>}
        </div>
      </section>
      <section className="panel chart-panel">
        <h2>任务积压 <small>未认领 {data.backlog_count} 条</small></h2>
        <Plot label="每个圆点是一条未认领信息；横轴入库时间，纵轴信息片数量，圆点越大等待越久。点击查看原文。"
          onPick={(index, category)=>{const point=(data.backlog_points||[]).filter(p=>p.category===category)[index]; if(point) onOpenItem?.(point.id);}}
          option={{
            color:['#dd4444','#fec42c','#80F1BE','#70c3ce','#e393b0'],
            grid:{left:38,right:20,top:42,bottom:40},
            legend:{top:0,type:'scroll',textStyle:{color:'#a6afb9',fontSize:10},itemWidth:8,itemHeight:8},
            tooltip:{trigger:'item',formatter:(p:{value:number[];seriesName:string})=>`${p.seriesName}\n等待 ${p.value[2].toFixed(1)} 小时\n${p.value[1]} 个信息片`},
            xAxis:{...axis,type:'time',splitLine:{show:false},axisLabel:{fontSize:10,hideOverlap:true,color:'#a6afb9'},name:'入库',nameLocation:'middle',nameGap:25,nameTextStyle:{color:'#a6afb9',fontSize:10}},
            yAxis:{...axis,type:'value',name:'信息片 / 个',nameTextStyle:{color:'#a6afb9',fontSize:10},min:0,minInterval:1,splitLine:{show:false}},
            visualMap:[{show:false,dimension:2,min:0,max:Math.max(1,...(data.backlog_points||[]).map(p=>p.waiting_hours)),inRange:{symbolSize:[7,24]}},
              {show:false,dimension:2,min:0,max:Math.max(1,...(data.backlog_points||[]).map(p=>p.waiting_hours)),inRange:{colorLightness:[.8,.5]}}],
            series:[...new Set((data.backlog_points||[]).map(p=>p.category))].map(category=>({
              type:'scatter',name:category,itemStyle:{opacity:.8,shadowBlur:10,shadowOffsetX:0,shadowOffsetY:0,shadowColor:'rgba(0,0,0,0.3)'},
              data:(data.backlog_points||[]).filter(p=>p.category===category).map(p=>[p.created_at*1000,p.fragments,p.waiting_hours])
            }))
          }}/>
      </section>
    </>
  );
}
