<script setup>
import { ref, onMounted } from 'vue'

const records = ref([])
const loading = ref(true)

function loadRecords() {
  // Load from localStorage if available, otherwise empty
  const saved = localStorage.getItem('asr-history')
  if (saved) {
    try { records.value = JSON.parse(saved) } catch (e) { records.value = [] }
  }
  loading.value = false
}

function clearAll() {
  records.value = []
  localStorage.removeItem('asr-history')
}

function clearOne(i) {
  records.value.splice(i, 1)
  localStorage.setItem('asr-history', JSON.stringify(records.value))
}

function exportRecords() {
  const blob = new Blob([JSON.stringify(records.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `asr-history-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(loadRecords)
</script>

<template>
  <div class="history-page">
    <div class="page-header">
      <h1 class="page-title">识别历史</h1>
      <div class="page-actions">
        <button class="btn-icon" @click="exportRecords" :disabled="!records.length" title="导出 JSON">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
        <button class="btn-icon danger" @click="clearAll" :disabled="!records.length" title="清除全部">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else-if="!records.length" class="empty-state">
      <div class="empty-orb">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
      </div>
      <h3>暂无记录</h3>
      <p>前往录音页面开始识别，记录将自动保存</p>
      <router-link to="/" class="btn-link">去录音</router-link>
    </div>

    <div v-else class="records-list">
      <div
        v-for="(record, index) in records.slice().reverse()"
        :key="index"
        class="record-card"
      >
        <div class="record-meta">
          <span class="record-time">{{ record.time }}</span>
          <span class="record-date">{{ record.date }}</span>
        </div>
        <div class="record-text">{{ record.text }}</div>
        <button class="record-delete" @click="clearOne(records.length - 1 - index)" title="删除">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-page {
  max-width: 800px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
}

.page-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}

.page-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-panel);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  position: relative;
  overflow: hidden;
}

.btn-icon::before {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 12px;
  background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary), var(--accent-primary));
  background-size: 200% 100%;
  opacity: 0;
  transition: opacity 0.4s ease;
  z-index: -1;
  animation: shimmer 3s linear infinite;
  filter: blur(6px);
}

.btn-icon:hover::before {
  opacity: 0.5;
}

.btn-icon:hover:not(:disabled) {
  transform: scale(1.1);
  color: var(--text-primary);
  border-color: var(--border-active);
}

.btn-icon:active:not(:disabled) {
  transform: scale(0.95);
}

.btn-icon.danger {
  color: var(--accent-danger);
}

.btn-icon.danger:hover:not(:disabled) {
  border-color: rgba(255, 107, 107, 0.4);
}

.btn-icon.danger::before {
  background: linear-gradient(90deg, var(--accent-danger), #FFB4B4, var(--accent-danger));
  background-size: 200% 100%;
}

.btn-icon:disabled {
  opacity: 0.3;
  cursor: not-allowed;
  transform: none !important;
}

.btn-icon:disabled::before {
  opacity: 0 !important;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-orb {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  margin-bottom: 20px;
  transition: all 0.4s ease;
}

.empty-state:hover .empty-orb {
  border-color: var(--border-active);
  box-shadow: 0 0 40px rgba(199, 125, 255, 0.1);
  color: var(--accent-primary);
}

.empty-state h3 {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.empty-state p {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 20px;
}

.btn-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 10px;
  background: var(--accent-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  box-shadow: 0 4px 16px rgba(199, 125, 255, 0.25);
}

.btn-link:hover {
  transform: scale(1.05);
  box-shadow: 0 6px 24px rgba(199, 125, 255, 0.4);
}

/* Record Cards */
.records-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.record-card {
  position: relative;
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 20px 24px;
  transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  overflow: hidden;
}

.record-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: linear-gradient(135deg, rgba(199, 125, 255, 0.03), rgba(0, 229, 255, 0.03));
  opacity: 0;
  transition: opacity 0.4s ease;
  pointer-events: none;
  z-index: 0;
}

.record-card:hover::before {
  opacity: 1;
}

.record-card:hover {
  border-color: var(--border-active);
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(199, 125, 255, 0.08);
}

.record-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  position: relative;
  z-index: 1;
}

.record-time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent-primary);
  background: rgba(199, 125, 255, 0.1);
  padding: 3px 10px;
  border-radius: 6px;
  font-weight: 500;
}

.record-date {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.record-text {
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-word;
  position: relative;
  z-index: 1;
  padding-right: 30px;
}

.record-delete {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  z-index: 2;
}

.record-delete:hover {
  background: var(--accent-danger-dim);
  color: var(--accent-danger);
  transform: scale(1.15);
}

.loading {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
  font-size: 14px;
}

@media (max-width: 640px) {
  .page-title { font-size: 22px; }
  .record-card { padding: 16px; border-radius: 12px; }
  .record-text { font-size: 14px; }
}
</style>
