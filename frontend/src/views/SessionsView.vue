<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { downloadFile, getStoredUser, request, requestPage, type Session } from '../api'
import ConfirmationDialog from '../components/ConfirmationDialog.vue'
import DiagnosticEvidence from '../components/DiagnosticEvidence.vue'
import PaginationControl from '../components/PaginationControl.vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{ id?: string }>()
const router = useRouter()
const currentUser = getStoredUser()
const rows = ref<Session[]>([])
const detail = ref<any>(null)
const query = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const pendingDeletion = ref<Session | null>(null)
const deletionError = ref('')
const deleting = ref(false)
const selectedIds = ref<string[]>([])
const pendingBatch = ref<Session[] | null>(null)
const batchDeleteError = ref('')
const batchDeleting = ref(false)
const attachmentObjectUrls = new Set<string>()
const rangeStart = computed(() => total.value ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, total.value))
const canDeleteDetail = computed(() => canDelete(detail.value))
const selectableRows = computed(() => rows.value.filter((item) => canDelete(item)))
const selectedSessions = computed(() => rows.value.filter((item) => selectedIds.value.includes(item.id)))
const allVisibleSelected = computed(() => selectableRows.value.length > 0 && selectableRows.value.every((item) => selectedIds.value.includes(item.id)))
const someVisibleSelected = computed(() => selectedIds.value.length > 0 && !allVisibleSelected.value)

function canDelete(session: Pick<Session, 'user_id'> | null | undefined) {
  return Boolean(session && (currentUser?.role === 'system_admin' || session.user_id === currentUser?.id))
}

function attachmentPath(attachment: { id: string; preview_url?: string }) {
  const previewUrl = attachment.preview_url || `/assets/${attachment.id}/content`
  return previewUrl.startsWith('/api/v1/') ? previewUrl.slice('/api/v1'.length) : previewUrl
}

async function hydrateAttachments(message: any) {
  if (!message.attachments?.length) return message
  const attachments = await Promise.all(message.attachments.map(async (attachment: any) => {
    try {
      const url = URL.createObjectURL(await downloadFile(attachmentPath(attachment)))
      attachmentObjectUrls.add(url)
      return { ...attachment, preview_url: url }
    } catch {
      return { ...attachment, preview_url: '' }
    }
  }))
  return { ...message, attachments }
}

function releaseAttachmentUrls() {
  attachmentObjectUrls.forEach((url) => URL.revokeObjectURL(url))
  attachmentObjectUrls.clear()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (props.id) {
      releaseAttachmentUrls()
      const result: any = await request('/sessions/' + props.id)
      result.messages = await Promise.all((result.messages ?? []).map(hydrateAttachments))
      detail.value = result
    } else {
      const result = await requestPage<Session>('/sessions', { page: page.value, page_size: pageSize.value, search: query.value })
      rows.value = result.items
      total.value = result.meta.total
      pages.value = result.meta.pages
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '会话加载失败'
  } finally {
    loading.value = false
  }
}

function openDeletion(session: Session) {
  pendingDeletion.value = session
  deletionError.value = ''
}

function closeDeletion() {
  if (deleting.value) return
  pendingDeletion.value = null
  deletionError.value = ''
}

function toggleSelection(session: Session) {
  if (!canDelete(session) || deleting.value || batchDeleting.value) return
  selectedIds.value = selectedIds.value.includes(session.id)
    ? selectedIds.value.filter((id) => id !== session.id)
    : [...selectedIds.value, session.id]
}

function toggleAll(event: Event) {
  if (deleting.value || batchDeleting.value) return
  const checked = (event.target as HTMLInputElement).checked
  const visibleIds = selectableRows.value.map((item) => item.id)
  selectedIds.value = checked
    ? [...new Set([...selectedIds.value, ...visibleIds])]
    : selectedIds.value.filter((id) => !visibleIds.includes(id))
}

function openBatchDeletion() {
  if (!selectedSessions.value.length || deleting.value || batchDeleting.value) return
  pendingBatch.value = [...selectedSessions.value]
  batchDeleteError.value = ''
}

function closeBatchDeletion() {
  if (batchDeleting.value) return
  pendingBatch.value = null
  batchDeleteError.value = ''
}

