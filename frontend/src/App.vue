<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<template>
  <div class="app">
    <!-- Flowing Background -->
    <div class="bg-flow">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
      <div class="orb orb-4"></div>
      <div class="orb orb-5"></div>
    </div>

    <!-- Navigation -->
    <nav class="nav">
      <div class="nav-inner">
        <div class="nav-brand">
          <svg class="nav-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/>
          </svg>
          <span class="nav-title">实时语音转写</span>
        </div>
        <div class="nav-links">
          <router-link to="/" class="nav-link" :class="{ active: route.path === '/' }">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
            录音
          </router-link>
          <router-link to="/history" class="nav-link" :class="{ active: route.path === '/history' }">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            历史记录
          </router-link>
        </div>
      </div>
    </nav>

    <!-- Page Content -->
    <main class="page">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app {
  position: relative;
  min-height: 100vh;
  overflow-x: hidden;
  background: var(--bg-base);
}

/* ===== Flowing Background ===== */
.bg-flow {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.5;
  will-change: transform;
}

.orb-1 {
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.35) 0%, transparent 70%);
  top: -10%; left: -10%;
  animation: float-1 25s ease-in-out infinite;
}

.orb-2 {
  width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(124, 58, 237, 0.3) 0%, transparent 70%);
  bottom: -5%; right: -10%;
  animation: float-2 30s ease-in-out infinite;
}

.orb-3 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, rgba(167, 139, 250, 0.25) 0%, transparent 70%);
  top: 40%; left: 50%;
  animation: float-3 20s ease-in-out infinite;
}

.orb-4 {
  width: 350px; height: 350px;
  background: radial-gradient(circle, rgba(196, 181, 253, 0.2) 0%, transparent 70%);
  top: 60%; left: 10%;
  animation: float-1 22s ease-in-out infinite reverse;
}

.orb-5 {
  width: 450px; height: 450px;
  background: radial-gradient(circle, rgba(109, 40, 217, 0.3) 0%, transparent 70%);
  top: 10%; right: 20%;
  animation: float-2 28s ease-in-out infinite reverse;
}

/* ===== Navigation ===== */
.nav {
  position: relative;
  z-index: 10;
  border-bottom: 1px solid var(--border-subtle);
  background: rgba(13, 11, 20, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.nav-inner {
  max-width: 900px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-icon {
  color: var(--accent-primary);
}

.nav-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}

.nav-links {
  display: flex;
  gap: 6px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.3s ease;
  border: 1px solid transparent;
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-surface);
  border-color: var(--border-subtle);
}

.nav-link.active {
  color: var(--accent-primary);
  background: rgba(199, 125, 255, 0.08);
  border-color: var(--border-active);
}

/* ===== Page ===== */
.page {
  position: relative;
  z-index: 1;
  flex: 1;
  padding: 32px 20px;
}

@media (max-width: 640px) {
  .nav-inner { padding: 12px 16px; }
  .nav-title { font-size: 15px; }
  .nav-link { padding: 6px 10px; font-size: 12px; }
  .nav-link svg { width: 14px; height: 14px; }
  .page { padding: 20px 16px; }
}
</style>
