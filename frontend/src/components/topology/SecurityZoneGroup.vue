<template>
  <svg class="zone-overlay">
    <g :transform="`translate(${viewport.x} ${viewport.y}) scale(${viewport.zoom})`">
      <!-- 网络层级背景带（最底层） -->
      <g v-for="band in layerBands" :key="band.layer">
        <rect
          :x="band.bounds.x"
          :y="band.bounds.y"
          :width="band.bounds.width"
          :height="band.bounds.height"
          :fill="bandColors[band.layer]?.fill || '#f1f5f9'"
          rx="14"
        />
        <text :x="band.bounds.x + 14" :y="band.bounds.y + 24" fill="#94a3b8" font-size="12" font-weight="600" letter-spacing="2">
          {{ band.label }}
        </text>
      </g>

      <!-- 安全域分组框 -->
      <g v-for="zone in zones" :key="zone.id">
        <rect
          :x="zone.bounds.x"
          :y="zone.bounds.y"
          :width="zone.bounds.width"
          :height="zone.bounds.height"
          :fill="zoneColors[zone.id]?.fill || '#f1f5f9'"
          :stroke="zoneColors[zone.id]?.stroke || '#64748b'"
          stroke-width="1.5"
          stroke-dasharray="6 4"
          rx="10"
        />
        <text :x="zone.bounds.x + 12" :y="zone.bounds.y + 20" :fill="zoneColors[zone.id]?.stroke || '#64748b'" font-size="13" font-weight="600">
          {{ zone.label }}
        </text>
        <text
          v-if="zone.risk_level"
          :x="zone.bounds.x + zone.bounds.width - 12"
          :y="zone.bounds.y + 20"
          :fill="riskColor(zone.risk_level)"
          font-size="11"
          font-weight="600"
          text-anchor="end"
        >
          风险：{{ zone.risk_level }}
        </text>
      </g>
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useVueFlow, type ViewportTransform } from '@vue-flow/core'
import type { LayerBand, SecurityZoneGroup } from './useTopology'

const props = defineProps<{ zones: SecurityZoneGroup[]; layerBands: LayerBand[] }>()

/** 视口变换（平移/缩放），SVG overlay 同步应用后与节点对齐。
 * store.viewport 在运行时是响应式普通对象，但类型声明为 Ref（版本类型缺陷），这里做类型收窄。 */
const store = useVueFlow()
const viewport = computed<ViewportTransform>(() => store.viewport as unknown as ViewportTransform)

/** 层级背景带配色：核心-淡琥珀 / 汇聚-淡蓝 / 接入-淡绿 */
const bandColors = computed<Record<string, { fill: string }>>(() => ({
  core: { fill: 'rgba(245, 158, 11, 0.06)' },
  aggregation: { fill: 'rgba(59, 130, 246, 0.06)' },
  access: { fill: 'rgba(34, 197, 94, 0.05)' },
}))

/** 不同安全域分配不同描边色，同域稳定呈现 */
const zoneColors = computed<Record<string, { fill: string; stroke: string }>>(() => {
  const palette = [
    { fill: 'rgba(59, 130, 246, 0.06)', stroke: '#3b82f6' },
    { fill: 'rgba(16, 185, 129, 0.06)', stroke: '#10b981' },
    { fill: 'rgba(168, 85, 247, 0.06)', stroke: '#a855f7' },
    { fill: 'rgba(245, 158, 11, 0.06)', stroke: '#f59e0b' },
    { fill: 'rgba(14, 165, 233, 0.06)', stroke: '#0ea5e9' },
  ]
  const map: Record<string, { fill: string; stroke: string }> = {}
  props.zones.forEach((zone, index) => {
    map[zone.id] = palette[index % palette.length]
  })
  return map
})

/** 风险等级颜色：高-红 / 中-橙 / 低-绿 */
function riskColor(level: string): string {
  const map: Record<string, string> = { 高: '#ef4444', 中: '#f59e0b', 低: '#22c55e' }
  return map[level] || '#f59e0b'
}
</script>

<style scoped>
.zone-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}
</style>
