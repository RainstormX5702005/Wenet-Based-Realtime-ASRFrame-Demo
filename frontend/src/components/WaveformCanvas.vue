<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps({ analyser: Object, recording: Boolean })
const canvas = ref(null)
const W = 800, H = 120
let ctx = null, raf = null

function draw() {
  if (!ctx) { raf = requestAnimationFrame(draw); return }
  if (!props.analyser || !props.recording) {
    ctx.clearRect(0, 0, W, H)
    // Idle line
    ctx.strokeStyle = 'rgba(199, 125, 255, 0.12)'
    ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke()
    // Idle pulse dots
    const t = Date.now() / 1000
    for (let i = 0; i < 5; i++) {
      const x = W / 2 + (i - 2) * 40
      const y = H / 2 + Math.sin(t * 2 + i) * 3
      const r = 2 + Math.sin(t * 3 + i) * 1
      ctx.fillStyle = `rgba(199, 125, 255, ${0.15 + Math.sin(t + i) * 0.1})`
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill()
    }
    raf = requestAnimationFrame(draw)
    return
  }

  const n = props.analyser.frequencyBinCount
  const buf = new Uint8Array(n)
  props.analyser.getByteTimeDomainData(buf)
  ctx.clearRect(0, 0, W, H)

  // Glow fill
  const g = ctx.createLinearGradient(0, 0, W, 0)
  g.addColorStop(0, 'rgba(199, 125, 255, 0)')
  g.addColorStop(0.5, 'rgba(199, 125, 255, 0.1)')
  g.addColorStop(1, 'rgba(199, 125, 255, 0)')
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)

  // Main wave
  ctx.lineWidth = 2.5; ctx.strokeStyle = 'rgba(199, 125, 255, 0.9)'
  ctx.beginPath()
  let x = 0, sw = W / n
  for (let i = 0; i < n; i++) {
    const y = (buf[i] / 128.0) * H / 2
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    x += sw
  }
  ctx.stroke()

  // Echo wave
  ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(0, 229, 255, 0.3)'
  ctx.beginPath(); x = 0
  for (let i = 0; i < n; i++) {
    const y = (buf[i] / 128.0) * H / 2 + 4
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    x += sw
  }
  ctx.stroke()

  raf = requestAnimationFrame(draw)
}

onMounted(() => { ctx = canvas.value.getContext('2d'); draw() })
onUnmounted(() => { if (raf) cancelAnimationFrame(raf) })
</script>

<template>
  <div class="wrap">
    <canvas ref="canvas" :width="W" :height="H" />
  </div>
</template>

<style scoped>
.wrap { width: 100%; max-width: 700px; }
canvas { width: 100%; height: 120px; border-radius: 12px; background: var(--bg-panel); border: 1px solid var(--border-subtle); }
</style>
