import { useEffect, useRef } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import type { Snapshot } from "./types";
import { clock, status } from "./types";
use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  CanvasRenderer,
]);
function Plot({ option, label }: { option: EChartsCoreOption; label: string }) {
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
        textStyle: { color: "#a6afb9", fontFamily: "system-ui" },
        tooltip: { trigger: "axis" },
        grid: { top: 24, right: 16, bottom: 40, left: 40 },
      },
      true,
    );
  }, [option]);
  return <div className="plot" ref={ref} role="img" aria-label={label} />;
}
export function Charts({ data }: { data: Snapshot }) {
  const axis = {
    axisLine: { lineStyle: { color: "#46505a" } },
    axisLabel: { color: "#a6afb9" },
    splitLine: { lineStyle: { color: "#30363e" } },
  };
  const x = {
    ...axis,
    type: "category",
    data: data.trend.map((r) => clock(r[0]).slice(0, 5)),
    boundaryGap: false,
  };
  return (
    <div className="charts">
      <section className="panel">
        <h2>
          信息归集趋势 <small>近 30 分钟 · 条 / 分钟</small>
        </h2>
        <Plot
          label="每分钟新归集的信息条数"
          option={{
            xAxis: x,
            yAxis: { ...axis, type: "value", min: 0, minInterval: 1 },
            series: [
              {
                type: "line",
                name: "新增信息",
                data: data.trend.map((r) => r[1]),
                showSymbol: false,
                lineStyle: { color: "#70c3ce" },
                itemStyle: { color: "#70c3ce" },
              },
            ],
          }}
        />
      </section>
      <section className="panel">
        <h2>
          任务状态 <small>项</small>
        </h2>
        <Plot
          label="任务各状态的数量"
          option={{
            xAxis: { ...axis, type: "value", minInterval: 1 },
            yAxis: {
              ...axis,
              type: "category",
              data: Object.keys(status).map((k) => status[k]),
            },
            series: [
              {
                type: "bar",
                data: Object.keys(status).map((k) => data.task_counts[k] || 0),
                itemStyle: { color: "#92b7ad" },
                barMaxWidth: 14,
              },
            ],
          }}
        />
      </section>
      <section className="panel">
        <h2>
          任务完成与失败 <small>项 / 分钟</small>
        </h2>
        <Plot
          label="每分钟任务完成和失败数"
          option={{
            xAxis: x,
            yAxis: { ...axis, type: "value", min: 0, minInterval: 1 },
            legend: { textStyle: { color: "#a6afb9" }, bottom: 0 },
            series: [
              {
                type: "line",
                name: "完成",
                data: data.trend.map((r) => r[2]),
                showSymbol: false,
                itemStyle: { color: "#d8ba7c" },
              },
              {
                type: "line",
                name: "失败",
                data: data.trend.map((r) => r[3]),
                showSymbol: false,
                itemStyle: { color: "#e393b0" },
              },
            ],
          }}
        />
      </section>
    </div>
  );
}
