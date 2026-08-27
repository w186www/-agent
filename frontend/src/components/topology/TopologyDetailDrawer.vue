<template>
  <el-drawer v-model="visible" title="设备详情" size="340px">
    <div v-if="node" class="detail-content">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="设备名称">{{ node.label || '—' }}</el-descriptions-item>
        <el-descriptions-item label="IP 地址">{{ node.ip || '—' }}</el-descriptions-item>
        <el-descriptions-item label="设备类型">{{ deviceTypeLabel }}</el-descriptions-item>
        <el-descriptions-item label="网络层级">{{ layerLabel }}</el-descriptions-item>
        <el-descriptions-item label="所属安全域">{{ node.zone || '未分组' }}</el-descriptions-item>
        <el-descriptions-item v-if="node.mac" label="MAC 地址">{{ node.mac }}</el-descriptions-item>
        <el-descriptions-item v-if="node.device_model" label="设备型号">{{ node.device_model }}</el-descriptions-item>
        <el-descriptions-item v-if="node.description" label="设备描述">{{ node.description }}</el-descriptions-item>
      </el-descriptions>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TopologyNodeData } from '@/types/topology'

const props = defineProps<{
  modelValue: boolean
  node: TopologyNodeData | null
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const TYPE_LABELS: Record<string, string> = {
  switch: '交换机',
  router: '路由器',
  firewall: '防火墙',
  server: '服务器',
  database: '数据库',
}
const LAYER_LABELS: Record<string, string> = {
  core: '核心层',
  aggregation: '汇聚层',
  access: '接入层',
}

const deviceTypeLabel = computed(() => TYPE_LABELS[props.node?.type || ''] || props.node?.type || '—')
const layerLabel = computed(() => LAYER_LABELS[props.node?.layer || ''] || props.node?.layer || '—')
</script>
