<template>
  <BaseEdge :id="id" :path="path" :style="edgeStyle" :marker-end="markerEnd" />
  <EdgeText
    v-if="showLabel && label"
    :x="labelX"
    :y="labelY"
    :label="labelText"
    :label-style="edgeLabelStyle"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { BaseEdge, EdgeText, getBezierPath, type EdgeProps } from '@vue-flow/core'

const props = defineProps<EdgeProps & { showLabel?: boolean }>()

const [path, labelX, labelY] = getBezierPath({
  sourceX: props.sourceX,
  sourceY: props.sourceY,
  targetX: props.targetX,
  targetY: props.targetY,
  sourcePosition: props.sourcePosition,
  targetPosition: props.targetPosition,
})

/** 跨层连线（core↔aggregation↔access 之间）用蓝色强调主干链路，同层连线用浅灰 */
const edgeStyle = computed(() => {
  const edgeData = (props.data || {}) as Record<string, string>
  const crossLayer =
    edgeData.sourceLayer && edgeData.targetLayer && edgeData.sourceLayer !== edgeData.targetLayer
  return {
    stroke: crossLayer ? '#60a5fa' : '#cbd5e1',
    strokeWidth: crossLayer ? 2.2 : 1.6,
    opacity: props.selected ? 1 : 0.9,
  }
})

const labelText = computed(() => {
  const edgeData = (props.data || {}) as Record<string, string>
  const label = props.label || ''
  return edgeData.bandwidth ? `${label} ${edgeData.bandwidth}`.trim() : label
})

/** 连线标签样式（EdgeText 的 label-style 为 CSSProperties 类型） */
const edgeLabelStyle = {
  fontSize: '11px',
  fill: '#475569',
  fontWeight: 500,
  background: 'rgba(255,255,255,0.85)',
  padding: '2px 4px',
  borderRadius: '4px',
}
</script>
