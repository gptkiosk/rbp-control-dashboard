<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import uPlot from 'uplot'
import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/icons/icons'
import { useThemeStore } from '@/stores/theme'
import 'uplot/dist/uPlot.min.css'

export interface ChartLine {
  field: string
  label: string
}

const props = withDefaults(
  defineProps<{
    title: string
    icon?: IconName
    /** `ts` (epoch seconds) plus one array per field; null = gap. */
    series: ({ ts: number[] } & Record<string, (number | null)[]>) | null
    lines: ChartLine[]
    format: (v: number | null | undefined) => string
    /** Pin the y axis to start at zero. */
    zeroBased?: boolean
  }>(),
  { zeroBased: false },
)

const host = ref<HTMLElement | null>(null)
const theme = useThemeStore()
let plot: uPlot | null = null
let plotKey = ''
let observer: ResizeObserver | null = null

const hasData = computed(() => {
  const s = props.series
  if (!s || !s.ts || s.ts.length === 0) return false
  return props.lines.some((l) => (s[l.field] ?? []).some((v) => v !== null && v !== undefined))
})

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function buildData(): uPlot.AlignedData {
  const s = props.series!
  return [s.ts, ...props.lines.map((l) => s[l.field] ?? s.ts.map(() => null))] as uPlot.AlignedData
}

function destroy(): void {
  plot?.destroy()
  plot = null
  plotKey = ''
}

function create(): void {
  const el = host.value
  if (!el) return
  const muted = token('--text-muted')
  const grid = token('--panel-border')
  const fmt = props.format
  const axisBase = {
    stroke: muted,
    grid: { stroke: grid, width: 1 },
    ticks: { stroke: grid, width: 1 },
  }
  const opts: uPlot.Options = {
    width: el.clientWidth || 300,
    height: Number.parseInt(token('--chart-height'), 10) || 220,
    legend: { live: true },
    cursor: { drag: { x: false, y: false } },
    scales: {
      x: { time: true },
      y: {
        range: props.zeroBased
          ? (_u, _min, max) => [0, max <= 0 ? 1 : max * 1.1]
          : undefined,
      },
    },
    axes: [
      { ...axisBase },
      { ...axisBase, size: 72, values: (_u, splits) => splits.map((v) => fmt(v)) },
    ],
    series: [
      {},
      ...props.lines.map((l, i) => ({
        label: l.label,
        stroke: token(`--series-${(i % 6) + 1}`),
        width: 2,
        points: { show: false },
        value: (_u: uPlot, v: number | null) => fmt(v),
      })),
    ],
  }
  plot = new uPlot(opts, buildData(), el)
  plotKey = props.lines.map((l) => l.field).join(',')
}

async function render(): Promise<void> {
  if (!hasData.value) {
    destroy()
    return
  }
  await nextTick()
  if (!host.value) return
  const key = props.lines.map((l) => l.field).join(',')
  if (plot && key === plotKey) plot.setData(buildData())
  else {
    destroy()
    create()
  }
}

onMounted(() => {
  void render()
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    observer = new ResizeObserver(() => {
      if (plot && host.value) plot.setSize({ width: host.value.clientWidth, height: plot.height })
    })
    observer.observe(host.value)
  }
})

watch(() => [props.series, props.lines], () => void render(), { deep: false })
// Canvas strokes are sampled from tokens when created; CSS alone cannot recolour them.
watch(() => theme.mode, () => { destroy(); void render() })

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  destroy()
})
</script>

<template>
  <section class="card chart" :aria-label="title">
    <h2 class="section-title" :class="{ 'has-icon': icon }">
      <AppIcon v-if="icon" :name="icon" />
      {{ title }}
    </h2>
    <p v-if="!hasData" class="empty muted">No data yet</p>
    <div v-show="hasData" ref="host" class="host" role="img" :aria-label="`${title} chart`"></div>
  </section>
</template>

<style scoped>
.chart {
  gap: var(--gap-sm);
}

.empty {
  margin: 0;
  min-height: var(--chart-height);
  display: flex;
  align-items: center;
  justify-content: center;
}

.host {
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.host :deep(.uplot) {
  max-width: 100%;
}

.host :deep(.u-legend) {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}
</style>
