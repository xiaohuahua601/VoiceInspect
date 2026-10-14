<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { getStoredUser, request, requestPage, type Fault, type User } from '../api'
import PaginationControl from '../components/PaginationControl.vue'

const props = defineProps<{ id?: string }>()
const rows = ref<Fault[]>([])
const detail = ref<any>(null)
const assignees = ref<User[]>([])
const selectedAssignee = ref('')
const status = ref('')
const query = ref('')
const note = ref('')
const processingNote = ref('')
const faultLocation = ref('')
const observedEvidence = ref('')
const resolution = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const actionBusy = ref(false)
const labels: Record<string, string> = { new: '新建', confirmed: '已确认', in_progress: '处理中', pending_verification: '待验证', closed: '已关闭' }
const user = computed(() => getStoredUser())
const canManageFaults = computed(() => ['maintenance_supervisor', 'system_admin'].includes(user.value?.role ?? ''))
const canSubmitProcessing = computed(() => user.value?.role === 'operator' && detail.value?.assigned_to === user.value?.id && detail.value?.status === 'in_progress')
const rangeStart = computed(() => total.value ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, total.value))

const MAX_TEXTAREA_HEIGHT = 220
function resizeTextarea(target: HTMLTextAreaElement) {
  target.style.height = 'auto'
  const nextHeight = Math.min(Math.max(target.scrollHeight, 48), MAX_TEXTAREA_HEIGHT)
  target.style.height = `${nextHeight}px`
  target.style.overflowY = target.scrollHeight > MAX_TEXTAREA_HEIGHT ? 'auto' : 'hidden'
}
function autoResize(event: Event) {
  resizeTextarea(event.currentTarget as HTMLTextAreaElement)
}
function resizeVisibleTextareas() {
  document.querySelectorAll<HTMLTextAreaElement>('.page-view textarea[data-autosize]').forEach(resizeTextarea)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (props.id) {
      detail.value = await request('/fault-records/' + props.id)
      selectedAssignee.value = detail.value.assigned_to || ''
      faultLocation.value = detail.value.fault_location || ''
      observedEvidence.value = detail.value.observed_evidence || ''
      resolution.value = detail.value.resolution || ''
      if (canManageFaults.value) {
        assignees.value = await request<User[]>('/fault-records/assignees?fault_id=' + encodeURIComponent(props.id))
      }
    } else {
      const result = await requestPage<Fault>('/fault-records', { page: page.value, page_size: pageSize.value, status: status.value, search: query.value })
      rows.value = result.items; total.value = result.meta.total; pages.value = result.meta.pages
    }
    await nextTick()
    resizeVisibleTextareas()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '故障加载失败'
  } finally { loading.value = false }
}

async function transition(action: string) {
  actionBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    await request('/fault-records/' + props.id + '/' + action, {
      method: 'POST',
      body: JSON.stringify({
        note: note.value || '后台处理操作',
        fault_location: faultLocation.value.trim() || undefined,
        observed_evidence: observedEvidence.value.trim() || undefined,
        resolution: resolution.value.trim() || undefined,
      }),
    })
    await load()
    note.value = ''
    notice.value = '状态已更新，操作记录已写入审计。'
    if (props.id && canManageFaults.value) assignees.value = await request<User[]>('/fault-records/assignees?fault_id=' + encodeURIComponent(props.id))
  } catch (e) { error.value = e instanceof Error ? e.message : '状态变更失败' }
  finally { actionBusy.value = false }
}

async function assignFault() {
  if (!props.id || !selectedAssignee.value) {
    error.value = '请选择负责人后再分派。'
    return
  }
  actionBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    await request('/fault-records/' + props.id + '/assign', {
      method: 'POST',
      body: JSON.stringify({
        assigned_to: selectedAssignee.value,
        note: note.value || undefined,
        fault_location: faultLocation.value.trim() || undefined,
        observed_evidence: observedEvidence.value.trim() || undefined,
        idempotency_key: `assign-${props.id}-${selectedAssignee.value}`,
      }),
    })
    await load()
    note.value = ''
    notice.value = detail.value.status === 'in_progress' ? '负责人已保存，故障已进入处理中。' : '负责人已更新。'
  } catch (e) { error.value = e instanceof Error ? e.message : '负责人分派失败' }
  finally { actionBusy.value = false }
}

