import { useEffect, useRef, useState } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart, HeatmapChart } from "echarts/charts";
import {
  CalendarComponent,
  VisualMapComponent,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import type { Snapshot } from "./types";

use([
  LineChart,
  HeatmapChart,
  BarChart,
  CalendarComponent,
  VisualMapComponent,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  CanvasRenderer,
]);
export type ChartSelection = { start: number; end: number; provider?: string; label: string };
function Plot({ option, label, onPick }: { option: EChartsCoreOption; label: string;
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
const names: Record<string, string> = { searxng: "开源搜索", tavily: "Tavily", demo: "演示来源" };
const palette = ["#70c3ce", "#e393b0", "#9bbb92", "#d8ba7c"];
const minuteLabel = (t: number) => new Date(t * 1000).toLocaleTimeString("zh-CN", {
  timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false,
});
export function Charts({ data, onSelect }: { data: Snapshot; onSelect: (range: ChartSelection) => void }) {
  const [table, setTable] = useState<"trend" | "calendar" | null>(null);
  const growth = data.discovery_history || [];
  const days = data.discovery_calendar || [];
  const history = data.collection_history || [];
  const sources = [...new Set(growth.flatMap(r => Object.keys(r.sources)))].sort();
  const pickMinute = (i: number, provider?: string) => {
    const r = growth[i];
    if (r) onSelect({ start: r.start, end: r.end, provider,
      label: `${minuteLabel(r.start)}–${minuteLabel(r.end)} · ${provider ? names[provider] || provider : "全部来源"}` });
  };
  const pickDay = (i: number) => {
    const d = days[i];
    if (d) onSelect({ start: d.start, end: d.end, label: `${d.date} · 全部来源` });
  };
  const axis = { axisLine: { show: false }, axisTick: { show: false },
    axisLabel: { color: "#a6afb9", fontSize: 11, margin: 12 },
    splitLine: { lineStyle: { color: "#30363e" } } };
  const y = { ...axis, type: "value", min: 0, minInterval: 1, splitNumber: 3 };
  return <>
    <div className="charts">
      <section className="panel chart-panel">
        <h2>新增信息 <small>近30分钟 / 条</small></h2>
        <Plot label="每分钟新增去重信息，按搜索服务堆叠。可通过下方时间明细按钮查看相同数据。"
          onPick={(i, name) => pickMinute(i, sources.find(s => (names[s] || s) === name))}
          option={{ xAxis: { ...axis, type: "category", boundaryGap: false,
            data: growth.map(r => minuteLabel(r.start)), splitLine: { show: false } }, yAxis: y,
            legend: { bottom: 0, textStyle: { color: "#a6afb9" }, icon: "roundRect", itemHeight: 4 },
            series: (sources.length ? sources : ["暂无新增"]).map((provider, i) => ({
              name: names[provider] || provider, type: "line", stack: "new", smooth: false,
              showSymbol: false, symbolSize: 5, lineStyle: { width: 0 },
              itemStyle: { color: palette[i % palette.length] },
              areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [{ offset: 0, color: palette[i % palette.length] + "a0" },
                  { offset: 1, color: palette[i % palette.length] + "12" }] } },
              data: growth.map(r => r.sources[provider] || 0),
              emphasis: { focus: "series" },
            })) }} />
        <button className="chart-link" aria-expanded={table === "trend"}
          onClick={() => setTable(table === "trend" ? null : "trend")}>时间明细</button>
      </section>
      <section className="panel chart-panel">
        <h2>归集日历 <small>近90天 / 北京时间</small></h2>
        <Plot label="最近90天每天新增去重信息。无入库记录不能据此判断系统是否停机。日期明细提供表格入口。"
          onPick={pickDay}
          option={{ tooltip: { trigger: "item", formatter: (p: { value: [string, number] }) =>
            `${p.value[0]}\n${p.value[1]} 条新增信息` },
            visualMap: { min: 0, max: Math.max(1, ...days.map(d => d.count)),
              orient: "horizontal", left: "center", bottom: 0, itemHeight: 90, itemWidth: 8,
              text: ["多", "少"], textStyle: { color: "#a6afb9" },
              inRange: { color: ["#30373d", "#347e88", "#70c3ce", "#e5c078"] } },
            calendar: { top: 28, left: 30, right: 8, bottom: 46,
              range: days.length ? [days[0].date, days[days.length - 1].date] : [],
              cellSize: ["auto", "auto"], splitLine: { lineStyle: { color: "#59616a", width: 1 } },
              itemStyle: { color: "#30373d", borderColor: "#1c2127", borderWidth: 2 },
              dayLabel: { firstDay: 1, nameMap: ["日", "一", "二", "三", "四", "五", "六"], color: "#a6afb9", fontSize: 10 },
              monthLabel: { nameMap: "ZH", color: "#a6afb9", fontSize: 11 }, yearLabel: { show: false } },
            series: [{ type: "heatmap", coordinateSystem: "calendar", data: days.map(d => [d.date, d.count]) }] }} />
        <button className="chart-link" aria-expanded={table === "calendar"}
          onClick={() => setTable(table === "calendar" ? null : "calendar")}>日期明细</button>
      </section>
      <section className="panel chart-panel">
        <h2>任务积压 <small>排队与重试 / 项</small></h2>
        <Plot label="近30分钟每分钟末排队与重试任务数"
          option={{ xAxis: { ...axis, type: "category", boundaryGap: false,
            data: history.map(r => minuteLabel(r[0])), splitLine: { show: false } }, yAxis: y,
            series: [{ name: "待处理", type: "line", showSymbol: false,
              data: history.map(r => r[3]), lineStyle: { color: "#d8ba7c", width: 2 },
              itemStyle: { color: "#d8ba7c" } }] }} />
      </section>
    </div>
    {table && <section className="panel chart-data">
      <div className="table-scroll"><table>
        <caption>{table === "trend" ? "每分钟新增信息 · 北京时间" : "每日新增信息 · 北京时间"}</caption>
        <thead><tr><th scope="col">{table === "trend" ? "时间段" : "日期"}</th><th scope="col">新增信息 / 条</th><th scope="col">查看</th>{table === "trend" && <th scope="col">搜索来源</th>}</tr></thead>
        <tbody>{table === "trend" ? [...growth].reverse().map((r, i) => <tr key={r.start}>
          <td>{minuteLabel(r.start)}–{minuteLabel(r.end)}</td><td>{Object.values(r.sources).reduce((a, b) => a + b, 0)}</td>
          <td><button onClick={() => pickMinute(growth.length - 1 - i)} aria-label={`查看${minuteLabel(r.start)}新增信息`}>查看信息</button></td>
          <td>{sources.map(s => <button key={s} className="source-filter" onClick={() => pickMinute(growth.length - 1 - i, s)}>{names[s] || s} · {r.sources[s] || 0}</button>)}</td>
        </tr>) : [...days].reverse().map((d, i) => <tr key={d.date}>
          <td>{d.date}</td><td>{d.count}</td><td><button onClick={() => pickDay(days.length - 1 - i)} aria-label={`查看${d.date}新增信息`}>查看信息</button></td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </>;
}
