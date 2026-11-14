import { useEffect, useRef, useState } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart, HeatmapChart, ScatterChart } from "echarts/charts";
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
  ScatterChart,
  BarChart,
  CalendarComponent,
  VisualMapComponent,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
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
const minuteLabel = (t: number) => new Date(t * 1000).toLocaleTimeString("zh-CN", {
  timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false,
});
export function Charts({ data, onSelect }: { data: Snapshot; onSelect: (range: ChartSelection) => void }) {
  const [table, setTable] = useState<"trend" | "calendar" | null>(null);
  const growth = data.discovery_history || [];
  const days = data.discovery_calendar || [];
  const history = data.collection_history || [];

  const pickMinute = (i: number, provider?: string) => {
    const r = growth[i];
    if (r) onSelect({ start: r.start, end: r.end, provider,
      label: `${minuteLabel(r.start)}–${minuteLabel(r.end)} · 归集信息` });
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
        <h2>归集与发送 <small>累计 / 条</small></h2>
        <Plot label="累计归集信息与发送进度；发送服务尚未接入，没有发送数值。"
          onPick={(i) => pickMinute(i)}
          option={{ color: ['#80FFA5', '#00DDFF'], xAxis: { ...axis, type: "category", boundaryGap: false,
            data: history.map(r => minuteLabel(r[0])), splitLine: { show: false } }, yAxis: y,
            legend: { bottom: 0, textStyle: { color: "#ddd" } },
            series: [{ name: "已归集", type: "line", smooth: true, showSymbol: false,
              lineStyle: { width: 0 }, areaStyle: { opacity: 0.8,
                color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [
                  { offset: 0, color: "rgb(128, 255, 165)" }, { offset: 1, color: "rgb(1, 191, 236)" }] } },
              data: history.map(r => r[2]) },
              { name: "已发送（未接入）", type: "line", smooth: true,
                data: history.map(() => null), itemStyle: { color: "#00DDFF" } }] }} />
        <button className="chart-link" aria-expanded={table === "trend"}
          onClick={() => setTable(table === "trend" ? null : "trend")}>时间明细</button>
      </section>
      <section className="panel chart-panel">
        <h2>归集日历 <small>近90天 / 北京时间</small></h2>
        <div className="calendar-total"><strong>{days.at(-1)?.count || 0}</strong><span>今日归集 · 90天共 {days.reduce((n, d) => n + d.count, 0)} 条</span></div>
        <Plot label="最近90天每天新增去重信息。无入库记录不能据此判断系统是否停机。日期明细提供表格入口。"
          onPick={pickDay}
          option={{ tooltip: { trigger: "item", formatter: (p: { value: [string, number] }) =>
            `${p.value[0]}\n${p.value[1]} 条新增信息` },
            visualMap: { show: false, min: 0, max: Math.max(1, ...days.map(d => d.count)) },
            calendar: { top: 24, left: 30, right: 8, bottom: 24,
              range: days.length ? [days[0].date, days[days.length - 1].date] : [],
              cellSize: ["auto", "auto"],
              itemStyle: { borderWidth: 1 },
              dayLabel: { firstDay: 1, nameMap: ["日", "一", "二", "三", "四", "五", "六"], color: "#a6afb9", fontSize: 10 },
              monthLabel: { nameMap: "ZH", color: "#a6afb9", fontSize: 11 }, yearLabel: { show: false } },
            series: [{ type: "heatmap", coordinateSystem: "calendar", data: days.map(d => [d.date, d.count]) }] }} />
        <button className="chart-link" aria-expanded={table === "calendar"}
          onClick={() => setTable(table === "calendar" ? null : "calendar")}>日期明细</button>
      </section>
      <section className="panel chart-panel">
        <h2>任务分布 <small>近30分钟 · 最近300项</small></h2>
        <Plot label="任务散点：横轴创建时间，纵轴流转秒数，气泡大小表示尝试次数，颜色表示任务状态。"
          option={{ color: ['#80F1BE', '#fec42c', '#dd4444'],
            grid: { top: 36, right: 70, bottom: 45, left: 42 },
            legend: { top: 0, textStyle: { color: "#ddd" } },
            xAxis: { type: "time", splitNumber: 5, axisLabel: { hideOverlap: true, formatter: (v: number) => minuteLabel(v / 1000), color: "#bbb" }, splitLine: { show: false } },
            yAxis: { ...y, name: "流转 / 秒", splitLine: { show: false } },
            tooltip: { trigger: "item", formatter: (p: { seriesName: string; value: number[] }) =>
              `${p.seriesName} · ${minuteLabel(p.value[0] / 1000)}\n${p.value[1]} 秒 · ${p.value[2]} 次尝试` },
            visualMap: { min: 1, max: 5, dimension: 2, right: 0, top: 52, itemWidth: 10, itemHeight: 80,
              text: ["尝试次数"], textStyle: { color: "#bbb" }, inRange: { symbolSize: [8, 38] }, calculable: true },
            series: [
              { name: "完成", states: ["succeeded"] },
              { name: "执行 / 等待", states: ["running", "queued", "retry_wait"] },
              { name: "失败 / 待配置", states: ["failed", "action_required"] },
            ].map(group => ({ name: group.name, type: "scatter",
              itemStyle: { opacity: 0.8, shadowBlur: 10, shadowOffsetX: 0, shadowOffsetY: 0, shadowColor: 'rgba(0,0,0,0.3)' },
              data: (data.task_scatter || []).filter(t => group.states.includes(t.status)).map(t => [t.time * 1000, Math.round(t.duration), Math.max(1, t.attempts)]) })) }} />
      <p className="chart-caption">横轴创建时间 · 纵轴流转秒数 · 圆点大小为尝试次数</p>
      </section>
    </div>
    {table && <section className="panel chart-data">
      <div className="table-scroll"><table>
        <caption>{table === "trend" ? "每分钟新增信息 · 北京时间" : "每日新增信息 · 北京时间"}</caption>
        <thead><tr><th scope="col">{table === "trend" ? "时间段" : "日期"}</th><th scope="col">新增信息 / 条</th><th scope="col">查看</th></tr></thead>
        <tbody>{table === "trend" ? [...growth].reverse().map((r, i) => <tr key={r.start}>
          <td>{minuteLabel(r.start)}–{minuteLabel(r.end)}</td><td>{Object.values(r.sources).reduce((a, b) => a + b, 0)}</td>
          <td><button onClick={() => pickMinute(growth.length - 1 - i)} aria-label={`查看${minuteLabel(r.start)}新增信息`}>查看信息</button></td>

        </tr>) : [...days].reverse().map((d, i) => <tr key={d.date}>
          <td>{d.date}</td><td>{d.count}</td><td><button onClick={() => pickDay(days.length - 1 - i)} aria-label={`查看${d.date}新增信息`}>查看信息</button></td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </>;
}
