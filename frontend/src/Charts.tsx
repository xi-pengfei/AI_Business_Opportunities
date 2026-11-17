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
export function Plot({ option, label }: { option: EChartsCoreOption; label: string }) {
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
          fontSize: 13,
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
  return <div className="plot" ref={ref} role="img" aria-label={label} />;
}

/** 图表配色主题：大屏深色 / 控制台浅色共用 */
const chartTheme = (dark: boolean) => {
  const ink = dark ? "#D9E0E4" : "#53616f";
  const grid = dark ? "rgba(255,255,255,.12)" : "#e8edf2";
  const axis = { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: ink, fontSize: 12, hideOverlap: true }, splitLine: { lineStyle: { color: grid } } };
  return { ink, grid, axis, colors: ["#74d7e8", "#78A9C4", "#9be3b1"], hitColors: ["#dd4444", "#fec42c", "#80F1BE"] };
};

/** 来源分布：有效入库条数的横向条形图（来源多于 6 个时自动轮播） */
export function SourcePanel({ data, dark = false }: { data: Snapshot; dark?: boolean }) {
  const { ink, colors, axis } = chartTheme(dark);
  const sources = Object.entries(data.information_sources || {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"));
  const [sourcePage, setSourcePage] = useState(0);
  const sourcePages = Math.max(1, Math.ceil(sources.length / 6));
  useEffect(() => { if (sourcePages <= 1) return; const timer = window.setInterval(() => setSourcePage(p => (p + 1) % sourcePages), 8000); return () => clearInterval(timer); }, [sourcePages]);
  const visibleSources = sources.slice((sourcePage % sourcePages) * 6, (sourcePage % sourcePages + 1) * 6);
  return <section className="panel chart-panel"><h2>来源分布 <small>已启动 · 有效入库 / 条{sourcePages > 1 ? ` · ${sourcePage % sourcePages + 1}/${sourcePages}` : ""}</small></h2><div className="plot-wrap"><Plot label={sources.map(([s, n]) => `${s} ${n}条`).join("，")} option={{
    grid: { left: 106, right: 30, bottom: 26, top: 12 }, xAxis: { ...axis, type: "value", minInterval: 1, splitNumber: 3 },
    yAxis: { ...axis, type: "category", inverse: true, data: visibleSources.map(s => s[0]), axisLabel: { ...axis.axisLabel, interval: 0, width: 96, overflow: "truncate" }, splitLine: { show: false } },
    series: [{ type: "bar", barMaxWidth: 18, label: { show: true, position: "right", color: ink }, data: visibleSources.map(([, value], i) => ({ value, itemStyle: { color: colors[i % colors.length], borderRadius: 5 } })) }]
  }} />{!sources.length && <span className="chart-empty">已启动来源暂无有效信息</span>}</div></section>;
}

/** 搜索命中率：最近一小时的查询/有结果/命中率散点 */
export function HitRatePanel({ data, dark = false }: { data: Snapshot; dark?: boolean }) {
  const { ink, hitColors, axis } = chartTheme(dark);
  const history = data.search_hit_history || [];
  const queryTotal = data.search_hit_total || 0, hitTotal = data.search_hit_success || 0;
  return <section className="panel chart-panel"><h2>搜索命中率 <small>{queryTotal ? `${(hitTotal / queryTotal * 100).toFixed(1)}%` : "—"} · {hitTotal}/{queryTotal} 次</small></h2><div className="plot-wrap"><Plot label="最近一小时搜索命中率：每点汇总五分钟已结束搜索；红色查询次数，黄色有结果次数，绿色命中率。返回结果不代表通过AI审核的商机。" option={{
    color: hitColors, grid: { left: 30, right: 38, top: 32, bottom: 26 },
    legend: { top: 0, itemWidth: 8, itemHeight: 8, itemGap: 8, textStyle: { color: ink, fontSize: 11 } },
    tooltip: { trigger: "item", formatter: (p: { seriesName: string; value: number[] }) => `${clock(p.value[0] / 1000).slice(0, 5)} 起五分钟\n${p.seriesName}：${p.value[1]}${p.seriesName === "命中率" ? "%" : "次"}\n搜索 ${p.value[2]} 次 · 有结果 ${p.value[3]} 次\n异常 ${p.value[4]} 次（计入搜索次数）\n有结果不等于通过AI审核的商机` },
    xAxis: { ...axis, type: "time", min: (data.server_time - 3600) * 1000, max: data.server_time * 1000, splitNumber: 3, splitLine: { show: false }, axisLabel: { ...axis.axisLabel, formatter: (v: number) => clock(v / 1000).slice(0, 5) } },
    yAxis: [{ ...axis, type: "value", min: 0, minInterval: 1, splitNumber: 3 },
      { ...axis, type: "value", min: 0, max: 100, interval: 50, position: "right", splitLine: { show: false }, axisLabel: { ...axis.axisLabel, formatter: "{value}%" } }],
    series: ["搜索次数", "有结果次数", "命中率"].map((name, i) => ({ name, type: "scatter", yAxisIndex: i === 2 ? 1 : 0,
      symbolSize: (v: number[]) => Math.min(18, 6 + Math.sqrt(i === 2 ? v[2] : v[1]) * 1.6),
      itemStyle: { opacity: .8 }, emphasis: { focus: "series" },
      data: history.map(r => [r[0] * 1000, i === 2 ? Number((r[2] / r[1] * 100).toFixed(1)) : r[i + 1], r[1], r[2], r[3]]) }))
  }} />{!history.length && <span className="chart-empty">最近一小时暂无已结束搜索</span>}</div></section>;
}

/** 信息流向：已推送信息从采集来源流向认领去向的桑基图 */
export function FlowPanel({ data, dark = false }: { data: Snapshot; dark?: boolean }) {
  const { ink, colors } = chartTheme(dark);
  const flows = data.information_flows || [];
  const nodes = [...new Set(flows.flatMap(f => [f.source, f.target]))];
  const flowColor = (name: string) => name.includes("待认领") ? "#C8AD78"
    : name.includes("已认领") ? "#74B5A3"
    : name === "商机" ? colors[0] : name === "小红书" ? colors[1]
    : name === "监控" || name.includes("播报") ? colors[2] : colors[1];
  return <section className="panel chart-panel"><h2>信息流向 <small>来源 → 去向</small></h2><div className="plot-wrap"><Plot label="已推送信息从采集来源流向待认领、认领人或客户播报" option={{
    tooltip: { trigger: "item" }, series: [{ type: "sankey", left: 8, right: 90, top: 16, bottom: 12, nodeWidth: 9, nodeGap: 18, draggable: false,
      label: { color: ink, fontSize: 12 }, data: nodes.map(name => ({ name, itemStyle: { color: flowColor(name) } })), links: flows,
      lineStyle: { color: "source", curveness: .5, opacity: .22 }, emphasis: { focus: "adjacency" } }]
  }} />{!flows.length && <span className="chart-empty">等待信息推送</span>}</div></section>;
}