async function confirmBatchDeletion() {
  const batch = pendingBatch.value
  if (!batch?.length) return
  batchDeleting.value = true
  batchDeleteError.value = ''
  try {
    const result: any = await request('/sessions/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ session_ids: batch.map((item) => item.id) }),
    })
    const deletedCount = result.deleted?.length ?? 0
    const skippedCount = result.skipped?.length ?? 0
    const failedCount = result.failed?.length ?? 0
    const messages = [`已删除 ${deletedCount} 个会话。`]
    if (skippedCount) messages.push(`${skippedCount} 个会话因仍有任务未删除。`)
    if (failedCount) messages.push(`${failedCount} 个会话无权删除或已不存在。`)
    notice.value = messages.join(' ')
    selectedIds.value = []
    pendingBatch.value = null
    if (deletedCount && rows.value.length === deletedCount && page.value > 1) page.value -= 1
    else await load()
  } catch (e) {
    batchDeleteError.value = e instanceof Error ? e.message : '批量删除会话失败，请重试。'
  } finally {
    batchDeleting.value = false
  }
}

async function deleteSession() {
  const session = pendingDeletion.value
  if (!session) return
  deleting.value = true
  deletionError.value = ''
  try {
    await request(`/sessions/${session.id}`, { method: 'DELETE' })
    notice.value = `已删除会话“${session.title}”。`
    pendingDeletion.value = null
    if (props.id) {
      releaseAttachmentUrls()
      await router.replace('/sessions')
      return
    }
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    else await load()
  } catch (e) {
    deletionError.value = e instanceof Error ? e.message : '删除会话失败，请重试。'
  } finally {
    deleting.value = false
  }
}

watch(() => props.id, () => {
  page.value = 1
  notice.value = ''
  load()
})
watch(query, () => {
  page.value = 1
  selectedIds.value = []
  load()
})
watch(pageSize, () => {
  page.value = 1
  selectedIds.value = []
  load()
})
watch(page, () => {
  selectedIds.value = []
  if (!props.id) load()
})
onMounted(load)
onBeforeUnmount(releaseAttachmentUrls)
</script>

