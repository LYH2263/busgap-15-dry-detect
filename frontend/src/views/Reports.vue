<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
type Mode = 'idle' | 'preview' | 'saved'
const trips = ref<any[]>([])
const reports = ref<any[]>([])
const events = ref<any[]>([])
const mode = ref<Mode>('idle')
const activeReport = ref<any | null>(null)
const stopName = ref('')
const loading = ref<'' | 'run' | 'preview'>('')

async function loadReports() {
  reports.value = await api('/reports')
}
function query() {
  const q = new URLSearchParams({ line_id: '1' })
  const stop = stopName.value.trim()
  if (stop) q.set('stop_name', stop)
  return q.toString()
}
// 试算：用当前阈值跑完全线或指定站，只返回事件，不写入任何报告记录
async function preview() {
  loading.value = 'preview'
  try {
    const res = await api<any>(`/reports/preview?${query()}`, { method: 'POST' })
    events.value = res.events || []
    mode.value = 'preview'
    activeReport.value = null
    // 有意不刷新报告列表：试算不产生记录，条数保持不变
  } finally { loading.value = '' }
}
// 真正检测：写入一条新的历史报告
async function run() {
  loading.value = 'run'
  try {
    const res = await api<any>(`/reports/run?${query()}`, { method: 'POST' })
    await loadReports()
    activeReport.value = reports.value.find((r) => r.id === res.id) || null
    events.value = res.events || []
    mode.value = 'saved'
  } finally { loading.value = '' }
}
function viewReport(r: any) {
  activeReport.value = r
  events.value = r.events || []
  mode.value = 'saved'
}
function fmtTime(iso: string) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : ''
}
function stripClass(s: string) {
  return s === 'bunching' ? 'bg-bunch' : s === 'large_gap' ? 'bg-large' : ''
}
function label(s: string) {
  return s === 'bunching' ? '串车' : s === 'large_gap' ? '大间隔' : '正常'
}
onMounted(async () => {
  trips.value = await api('/trips')
  await loadReports()
  if (reports.value.length) viewReport(reports.value[0])
})
</script>
<template>
  <h1>串车报告</h1>
  <p class="sub">按实际到站间隔对照计划发车间隔 · 竖直条带展示</p>
  <div class="bg-actions">
    <input v-model="stopName" placeholder="留空=跑完全线；指定站如：市民中心" />
    <button class="btn" :disabled="loading !== ''" @click="run">
      {{ loading === 'run' ? '检测中…' : '重新检测' }}
    </button>
    <button class="btn btn-preview" :disabled="loading !== ''" @click="preview">
      {{ loading === 'preview' ? '试算中…' : '试算' }}
    </button>
  </div>

  <div class="bg-reports">
    <strong>历史报告（{{ reports.length }} 条）</strong>
    <span
      v-for="r in reports"
      :key="r.id"
      class="bg-report-chip"
      :class="{ on: mode === 'saved' && activeReport?.id === r.id }"
      @click="viewReport(r)"
    >
      #{{ r.id }} · {{ r.stop_name }} · {{ fmtTime(r.created_at) }}
    </span>
    <span v-if="!reports.length" class="muted">暂无已保存报告</span>
  </div>

  <div v-if="mode === 'preview'" class="bg-mode bg-mode-preview">
    试算结果 · 未保存 · 仅按当前阈值计算，不会写入历史报告（历史报告仍为 {{ reports.length }} 条）
  </div>
  <div v-else-if="mode === 'saved' && activeReport" class="bg-mode bg-mode-saved">
    已保存报告 #{{ activeReport.id }} · 范围 {{ activeReport.stop_name }} · {{ fmtTime(activeReport.created_at) }}
  </div>
  <div v-else class="bg-mode muted">
    点击「试算」查看结果（不保存、条数不变），或点击「重新检测」写入一条新报告
  </div>

  <div class="bg-split">
    <aside class="bg-trip-col">
      <h2>关联班次</h2>
      <div v-for="r in trips" :key="r.id ?? r.trip_no" class="bg-trip-row">
        <div>
          <div>{{ r.trip_no }}</div>
          <div class="bg-trip-meta">{{ r.vehicle_no }}</div>
        </div>
        <div class="bg-trip-meta">{{ r.planned_depart }}</div>
      </div>
    </aside>
    <div class="bg-strip-col">
      <article
        v-for="(e, i) in events"
        :key="i"
        class="bg-gap-strip"
        :class="[stripClass(e.status), { 'bg-strip-preview': mode === 'preview' }]"
      >
        <header>
          <span>{{ e.stop_name }}</span>
          <span v-if="mode === 'preview'" class="badge badge-warn">试算</span>
        </header>
        <div class="bg-gap-body">
          <div class="bg-gap-val">{{ e.gap_min }}′</div>
          <div>计划 {{ e.planned_headway_min }}′</div>
          <div>{{ e.earlier_trip }} → {{ e.later_trip }}</div>
          <span class="badge" :class="e.status === 'bunching' ? 'badge-bad' : e.status === 'large_gap' ? 'badge-warn' : 'badge-ok'">
            {{ label(e.status) }}
          </span>
        </div>
      </article>
      <p v-if="!events.length" class="muted">暂无事件</p>
    </div>
  </div>
</template>
