<script setup lang="ts">
import type { Zone } from '@/types/topology'

defineProps<{
  zones: Zone[]
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

function select(id: string) {
  emit('update:modelValue', id)
}
</script>

<template>
  <div class="topo-zones">
    <button
      v-for="z in zones"
      :key="z.id"
      class="zone-btn"
      :class="{ active: modelValue === z.id }"
      @click="select(z.id)"
    >
      {{ z.label }}
      <span class="zone-count">{{ z.devices }}</span>
    </button>
  </div>
</template>

<style scoped>
.topo-zones {
  display: flex;
  gap: 8px;
}
.zone-btn {
  padding: 6px 16px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--surface);
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}
.zone-btn.active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
.zone-count {
  margin-left: 6px;
  font-size: 11px;
  opacity: 0.8;
}
</style>
