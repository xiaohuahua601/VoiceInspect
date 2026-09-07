<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request, type Fault } from '../api'
import PaginationControl from '../components/PaginationControl.vue'

const props = defineProps<{ id?: string }>()
const rows = ref<Fault[]>([])
const detail = ref<any>(null)
const status = ref('')
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')
const actionBusy = ref(false)
const labels: Record<string, string> = { new: '新建', confirmed: '已确认', in_progress: '处理中', pending_verification: '待验证', closed: '已关闭' }
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize.value)))
const pagedRows = computed(() => rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const rangeStart = computed(() => rows.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, rows.value.length))

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (props.id) detail.value = await request('/fault-records/' + props.id)
    else rows.value = await request<Fault[]>('/fault-records' + (status.value ? '?status=' + status.value : ''))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '故障加载失败'
  } finally { loading.value = false }
}
async function transition(action: string) {
  actionBusy.value = true
  error.value = ''
  try { detail.value = await request('/fault-records/' + props.id + '/' + action, { method: 'POST', body: JSON.stringify({ note: '后台处理操作' }) }) }
  catch (e) { error.value = e instanceof Error ? e.message : '状态变更失败' }
  finally { actionBusy.value = false }
}
watch(() => props.id, () => { page.value = 1; load() })
watch(status, () => { page.value = 1; if (!props.id) load() })
watch(pageSize, () => { page.value = 1 })
watch(pages, (value) => { if (page.value > value) page.value = value })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">FAULT MANAGEMENT</span><h2>{{ props.id ? '故障详情' : '故障闭环' }}</h2><p>{{ props.id ? '状态流转、处理记录和审计轨迹。' : '按严重级别与处理阶段管理现场故障。' }}</p></div><RouterLink v-if="props.id" class="button secondary" to="/faults">返回列表</RouterLink></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p>
    <div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else-if="props.id && detail">
      <div class="detail-card"><div class="detail-title"><div><span class="eyebrow">FAULT / {{ detail.id.slice(0,8) }}</span><h3>{{ detail.symptom }}</h3></div><span class="pill" :class="'pill-' + detail.status">{{ labels[detail.status] || detail.status }}</span></div><dl class="detail-grid"><div><dt>严重级别</dt><dd>{{ detail.severity }}</dd></div><div><dt>设备</dt><dd>{{ detail.device_id }}</dd></div><div><dt>创建时间</dt><dd>{{ new Date(detail.created_at).toLocaleString('zh-CN') }}</dd></div><div><dt>负责人</dt><dd>{{ detail.assigned_to || '待分派' }}</dd></div></dl><div class="action-bar"><button v-if="detail.status === 'new'" class="button primary" :disabled="actionBusy" @click="transition('confirm')">确认故障</button><button v-if="detail.status === 'confirmed'" class="button primary" :disabled="actionBusy" @click="transition('assign')">分派并开始</button><button v-if="detail.status === 'in_progress'" class="button primary" :disabled="actionBusy" @click="transition('verify')">提交验证</button><button v-if="detail.status === 'pending_verification'" class="button primary" :disabled="actionBusy" @click="transition('close')">关闭故障</button></div><div class="event-timeline"><div v-for="event in detail.events" :key="event.id" class="event-item"><span class="timeline-dot"></span><div><strong>{{ labels[event.to_status] || event.to_status }}</strong><small>{{ event.note || '状态更新' }} · {{ new Date(event.created_at).toLocaleString('zh-CN') }}</small></div></div><div v-if="!detail.events?.length" class="empty-panel">暂无处理事件。</div></div></div>
    </template>
    <template v-else>
      <div class="toolbar"><select v-model="status" aria-label="筛选故障状态"><option value="">全部状态</option><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></div>
      <div class="table-wrap"><table><thead><tr><th>故障现象</th><th>设备</th><th>严重级别</th><th>状态</th><th>更新时间</th><th></th></tr></thead><tbody><tr v-for="fault in pagedRows" :key="fault.id"><td><strong>{{ fault.symptom }}</strong><small>{{ fault.id.slice(0,8) }}</small></td><td>{{ fault.device_id }}</td><td><span class="severity-label" :class="'severity-' + fault.severity">{{ fault.severity }}</span></td><td><span class="pill" :class="'pill-' + fault.status">{{ labels[fault.status] || fault.status }}</span></td><td>{{ new Date(fault.updated_at || fault.created_at).toLocaleString('zh-CN') }}</td><td><RouterLink class="text-link" :to="'/faults/' + fault.id">处理 →</RouterLink></td></tr><tr v-if="!pagedRows.length"><td colspan="6" class="table-empty">暂无符合条件的故障记录。</td></tr></tbody></table></div>
      <PaginationControl v-if="rows.length" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="rows.length" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
</template>