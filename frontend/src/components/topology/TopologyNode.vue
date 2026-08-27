<template>
  <div
    class="topology-node"
    :class="[`type-${data?.deviceType || 'switch'}`, `layer-${data?.layer || 'access'}`, { selected }]"
  >
    <div class="node-icon" v-html="iconSvg"></div>
    <div class="node-info">
      <span class="node-label">{{ data?.label || '' }}</span>
      <span class="node-ip">{{ data?.ip || '—' }}</span>
      <span v-if="data?.deviceModel" class="node-model">{{ data.deviceModel }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { NodeProps } from '@vue-flow/core'
import type { TopologyNodeData } from '@/types/topology'

const props = defineProps<NodeProps>()

type NodeData = TopologyNodeData & { deviceType?: string; deviceModel?: string }

/** 节点数据（useTopology 转换后挂载在 data 上） */
const data = computed<Partial<NodeData>>(() => (props.data || {}) as Partial<NodeData>)
const selected = computed(() => props.selected ?? false)

/** 按设备类型输出内联 SVG 图标 */
const iconSvg = computed(() => {
  const type = data.value?.deviceType || 'switch'
  const svgs: Record<string, string> = {
    switch:
      '<svg viewBox="0 0 24 24" width="24" height="24"><rect x="3" y="8" width="18" height="8" rx="1" fill="currentColor"/><circle cx="7" cy="12" r="1.2" fill="#fff"/><circle cx="11" cy="12" r="1.2" fill="#fff"/><circle cx="15" cy="12" r="1.2" fill="#fff"/><circle cx="19" cy="12" r="1.2" fill="#fff"/></svg>',
    router:
      '<svg viewBox="0 0 24 24" width="24" height="24"><rect x="4" y="10" width="16" height="8" rx="2" fill="currentColor"/><circle cx="8" cy="6" r="1.6" fill="currentColor"/><circle cx="16" cy="6" r="1.6" fill="currentColor"/><line x1="8" y1="7.6" x2="8" y2="10" stroke="currentColor" stroke-width="1.2"/><line x1="16" y1="7.6" x2="16" y2="10" stroke="currentColor" stroke-width="1.2"/></svg>',
    firewall:
      '<svg viewBox="0 0 24 24" width="24" height="24"><rect x="3" y="5" width="18" height="14" rx="1" fill="currentColor"/><line x1="3" y1="10" x2="21" y2="10" stroke="#fff" stroke-width="1.2"/><line x1="3" y1="14" x2="21" y2="14" stroke="#fff" stroke-width="1.2"/><line x1="9" y1="5" x2="9" y2="10" stroke="#fff" stroke-width="1.2"/><line x1="15" y1="5" x2="15" y2="10" stroke="#fff" stroke-width="1.2"/><line x1="7" y1="10" x2="7" y2="14" stroke="#fff" stroke-width="1.2"/><line x1="13" y1="10" x2="13" y2="14" stroke="#fff" stroke-width="1.2"/><line x1="17" y1="10" x2="17" y2="14" stroke="#fff" stroke-width="1.2"/></svg>',
    server:
      '<svg viewBox="0 0 24 24" width="24" height="24"><rect x="5" y="4" width="14" height="5" rx="1" fill="currentColor"/><rect x="5" y="11" width="14" height="5" rx="1" fill="currentColor"/><rect x="5" y="18" width="14" height="3" rx="1" fill="currentColor"/><circle cx="8" cy="6.5" r="1" fill="#fff"/><circle cx="8" cy="13.5" r="1" fill="#fff"/></svg>',
    database:
      '<svg viewBox="0 0 24 24" width="24" height="24"><ellipse cx="12" cy="6" rx="8" ry="2.6" fill="currentColor"/><path d="M4 6 V18 a8 2.6 0 0 0 16 0 V6" fill="currentColor"/><ellipse cx="12" cy="6" rx="8" ry="2.6" fill="none" stroke="#fff" stroke-width="0.6"/><ellipse cx="12" cy="12" rx="8" ry="2.6" fill="none" stroke="#fff" stroke-width="0.6"/></svg>',
  }
  return svgs[type] || svgs.switch
})
</script>

<style scoped>
.topology-node {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 164px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1.5px solid #e2e8f0;
  background: #fff;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s, border-color 0.2s;
  font-family: inherit;
}
.topology-node:hover {
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.14);
  transform: translateY(-2px);
}
.topology-node.selected {
  border-color: var(--el-color-primary, #409eff);
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.2);
}
.node-icon {
  width: 38px;
  height: 38px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  box-shadow: inset 0 -2px 4px rgba(0, 0, 0, 0.12);
}
.node-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}
.node-label {
  font-size: 12.5px;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.node-ip {
  font-size: 11px;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.node-model {
  font-size: 10px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 按设备类型着色（图标底色） */
.type-switch .node-icon {
  background: #3b82f6;
}
.type-router .node-icon {
  background: #0ea5e9;
}
.type-firewall .node-icon {
  background: #ef4444;
}
.type-server .node-icon {
  background: #22c55e;
}
.type-database .node-icon {
  background: #a855f7;
}
/* 按层级加左侧色条 */
.layer-core {
  border-left: 4px solid #f59e0b;
}
.layer-aggregation {
  border-left: 4px solid #3b82f6;
}
.layer-access {
  border-left: 4px solid #22c55e;
}
</style>