async function submitProcessingResult() {
  if (!props.id || !processingNote.value.trim()) {
    error.value = '请填写处理结果或复测说明后再提交。'
    return
  }
  if (!faultLocation.value.trim() || !observedEvidence.value.trim()) {
    error.value = '请先填写故障部位和现场证据，便于主管排查和验证。'
    return
  }
  actionBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    await request('/fault-records/' + props.id + '/submit-verification', {
      method: 'POST',
      body: JSON.stringify({
        note: processingNote.value.trim(),
        fault_location: faultLocation.value.trim(),
        observed_evidence: observedEvidence.value.trim(),
      }),
    })
    await load()
    processingNote.value = ''
    notice.value = '处理结果已提交，等待维修主管验证并关闭故障。'
  } catch (e) { error.value = e instanceof Error ? e.message : '处理结果提交失败' }
  finally { actionBusy.value = false }
}

watch(() => props.id, () => { page.value = 1; notice.value = ''; load() })
watch(status, () => { page.value = 1; if (!props.id) load() })
watch(query, () => { page.value = 1; if (!props.id) load() })
watch(pageSize, () => { page.value = 1; if (!props.id) load() })
watch(page, () => { if (!props.id) load() })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">FAULT MANAGEMENT</span><h2>{{ props.id ? '故障详情' : '故障闭环' }}</h2><p>{{ props.id ? '状态流转、负责人分派、处理记录和审计轨迹。' : '按严重级别与处理阶段管理现场故障。' }}</p></div><RouterLink v-if="props.id" class="button secondary" to="/faults">返回列表</RouterLink></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p>
    <p v-if="notice" class="inline-success" role="status">{{ notice }}</p>
    <div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else-if="props.id && detail">
      <div class="detail-card">
        <div class="detail-title"><div><span class="eyebrow">FAULT / {{ detail.id.slice(0,8) }}</span><h3>{{ detail.symptom }}</h3></div><span class="pill" :class="'pill-' + detail.status">{{ labels[detail.status] || detail.status }}</span></div>
        <dl class="detail-grid"><div><dt>严重级别</dt><dd><span class="severity-label" :class="'severity-' + detail.severity">{{ detail.severity }}</span></dd></div><div><dt>故障部位 / 位置</dt><dd>{{ detail.fault_location || '待补充' }}</dd></div><div><dt>设备</dt><dd>{{ detail.device_id }}</dd></div><div><dt>创建时间</dt><dd>{{ new Date(detail.created_at).toLocaleString('zh-CN') }}</dd></div><div><dt>当前负责人</dt><dd>{{ detail.assigned_to_name || detail.assigned_to || '待分派' }}</dd></div><div><dt>现场证据</dt><dd>{{ detail.observed_evidence || '待补充' }}</dd></div></dl>
        <section v-if="detail.processing_result" class="processing-result-panel"><div><span class="eyebrow">PREVIOUS HANDLER RESULT</span><h4>上一处理人的处理结果</h4></div><p>{{ detail.processing_result }}</p><small>{{ detail.processing_by_name || '未知处理人' }} · {{ detail.processing_at ? new Date(detail.processing_at).toLocaleString('zh-CN') : '时间未知' }}</small></section>
        <div v-if="(canManageFaults || canSubmitProcessing) && detail.status !== 'closed'" class="assignment-panel fault-context-panel">
          <div><span class="eyebrow">FIELD CONTEXT</span><h4>故障定位与排查依据</h4><p>没有明确部位和现场证据时，系统不允许关闭故障。</p></div>
          <div class="form-grid"><label>故障部位 / 位置<input v-model="faultLocation" maxlength="255" placeholder="例如：二级冷却器出口、液压泵入口" /></label><label>现场证据 / 排查依据<textarea v-model="observedEvidence" class="resize-none" data-autosize @input="autoResize" rows="3" maxlength="4000" placeholder="填写报警码、仪表读数、异响、泄漏位置或复测结果"></textarea></label></div>
          <label v-if="canManageFaults && detail.status === 'pending_verification'">最终处理结果 / 验证依据<textarea v-model="resolution" class="resize-none" data-autosize @input="autoResize" rows="3" maxlength="4000" placeholder="填写维修措施、复测结果和关闭依据"></textarea></label>
        </div>
        <div v-if="canManageFaults && ['confirmed', 'in_progress'].includes(detail.status)" class="assignment-panel">
          <div><span class="eyebrow">ASSIGNMENT</span><h4>{{ detail.status === 'in_progress' ? '重新分派负责人' : '选择负责人并开始处理' }}</h4><p>仅显示当前故障所属组织内的在岗操作员和维修主管。</p></div>
          <div class="assignment-controls"><select v-model="selectedAssignee" aria-label="选择故障负责人"><option value="">请选择负责人</option><option v-for="candidate in assignees" :key="candidate.id" :value="candidate.id">{{ candidate.username }} · {{ candidate.role === 'maintenance_supervisor' ? '维修主管' : '操作员' }}</option></select><button class="button primary" :disabled="actionBusy || !selectedAssignee" @click="assignFault">{{ detail.status === 'in_progress' ? '保存改派' : '分派并开始' }}</button></div>
          <textarea v-model="note" class="assignment-note resize-none" data-autosize @input="autoResize" rows="2" maxlength="2000" placeholder="可选：填写分派说明或处理备注"></textarea>
          <p v-if="!assignees.length" class="empty-panel">当前组织没有可分派的在岗人员，请联系系统管理员。</p>
        </div>
        <div v-if="canSubmitProcessing" class="assignment-panel operator-work-panel">
          <div><span class="eyebrow">FIELD ACTION</span><h4>提交处理结果</h4><p>你是当前负责人。完成现场处理和复测后提交结果，由维修主管验证并关闭故障。</p></div>
          <textarea v-model="processingNote" class="assignment-note resize-none" data-autosize @input="autoResize" rows="3" maxlength="4000" placeholder="填写已执行的处理措施、复测读数和现场结果（必填）"></textarea>
          <div class="action-bar"><button class="button primary" :disabled="actionBusy || !processingNote.trim()" @click="submitProcessingResult">提交验证</button></div>
        </div>
        <div v-if="canManageFaults" class="action-bar"><button v-if="detail.status === 'new'" class="button primary" :disabled="actionBusy" @click="transition('confirm')">确认故障</button><button v-if="detail.status === 'in_progress'" class="button secondary" :disabled="actionBusy" @click="transition('verify')">提交验证</button><button v-if="detail.status === 'pending_verification'" class="button primary" :disabled="actionBusy || !faultLocation.trim() || !observedEvidence.trim() || !resolution.trim()" @click="transition('close')">关闭故障</button></div>
        <p v-if="!canManageFaults && !canSubmitProcessing" class="read-only-notice">当前账号为操作员，仅可查看授权范围内故障；状态变更和负责人分派由维修主管或系统管理员执行。</p>
        <p v-else-if="canSubmitProcessing" class="read-only-notice">处理结果提交后，维修主管负责验证并关闭故障。</p>
        <div class="event-timeline"><div v-for="event in detail.events" :key="event.id" class="event-item"><span class="timeline-dot"></span><div><strong>{{ labels[event.to_status] || event.to_status }}</strong><small>{{ event.note || '状态更新' }} · {{ event.actor_name || event.actor_id || '系统' }} · {{ new Date(event.created_at).toLocaleString('zh-CN') }}</small></div></div><div v-if="!detail.events?.length" class="empty-panel">暂无处理事件。</div></div>
      </div>
    </template>
    <template v-else>
      <div class="toolbar"><input v-model="query" placeholder="搜索故障现象、设备或负责人" aria-label="搜索故障"><select v-model="status" aria-label="筛选故障状态"><option value="">全部状态</option><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></div>
      <div class="table-wrap"><table><thead><tr><th>故障现象</th><th>设备</th><th>严重级别</th><th>负责人</th><th>状态</th><th>更新时间</th><th></th></tr></thead><tbody><tr v-for="fault in rows" :key="fault.id"><td><strong>{{ fault.symptom }}</strong><small>{{ fault.id.slice(0,8) }}</small></td><td>{{ fault.device_id }}</td><td><span class="severity-label" :class="'severity-' + fault.severity">{{ fault.severity }}</span></td><td>{{ fault.assigned_to_name || '待分派' }}</td><td><span class="pill" :class="'pill-' + fault.status">{{ labels[fault.status] || fault.status }}</span></td><td>{{ new Date(fault.updated_at || fault.created_at).toLocaleString('zh-CN') }}</td><td><RouterLink class="text-link" :to="'/faults/' + fault.id">查看 →</RouterLink></td></tr><tr v-if="!rows.length"><td colspan="7" class="table-empty">暂无符合条件的故障记录。</td></tr></tbody></table></div>
      <PaginationControl v-if="total" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="total" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
</template>
