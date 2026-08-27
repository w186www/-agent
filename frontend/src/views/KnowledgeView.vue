<script setup lang="ts">
import type { Category, DocItem as Doc } from '@/types/knowledge'
import CategoryCard from '@/components/knowledge/CategoryCard.vue'
import DocItem from '@/components/knowledge/DocItem.vue'

const categories: Category[] = [
  { name: '等保标准', count: 128 },
  { name: '测评指南', count: 56 },
  { name: '行业案例', count: 34 },
  { name: '政策法规', count: 22 },
]

const recentDocs: Doc[] = [
  { title: 'GB/T 22239-2019 信息安全技术 网络安全等级保护基本要求', date: '2026-07-15', size: '2.4 MB' },
  { title: 'GB/T 28448-2019 网络安全等级保护测评要求', date: '2026-07-10', size: '1.8 MB' },
  { title: '金融行业等保测评实施指南', date: '2026-06-28', size: '3.1 MB' },
  { title: '政务云等保三级测评案例集', date: '2026-06-20', size: '5.6 MB' },
]
</script>

<template>
  <div class="knowledge-view">
    <div class="knowledge-header">
      <h2 class="page-title">知识库</h2>
      <el-button type="primary">
        <el-icon><Upload /></el-icon>
        上传文档
      </el-button>
    </div>

    <div class="knowledge-categories">
      <CategoryCard
        v-for="cat in categories"
        :key="cat.name"
        :name="cat.name"
        :count="cat.count"
      />
    </div>

    <div class="knowledge-docs">
      <h3 class="section-title">最近文档</h3>
      <div class="doc-list">
        <DocItem
          v-for="doc in recentDocs"
          :key="doc.title"
          :doc="doc"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge-view {
  padding: 24px;
  height: 100%;
  overflow-y: auto;
}
.knowledge-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.knowledge-categories {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 16px;
}
.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
