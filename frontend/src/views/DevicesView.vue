<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request, requestPage, type Device } from '../api'
import PaginationControl from '../components/PaginationControl.vue'

const props = defineProps<{ id?: string }>()
const rows = ref<Device[]>([])
const detail = ref<any>(null)
const history = ref<any[]>([])
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
  loading.value = true
  error.value = ''
  try {
    if (props.id) {
      detail.value = await request('/devices/' + props.id)
      const result = await request<any>('/devices/' + props.id + '/history')
      history.value = result.records || []
    } else {
      const result = await requestPage<Device>('/devices', { page: page.value, page_size: pageSize.value, search: query.value })
      rows.value = result.items; total.value = result.meta.total; pages.value = result.meta.pages
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '设备加载失败'
  } finally { loading.value = false }
}
watch(() => props.id, () => { page.value = 1; load() })
watch(query, () => { page.value = 1; load() })
watch(pageSize, () => { page.value = 1; load() })
watch(page, () => { if (!props.id) load() })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">ASSET REGISTER</span><h2>{{ props.id ? '设备详情' : '设备资产' }}</h2><p>{{ props.id ? '设备资料、故障历史和诊断入口。' : '按组织范围查看现场设备资产。' }}</p></div><RouterLink v-if="props.id" class="button secondary" to="/devices">返回列表</RouterLink><RouterLink v-else class="button primary" to="/diagnosis">开始诊断</RouterLink></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} <button class="link-button" type="button" @click="load">重试</button></p>
    <div v-if="loading" class="loading-state" role="status">正在加载…</div>
    <template v-else-if="props.id && detail">
      <div class="detail-card"><div class="detail-title"><div><span class="eyebrow">{{ detail.code }} / {{ detail.model }}</span><h3>{{ detail.name }}</h3></div><span class="pill">可用</span></div><dl class="detail-grid"><div><dt>设备编号</dt><dd>{{ detail.code }}</dd></div><div><dt>型号</dt><dd>{{ detail.model }}</dd></div><div><dt>组织范围</dt><dd>{{ detail.organization_id || '未绑定' }}</dd></div><div><dt>元数据</dt><dd>{{ JSON.stringify(detail.metadata || {}) }}</dd></div></dl><h3 class="section-title">故障历史</h3><div v-for="row in history" :key="row.id" class="list-row static-row"><span class="severity-dot" :class="'severity-' + row.severity"></span><div><strong>{{ row.symptom }}</strong><small>{{ row.status }} · {{ new Date(row.created_at).toLocaleString('zh-CN') }}</small></div></div><div v-if="!history.length" class="empty-panel">该设备暂无故障历史。</div></div>
    </template>
    <template v-else>
      <div class="toolbar"><input v-model="query" placeholder="搜索设备编号、名称或型号" aria-label="搜索设备"></div>
      <div class="table-wrap"><table><thead><tr><th>设备</th><th>型号</th><th>组织</th><th>状态</th><th></th></tr></thead><tbody><tr v-for="device in rows" :key="device.id"><td><strong>{{ device.name }}</strong><small>{{ device.code }}</small></td><td>{{ device.model }}</td><td>{{ device.organization_id || '未绑定' }}</td><td><span class="pill pill-success">在线</span></td><td><RouterLink class="text-link" :to="'/devices/' + device.id">查看 →</RouterLink></td></tr><tr v-if="!rows.length"><td colspan="5" class="table-empty">{{ query ? '没有符合条件的设备。' : '暂无授权设备。' }}</td></tr></tbody></table></div>
      <PaginationControl v-if="total" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="total" :start="rangeStart" :end="rangeEnd" />
    </template>
  </section>
</template>
