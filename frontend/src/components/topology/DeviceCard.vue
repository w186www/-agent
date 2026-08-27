<script setup lang="ts">
import type { Device } from '@/types/topology'

defineProps<{
  device: Device
}>()
</script>

<template>
  <div class="device-card">
    <div class="device-status" :class="device.status"></div>
    <div class="device-name">{{ device.name }}</div>
    <div class="device-type">{{ device.type }}</div>
  </div>
</template>

<style scoped>
.device-card {
  padding: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.device-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.device-status.online {
  background: var(--success);
}
.device-status.warning {
  background: var(--warning);
}
.device-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}
.device-type {
  font-size: 11px;
  color: var(--text-muted);
  margin-left: auto;
}
</style>
