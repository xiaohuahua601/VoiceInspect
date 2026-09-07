<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request, type AuditEvent } from '../api'
import PaginationControl from '../components/PaginationControl.vue'

const rows = ref<AuditEvent[]>([])
const query = ref('')
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')
const filteredRows = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return rows.value
  return rows.value.filter((item) => (item.action + (item.target || '') + item.trace_id).toLowerCase().includes(keyword))
})
const pages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value)))
const pagedRows = computed(() => filteredRows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const rangeStart = computed(() => filteredRows.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, filteredRows.value.length))

async function load() {
  loading.value = true
  error.value = ''
  try { rows.value = await request<AuditEvent[]>('/audit-events') }
  catch (e) { error.value = e instanceof Error ? e.message : '审计加载失败' }
  finally { loading.value = false }
}
watch(query, () => { page.value = 1 })
watch(pageSize, () => { page.value = 1 })
watch(pages, (value) => { if (page.value > value) page.value = value })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">AUDIT TRAIL</span><h2>审计追踪</h2><p>记录登录、诊断、故障、知识和系统配置变更。</p></div><button class="button secondary" type="button" @click="load" :disabled="loading">刷新</button></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p>
    <div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else>
      <div class="toolbar"><input v-model="query" placeholder="按动作、对象或 trace_id 搜索" aria-label="搜索审计"></div>
      <div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>对象</th><th>trace_id</th><th>结果</th></tr></thead><tbody><tr v-for="event in pagedRows" :key="event.id"><td>{{ new Date(event.created_at).toLocaleString('zh-CN') }}</td><td><strong>{{ event.action }}</strong></td><td>{{ event.target || '—' }}</td><td><code>{{ event.trace_id.slice(0,12) }}</code></td><td><span class="pill pill-success">{{ event.result }}</span></td></tr><tr v-if="!pagedRows.length"><td colspan="5" class="table-empty">{{ rows.length ? '没有符合条件的审计事件。' : '暂无审计事件。' }}</td></tr></tbody></table></div>
      <PaginationControl v-if="filteredRows.length" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="filteredRows.length" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
</template>