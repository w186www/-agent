<template>
  <div class="panel panel-upload">
    <h3 class="panel-title">截图分析</h3>
    <div class="upload-area">
      <el-icon class="upload-icon"><Picture /></el-icon>
      <div class="upload-text">上传测评截图</div>
      <div class="upload-hint">点击或拖拽上传</div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 16px;
}

/* ── 截图上传 ── */
.panel-upload {
  width: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}
.upload-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 2px dashed var(--border);
  border-radius: 8px;
  padding: 24px 16px;
  cursor: pointer;
  transition: all 0.15s;
}
.upload-area:hover {
  border-color: var(--primary);
  background: var(--primary-light);
}
.upload-icon {
  font-size: 32px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.upload-text {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.upload-hint {
  font-size: 11px;
  color: var(--text-muted);
}
</style>
