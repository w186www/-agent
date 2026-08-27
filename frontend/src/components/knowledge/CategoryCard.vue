<script setup lang="ts">
defineProps<{
  name: string
  count: number
}>()
</script>

<template>
  <div class="category-card">
    <div class="cat-name">{{ name }}</div>
    <div class="cat-count">{{ count }} 篇</div>
  </div>
</template>

<style scoped>
.category-card {
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.15s;
}
.category-card:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow);
}
.cat-name {
  font-size: 15px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 6px;
}
.cat-count {
  font-size: 13px;
  color: var(--text-muted);
}
</style>
