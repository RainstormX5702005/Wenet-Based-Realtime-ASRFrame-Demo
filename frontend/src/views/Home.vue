<script setup>
import { ref, computed, onUnmounted } from 'vue'
import WaveformCanvas from '../components/WaveformCanvas.vue'

const SAMPLE_RATE = 16000
const CHUNK_SIZE = 512

const status = ref('等待开始')
const isRecording = ref(false)
const displayedText = ref('')
const typingTimer = ref(null)
let audioCtx = null, processor = null, mediaStream = null
let analyser = null, sourceNode = null, ws = null

const statusColor = computed(() => {
  if (isRecording.value) return 'var(--accent-primary)'
  if (status.value.includes('错误') || status.value.includes('断开')) return 'var(--accent-danger)'
  return 'var(--text-secondary)'
})

function typeText(full) {
  if (typingTimer.value) clearInterval(typingTimer.value)
  displayedText.value = ''
  let i = 0
  typingTimer.value = setInterval(() => {
    if (i >= full.length) { clearInterval(typingTimer.value); typingTimer.value = null; return }
    displayedText.value += full[i++]
  }, 50)
}

async function start() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE })
    sourceNode = audioCtx.createMediaStreamSource(mediaStream)
    processor = audioCtx.createScriptProcessor(CHUNK_SIZE, 1, 1)
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 2048
    sourceNode.connect(analyser)
    sourceNode.connect(processor)
    processor.connect(audioCtx.destination)

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${proto}//${location.host}/ws`)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => { status.value = '已连接，正在录音...'; isRecording.value = true }
    ws.onmessage = (e) => {
      const text = e.data
      typeText(text)
      // Save to history
      const now = new Date()
      const record = {
        time: now.toLocaleTimeString('zh-CN', { hour12: false }),
        date: now.toLocaleDateString('zh-CN'),
        text: text,
        timestamp: now.getTime()
      }
      const saved = localStorage.getItem('asr-history')
      const history = saved ? JSON.parse(saved) : []
      history.push(record)
      localStorage.setItem('asr-history', JSON.stringify(history))
    }
    ws.onerror = () => { status.value = 'WebSocket 连接错误'; isRecording.value = false }
    ws.onclose = () => { status.value = '连接已断开'; isRecording.value = false }

    processor.onaudioprocess = (ev) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(ev.inputBuffer.getChannelData(0).buffer)
    }
    status.value = '正在启动...'
  } catch (err) {
    status.value = '错误: ' + err.message
  }
}

function stop() {
  if (processor) { processor.disconnect(); processor = null }
  if (sourceNode) { sourceNode.disconnect(); sourceNode = null }
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null }
  if (audioCtx) { audioCtx.close(); audioCtx = null }
  if (ws) { ws.close(); ws = null }
  if (typingTimer.value) { clearInterval(typingTimer.value); typingTimer.value = null }
  isRecording.value = false
  status.value = '已停止'
  displayedText.value = ''
}

onUnmounted(stop)
</script>

<template>
  <div class="home">
    <!-- Status -->
    <div class="status-line" :style="{ color: statusColor }">
      <span class="status-dot" :class="{ pulse: isRecording }">●</span>
      <span>{{ status }}</span>
    </div>

    <!-- Center Panel -->
    <div class="center-stage">
      <div class="transcript-box" :class="{ active: isRecording }">
        <div class="label">{{ isRecording ? '实时识别中' : '等待录音...' }}</div>
        <div class="text">
          <span>{{ displayedText }}</span>
          <span v-if="typingTimer" class="cursor">|</span>
        </div>
      </div>

      <!-- Waveform directly below -->
      <WaveformCanvas :analyser="analyser" :recording="isRecording" />
    </div>

    <!-- Controls -->
    <div class="controls">
      <button class="btn glow-btn primary" :disabled="isRecording" @click="start">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4" fill="currentColor"/></svg>
        开始录音
      </button>
      <button class="btn glow-btn danger" :disabled="!isRecording" @click="stop">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>
        停止录音
      </button>
    </div>
  </div>
</template>

<style scoped>
.home {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: calc(100vh - 140px);
  justify-content: center;
  gap: 24px;
}

/* Status */
.status-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  transition: color 0.3s;
}

.status-dot {
  font-size: 8px;
  color: var(--text-muted);
}

.status-dot.pulse {
  color: var(--accent-primary);
  animation: pulse-glow 2s infinite;
}

/* Center Stage */
.center-stage {
  width: 100%;
  max-width: 700px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

/* Transcript Box */
.transcript-box {
  width: 100%;
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  padding: 36px 40px;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  transition: all 0.4s ease;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.transcript-box.active {
  border-color: var(--border-active);
  box-shadow: 0 0 60px rgba(199, 125, 255, 0.08), 0 0 120px rgba(199, 125, 255, 0.03);
}

.label {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-muted);
  margin-bottom: 14px;
}

.text {
  font-size: 22px;
  font-weight: 500;
  line-height: 1.6;
  word-break: break-word;
  color: var(--text-primary);
  min-height: 60px;
}

.cursor {
  color: var(--accent-primary);
  animation: typing-cursor 1s infinite;
  margin-left: 2px;
}

/* Controls */
.controls {
  display: flex;
  gap: 14px;
  padding-top: 8px;
}

/* Glow Button */
.btn {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 28px;
  border-radius: 12px;
  font-family: var(--font-body);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  overflow: hidden;
  transition: all 0.5s cubic-bezier(0.23, 1, 0.32, 1);
  z-index: 1;
}

.btn::before {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 14px;
  background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary), var(--accent-primary));
  background-size: 200% 100%;
  opacity: 0;
  transition: opacity 0.5s ease;
  z-index: -1;
  animation: shimmer 3s linear infinite;
  filter: blur(6px);
}

.btn:hover::before {
  opacity: 0.6;
}

.btn:hover:not(:disabled) {
  transform: scale(1.06);
  transition: transform 0.5s cubic-bezier(0.23, 1, 0.32, 1);
}

.btn:active:not(:disabled) {
  transform: scale(0.98);
}

.btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  transform: none !important;
}

.btn:disabled::before {
  opacity: 0 !important;
}

.btn.primary {
  background: linear-gradient(135deg, var(--accent-primary), #9D4EDD);
  color: #fff;
  box-shadow: 0 4px 20px rgba(199, 125, 255, 0.25);
}

.btn.primary:hover:not(:disabled) {
  box-shadow: 0 6px 30px rgba(199, 125, 255, 0.45);
}

.btn.danger {
  background: linear-gradient(135deg, var(--accent-danger), #FF8E8E);
  color: #fff;
  box-shadow: 0 4px 20px rgba(255, 107, 107, 0.25);
}

.btn.danger:hover:not(:disabled) {
  box-shadow: 0 6px 30px rgba(255, 107, 107, 0.45);
}

.btn.danger::before {
  background: linear-gradient(90deg, var(--accent-danger), #FFB4B4, var(--accent-danger));
  background-size: 200% 100%;
}

@media (max-width: 640px) {
  .home { gap: 18px; }
  .transcript-box { padding: 24px; min-height: 140px; border-radius: 16px; }
  .text { font-size: 18px; }
  .controls { flex-direction: column; width: 100%; max-width: 280px; }
  .btn { justify-content: center; }
}
</style>
