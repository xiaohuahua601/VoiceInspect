<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request, requestPage, type Session } from '../api'
import PaginationControl from '../components/PaginationControl.vue'
import { renderMarkdown } from '../utils/markdown'
import DiagnosticEvidence from '../components/DiagnosticEvidence.vue'

const props = defineProps<{ id?: string }>()
const rows = ref<Session[]>([])
const detail = ref<any>(null)
const query = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const error = ref('')
const rangeStart = computed(() => total.value ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, total.value))

async function load() {
  loading.value = true; error.value = ''
  try {
    if (props.id) detail.value = await request('/sessions/' + props.id)
    else {
      const result = await requestPage<Session>('/sessions', { page: page.value, page_size: pageSize.value, search: query.value })
      rows.value = result.items; total.value = result.meta.total; pages.value = result.meta.pages
    }
  } catch (e) { error.value = e instanceof Error ? e.message : '会话加载失败' }
  finally { loading.value = false }
}
watch(() => props.id, () => { page.value = 1; load() })
watch(query, () => { page.value = 1; load() })
watch(pageSize, () => { page.value = 1; load() })
watch(page, () => { if (!props.id) load() })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">DIAGNOSIS SESSIONS</span><h2>{{ props.id ? '会话详情' : '诊断会话' }}</h2><p>{{ props.id ? '查看完整消息、阶段状态和引用证据。' : '所有诊断任务的可追溯记录。' }}</p></div><RouterLink v-if="props.id" class="button secondary" to="/sessions">返回列表</RouterLink><RouterLink v-else class="button primary" to="/diagnosis">新建诊断</RouterLink></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p>
    <div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else-if="props.id && detail">
      <div class="detail-card"><div class="detail-title"><div><span class="eyebrow">{{ detail.status }}</span><h3>{{ detail.title }}</h3></div><span class="pill">{{ detail.device_id || '未绑定设备' }}</span></div>
        <div v-for="message in detail.messages" :key="message.id" class="message-row"><span class="message-role">{{ message.role === 'user' ? '用户' : '助手' }}</span><div><p v-if="message.role === 'user'" class="session-plain-text">{{ message.text || '（无文本）' }}</p><div v-else class="answer-markdown session-answer" v-html="renderMarkdown(message.text)"></div><DiagnosticEvidence :evidence="message.observations" /><small>{{ new Date(message.created_at).toLocaleString('zh-CN') }}</small><div v-if="message.citations?.length" class="citation-mini">引用 {{ message.citations.length }} 条 · {{ Object.entries(message.stage_states || {}).filter(([, value]) => typeof value === 'string').map(([key, value]) => key + ':' + value).join(' / ') }}</div></div></div>
        <div v-if="!detail.messages?.length" class="empty-panel">该会话暂无消息。</div>
      </div>
    </template>
    <template v-else>
      <div class="toolbar sessions-toolbar"><input v-model="query" placeholder="搜索会话标题或设备编号" aria-label="搜索会话"></div>
      <div class="table-wrap"><table><thead><tr><th>会话</th><th>设备</th><th>状态</th><th>创建时间</th><th></th></tr></thead><tbody><tr v-for="item in rows" :key="item.id"><td><strong>{{ item.title }}</strong><small>{{ item.id }}</small></td><td>{{ item.device_id || '未绑定' }}</td><td><span class="pill">{{ item.status }}</span></td><td>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</td><td><RouterLink class="text-link" :to="'/sessions/' + item.id">详情</RouterLink></td></tr><tr v-if="!rows.length"><td colspan="5" class="table-empty">{{ query ? '没有符合条件的会话。' : '暂无会话，先去创建一次诊断。' }}</td></tr></tbody></table></div>
      <PaginationControl v-if="total" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="total" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
</template>
