<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request, type KnowledgeDoc } from '../api'
import PaginationControl from '../components/PaginationControl.vue'

const props = defineProps<{ id?: string }>()
const rows = ref<KnowledgeDoc[]>([])
const detail = ref<any>(null)
const file = ref<File | null>(null)
const name = ref('')
const version = ref('1')
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize.value)))
const pagedRows = computed(() => rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const rangeStart = computed(() => rows.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, rows.value.length))

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (props.id) detail.value = await request('/knowledge/documents/' + props.id)
    else rows.value = await request<KnowledgeDoc[]>('/knowledge/documents')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '知识库加载失败'
  } finally { loading.value = false }
}
async function upload() {
  if (!file.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value); form.append('version', version.value)
    await request('/knowledge/documents', { method: 'POST', body: form })
    notice.value = '文档已上传并完成解析，等待索引或发布'; file.value = null; page.value = 1; await load()
  } catch (e) { error.value = e instanceof Error ? e.message : '上传失败' }
  finally { busy.value = false }
}
async function action(name: string) {
  if (!props.id) return
  busy.value = true
  try { detail.value = await request('/knowledge/documents/' + props.id + '/' + name, { method: 'POST' }) }
  catch (e) { error.value = e instanceof Error ? e.message : '操作失败' }
  finally { busy.value = false }
}
watch(() => props.id, () => { page.value = 1; load() })
watch(pageSize, () => { page.value = 1 })
watch(pages, (value) => { if (page.value > value) page.value = value })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">KNOWLEDGE OPERATIONS</span><h2>{{ props.id ? '文档详情' : '知识库管理' }}</h2><p>{{ props.id ? '查看解析片段、索引状态和发布版本。' : '只有已发布版本会进入诊断检索。' }}</p></div><RouterLink v-if="props.id" class="button secondary" to="/knowledge">返回列表</RouterLink></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p><p v-if="notice" class="inline-notice" role="status">{{ notice }}</p><div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else-if="props.id && detail">
      <div class="detail-card"><div class="detail-title"><div><span class="eyebrow">{{ detail.name }} / v{{ detail.version }}</span><h3>文档内容与生命周期</h3></div><span class="pill" :class="'pill-' + detail.status">{{ detail.status }}</span></div><div class="action-bar"><button v-if="detail.status === 'indexed' || detail.status === 'uploaded'" class="button primary" :disabled="busy" @click="action('publish')">发布到检索</button><button v-if="detail.status === 'published'" class="button secondary" :disabled="busy" @click="action('retire')">停用版本</button><button v-if="detail.status === 'uploaded' || detail.status === 'failed'" class="button secondary" :disabled="busy" @click="action('index')">重新索引</button></div><div v-for="chunk in detail.chunks" :key="chunk.id" class="chunk-card"><span class="eyebrow">{{ chunk.section || '片段' }}</span><p>{{ chunk.text }}</p><small>设备型号：{{ chunk.device_model || '通用' }}</small></div><div v-if="!detail.chunks?.length" class="empty-panel">暂无解析片段。</div></div>
    </template>
    <template v-else>
      <div class="upload-panel"><div class="upload-intro"><span class="eyebrow">IMPORT DOCUMENT</span><h3>上传现场知识</h3><p>支持 TXT、DOCX、PDF。上传后先解析和索引，再由知识管理员发布。</p></div><div class="form-grid upload-form-grid"><label>版本<input v-model="version" class="version-input"></label><label class="file-field">文件<span class="file-picker"><span class="file-picker-button">选择文件</span><span class="file-picker-name">{{ file?.name || '未选择任何文件' }}</span><input class="visually-hidden" type="file" accept=".txt,.docx,.pdf" @change="file = ($event.target as HTMLInputElement).files?.[0] || null"></span></label></div><button class="button primary upload-submit" type="button" :disabled="!file || busy" @click="upload">{{ busy ? '处理中…' : '上传并解析' }}</button></div><div class="table-wrap"><table><thead><tr><th>文档</th><th>版本</th><th>状态</th><th>片段</th><th>创建时间</th><th></th></tr></thead><tbody><tr v-for="doc in pagedRows" :key="doc.id"><td><strong>{{ doc.name }}</strong><small>{{ doc.id.slice(0,8) }}</small></td><td>v{{ doc.version }}</td><td><span class="pill" :class="'pill-' + doc.status">{{ doc.status }}</span></td><td>{{ doc.chunks }}</td><td>{{ new Date(doc.created_at).toLocaleString('zh-CN') }}</td><td><RouterLink class="text-link" :to="'/knowledge/' + doc.id">详情 →</RouterLink></td></tr><tr v-if="!pagedRows.length"><td colspan="6" class="table-empty">暂无文档，请上传第一份设备手册。</td></tr></tbody></table></div>
      <PaginationControl v-if="rows.length" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="rows.length" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
</template>