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
import { clock } from "./types";
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
        textStyle: {
          color: "#a6afb9",
          fontFamily: '"PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
          fontSize: 12,
        },
        tooltip: {
          trigger: "axis",
          backgroundColor: "#24292f",
          borderColor: "#353b43",
          textStyle: { color: "#e5e8ec" },
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
  return <div className="plot" ref={ref} role="img" aria-label={label} />;
}
export function Charts({ data }: { data: Snapshot }) {
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
    smooth: 0.22,
    smoothMonotone: "x",
    showSymbol: false,
    symbol: "circle",
    symbolSize: 5,
    lineStyle: { color, width: 2 },
    itemStyle: { color },
    emphasis: { focus: "series" },
  });
  const sources = Object.entries(data.source_counts || {}).sort(
    (a, b) => b[1] - a[1],
  );
  const names: Record<string, string> = {
    demo: "演示来源",
    tavily: "全网搜索",
  };
  const colors = ["#70c3ce", "#9bbb92", "#e393b0"];
  return (
    <div className="charts">
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
                      borderRadius: [0, 5, 5, 0],
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
        <h2>
          任务积压 <small>排队与重试 / 项</small>
        </h2>
        <Plot
          label="近30分钟每分钟末排队和等待重试的任务数，不含待配置任务"
          option={{
            xAxis: x,
            yAxis: y,
            series: [line("待处理", 3, "#d8ba7c")],
          }}
        />
      </section>
    </div>
  );
}