<template>
  <section class="page-view">
    <div class="page-heading">
      <div>
        <span class="eyebrow">DIAGNOSIS SESSIONS</span>
        <h2>{{ props.id ? '会话详情' : '诊断会话' }}</h2>
        <p>{{ props.id ? '查看完整消息、阶段状态和引用证据。' : '所有诊断任务的可追溯记录。' }}</p>
      </div>
      <div class="page-heading-actions">
        <button v-if="props.id && detail && canDeleteDetail" class="button danger compact" type="button" @click="openDeletion(detail)">删除会话</button>
        <RouterLink v-if="props.id" class="button secondary compact" to="/sessions">返回列表</RouterLink>
        <RouterLink v-else class="button primary" to="/diagnosis">新建诊断</RouterLink>
      </div>
    </div>
    <p v-if="notice" class="inline-success" role="status">{{ notice }}</p>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p>
    <div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else-if="props.id && detail">
      <div class="detail-card">
        <div class="detail-title">
          <div><span class="eyebrow">{{ detail.status }}</span><h3>{{ detail.title }}</h3></div>
          <span class="pill">{{ detail.device_id || '未绑定设备' }}</span>
        </div>
        <div v-for="message in detail.messages" :key="message.id" class="message-row">
          <span class="message-role">{{ message.role === 'user' ? '用户' : '助手' }}</span>
          <div>
            <div v-if="message.role === 'user' && message.attachments?.length" class="message-attachments session-attachments">
              <template v-for="attachment in message.attachments" :key="attachment.id">
                <figure v-if="attachment.kind === 'image'" class="message-attachment message-image-attachment">
                  <img v-if="attachment.preview_url" :src="attachment.preview_url" :alt="attachment.name" />
                  <div v-else class="attachment-unavailable">图片暂不可用</div>
                  <figcaption>{{ attachment.name }}</figcaption>
                </figure>
                <div v-else class="message-attachment message-audio-attachment">
                  <span class="message-attachment-icon" aria-hidden="true">◉</span>
                  <div><strong>现场语音</strong><small>{{ attachment.name }}</small></div>
                  <audio v-if="attachment.preview_url" :src="attachment.preview_url" controls preload="metadata" :aria-label="attachment.name"></audio>
                  <span v-else class="attachment-unavailable">音频暂不可用</span>
                </div>
              </template>
            </div>
            <p v-if="message.role === 'user'" class="session-plain-text">{{ message.text || '（无文本）' }}</p>
            <div v-else class="answer-markdown session-answer" v-html="renderMarkdown(message.text)"></div>
            <DiagnosticEvidence :evidence="message.observations" />
            <small>{{ new Date(message.created_at).toLocaleString('zh-CN') }}</small>
            <div v-if="message.citations?.length" class="citation-mini">引用 {{ message.citations.length }} 条 · {{ Object.entries(message.stage_states || {}).filter(([, value]) => typeof value === 'string').map(([key, value]) => key + ':' + value).join(' / ') }}</div>
          </div>
        </div>
        <div v-if="!detail.messages?.length" class="empty-panel">该会话暂无消息。</div>
      </div>
    </template>
    <template v-else>
      <div class="toolbar sessions-toolbar"><input v-model="query" placeholder="搜索会话标题或设备编号" aria-label="搜索会话"></div>
      <div v-if="rows.length" class="bulk-toolbar" role="region" aria-label="会话批量操作" aria-live="polite">
        <div><strong>批量操作</strong><span>已选择 {{ selectedIds.length }} 个当前页会话</span></div>
        <button class="button danger compact" type="button" :disabled="!selectedIds.length || deleting || batchDeleting" @click="openBatchDeletion">删除所选</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="selection-column"><input class="selection-control" type="checkbox" :checked="allVisibleSelected" :indeterminate="someVisibleSelected" :disabled="!selectableRows.length || deleting || batchDeleting" aria-label="选择当前页可删除会话" @change="toggleAll"></th><th>会话</th><th>设备</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
          <tbody>
            <tr v-for="item in rows" :key="item.id">
              <td class="selection-column"><input class="selection-control" type="checkbox" :checked="selectedIds.includes(item.id)" :disabled="!canDelete(item) || deleting || batchDeleting" :aria-label="`选择会话 ${item.title}`" @change="toggleSelection(item)"></td>
              <td><strong>{{ item.title }}</strong><small>{{ item.id }}</small></td>
              <td>{{ item.device_id || '未绑定' }}</td>
              <td><span class="pill">{{ item.status }}</span></td>
              <td>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</td>
              <td><div class="table-actions"><RouterLink class="text-link" :to="'/sessions/' + item.id">详情</RouterLink><button v-if="canDelete(item)" class="text-button danger" type="button" :aria-label="`删除会话 ${item.title}`" @click="openDeletion(item)">删除</button></div></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="6" class="table-empty">{{ query ? '没有符合条件的会话。' : '暂无会话，先去创建一次诊断。' }}</td></tr>
          </tbody>
        </table>
      </div>
      <PaginationControl v-if="total" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="total" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
  <ConfirmationDialog
    :open="Boolean(pendingBatch)"
    eyebrow="BULK DELETE"
    title="批量删除会话？"
    :description="`将永久删除已选择的 ${pendingBatch?.length ?? 0} 个会话及其消息、附件和报告。已创建的故障记录会保留，但仍有任务运行的会话会跳过并返回原因。`"
    confirm-label="删除所选会话"
    :busy="batchDeleting"
    :error="batchDeleteError"
    @cancel="closeBatchDeletion"
    @confirm="confirmBatchDeletion"
  />
  <ConfirmationDialog
    :open="Boolean(pendingDeletion)"
    eyebrow="PERMANENT DELETE"
    title="删除会话？"
    :description="`会话“${pendingDeletion?.title ?? ''}”的所有消息、上传附件及该会话生成的报告都会被永久删除。已创建的故障记录会保留，但不再关联该会话。`"
    confirm-label="删除会话"
    :busy="deleting"
    :error="deletionError"
    @cancel="closeDeletion"
    @confirm="deleteSession"
  />
</template>
