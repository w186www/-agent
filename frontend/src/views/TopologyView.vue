<script setup lang="ts">
import { ref } from 'vue'
import type { Zone, Device } from '@/types/topology'
import ZoneTabs from '@/components/topology/ZoneTabs.vue'
import DeviceCard from '@/components/topology/DeviceCard.vue'

const selectedZone = ref('dmz')

const zones: Zone[] = [
  { id: 'dmz', label: 'DMZ 区', devices: 6 },
  { id: 'internal', label: '内网区', devices: 12 },
  { id: 'management', label: '管理区', devices: 4 },
]

const devices: Device[] = [
  { name: '核心交换机', type: 'switch', zone: 'internal', status: 'online' },
  { name: '防火墙-01', type: 'firewall', zone: 'dmz', status: 'online' },
  { name: '应用服务器', type: 'server', zone: 'dmz', status: 'online' },
  { name: '数据库服务器', type: 'server', zone: 'internal', status: 'warning' },
  { name: '堡垒机', type: 'server', zone: 'management', status: 'online' },
  { name: '日志审计', type: 'server', zone: 'management', status: 'online' },
]

const filteredDevices = devices.filter((d) => d.zone === selectedZone.value)
</script>

<template>
  <div class="topology-view">
    <div class="topo-header">
      <h2 class="page-title">网络拓扑图</h2>
      <ZoneTabs v-model="selectedZone" :zones="zones" />
    </div>

    <div class="topo-canvas">
      <div class="topo-placeholder">
        <el-icon class="topo-icon"><Share /></el-icon>
        <div class="topo-text">拓扑图可视化区域</div>
        <div class="topo-hint">展示 {{ zones.find((z) => z.id === selectedZone)?.label }} 设备连接关系</div>
      </div>
    </div>

    <div class="topo-devices">
      <h3 class="section-title">设备列表</h3>
      <div class="device-grid">
        <DeviceCard
          v-for="dev in filteredDevices"
          :key="dev.name"
          :device="dev"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.topology-view {
  padding: 24px;
  height: 100%;
  overflow-y: auto;
}
.topo-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.topo-canvas {
  height: 320px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.topo-placeholder {
  text-align: center;
}
.topo-icon {
  font-size: 48px;
  color: var(--text-muted);
  margin-bottom: 12px;
}
.topo-text {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.topo-hint {
  font-size: 13px;
  color: var(--text-muted);
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 14px;
}
.device-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
</style>
