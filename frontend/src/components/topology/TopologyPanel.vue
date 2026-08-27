<template>
  <div class="topology-panel">
    <!-- 标签切换：对话 | 网络拓扑图 -->
    <div class="tabs">
      <button :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'">对话</button>
      <button :class="{ active: activeTab === 'topology' }" @click="activeTab = 'topology'">网络拓扑图</button>
    </div>

    <!-- 拓扑图画布 -->
    <div v-show="activeTab === 'topology'" ref="flowEl" class="topology-canvas">
      <!-- 操作栏 -->
      <div class="topology-toolbar">
        <el-button size="small" @click="exportPng">导出 PNG</el-button>
        <el-button size="small" @click="resetLayout">重置布局</el-button>
        <el-checkbox v-model="showLabels" size="small">显示标签</el-checkbox>
        <el-checkbox v-model="showZones" size="small">安全域分组</el-checkbox>
      </div>

      <!-- Vue Flow 画布 -->
      <VueFlow
        :nodes="nodes"
        :edges="edges"
        :default-viewport="{ zoom: 0.8 }"
        :min-zoom="0.3"
        :max-zoom="2"
        fit-view-on-init
        class="flow-canvas"
        @node-click="handleNodeClick"
      >
        <Background pattern-color="#e2e8f0" :gap="22" />
        <Controls />
        <MiniMap />

        <template #node-topology-node="props">
          <TopologyNode v-bind="props" />
        </template>
        <template #edge-topology-edge="props">
          <TopologyEdge v-bind="props" :show-label="showLabels" />
        </template>
      </VueFlow>

      <!-- 层级背景带 + 安全域分组 overlay（跟随视口变换对齐节点） -->
      <SecurityZoneGroup v-if="showZones" :zones="zones" :layer-bands="layerBands" />

      <!-- 底部拓扑分析摘要 -->
      <div v-if="summary" class="topology-summary">
        <h4>拓扑分析</h4>
        <p>{{ summary }}</p>
      </div>
    </div>

    <!-- 节点详情抽屉 -->
    <TopologyDetailDrawer v-model="drawerVisible" :node="selectedNode" />
  </div>
</template>

<script setup lang="ts">
import { ref, toRef, watch } from 'vue'
import { VueFlow, useVueFlow, type Node, type NodeMouseEvent } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { toPng } from 'html-to-image'
import { ElMessage } from 'element-plus'
import type { TopologyData, TopologyNodeData } from '@/types/topology'
import TopologyNode from './TopologyNode.vue'
import TopologyEdge from './TopologyEdge.vue'
import SecurityZoneGroup from './SecurityZoneGroup.vue'
import TopologyDetailDrawer from './TopologyDetailDrawer.vue'
import { useTopology } from './useTopology'

const props = defineProps<{
  topologyData: TopologyData | null
}>()

const activeTab = ref<'chat' | 'topology'>('chat')
const showLabels = ref(true)
const showZones = ref(true)
const drawerVisible = ref(false)
const selectedNode = ref<TopologyNodeData | null>(null)
const flowEl = ref<HTMLElement | null>(null)

const { nodes, edges, zones, layerBands, summary } = useTopology(toRef(props, 'topologyData'))
const { setNodes } = useVueFlow()

// 收到新的拓扑数据时自动切换到「网络拓扑图」标签页
watch(
  () => props.topologyData,
  (data) => {
    if (data) activeTab.value = 'topology'
  },
)

function handleNodeClick(event: NodeMouseEvent) {
  selectedNode.value = (event.node.data || {}) as TopologyNodeData
  drawerVisible.value = true
}

/** 导出 PNG：对画布视口截图 */
async function exportPng() {
  const el = flowEl.value?.querySelector('.vue-flow__viewport')
  if (!el) {
    ElMessage.warning('画布尚未就绪')
    return
  }
  try {
    const dataUrl = await toPng(el as HTMLElement, { backgroundColor: '#fff', pixelRatio: 2 })
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = `topology-${Date.now()}.png`
    a.click()
    ElMessage.success('拓扑图已导出')
  } catch (err) {
    console.error('拓扑图导出失败:', err)
    ElMessage.error('导出失败，请重试')
  }
}

/** 重置布局：恢复初始分层布局（覆盖拖拽/缩放后的位置） */
function resetLayout() {
  const snapshot = JSON.parse(JSON.stringify(nodes.value)) as Node[]
  setNodes(snapshot)
  ElMessage.success('布局已重置')
}
</script>

<style scoped>
.topology-panel {
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  margin-bottom: 12px;
}
.tabs {
  display: flex;
  border-bottom: 1px solid var(--el-border-color, #dcdfe6);
}
.tabs button {
  padding: 8px 16px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--el-text-color-secondary, #909399);
}
.tabs button.active {
  color: var(--el-color-primary, #409eff);
  border-bottom: 2px solid var(--el-color-primary, #409eff);
  font-weight: 600;
}
.topology-canvas {
  height: 500px;
  position: relative;
}
.flow-canvas {
  width: 100%;
  height: 100%;
}
.topology-toolbar {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 10;
  display: flex;
  gap: 10px;
  align-items: center;
  background: rgba(255, 255, 255, 0.85);
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.topology-summary {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 10px 16px;
  border-top: 1px solid var(--el-border-color, #dcdfe6);
  background: rgba(250, 251, 252, 0.95);
  max-height: 100px;
  overflow-y: auto;
}
.topology-summary h4 {
  margin: 0 0 4px;
  font-size: 14px;
  color: #1f2937;
}
.topology-summary p {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary, #909399);
  line-height: 1.6;
}
</style>
