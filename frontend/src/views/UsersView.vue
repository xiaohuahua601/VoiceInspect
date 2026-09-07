<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request, roleLabel, type User } from '../api'
import PaginationControl from '../components/PaginationControl.vue'

const rows = ref<User[]>([])
const query = ref('')
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const form = ref({ username: '', password: '', role: 'operator', organization_id: '' })
const filteredRows = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return rows.value
  return rows.value.filter((item) => (item.username + item.role + (item.organization_id || '') + (item.status || '')).toLowerCase().includes(keyword))
})
const pages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value)))
const pagedRows = computed(() => filteredRows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const rangeStart = computed(() => filteredRows.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, filteredRows.value.length))

async function load() {
  loading.value = true
  error.value = ''
  try { rows.value = await request<User[]>('/users') }
  catch (e) { error.value = e instanceof Error ? e.message : '用户加载失败' }
  finally { loading.value = false }
}
async function create() {
  error.value = ''; notice.value = ''
  try { await request('/users', { method: 'POST', body: JSON.stringify(form.value) }); notice.value = '用户已创建'; form.value = { username: '', password: '', role: 'operator', organization_id: '' }; page.value = 1; await load() }
  catch (e) { error.value = e instanceof Error ? e.message : '创建失败' }
}
async function toggle(item: User) {
  try { await request('/users/' + item.id, { method: 'PATCH', body: JSON.stringify({ status: item.status === 'active' ? 'disabled' : 'active' }) }); await load() }
  catch (e) { error.value = e instanceof Error ? e.message : '状态更新失败' }
}
watch(query, () => { page.value = 1 })
watch(pageSize, () => { page.value = 1 })
watch(pages, (value) => { if (page.value > value) page.value = value })
onMounted(load)
</script>

<template>
  <section class="page-view">
    <div class="page-heading"><div><span class="eyebrow">IDENTITY & ACCESS</span><h2>用户与权限</h2><p>管理账号角色和组织归属。服务端会继续执行角色与数据范围校验。</p></div></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p><p v-if="notice" class="inline-notice" role="status">{{ notice }}</p>
    <div class="split-layout">
      <section class="panel"><span class="eyebrow">CREATE ACCOUNT</span><h3>创建用户</h3><div class="form-grid single"><label>用户名<input v-model="form.username" autocomplete="off"></label><label>初始密码<input v-model="form.password" type="password" autocomplete="new-password"></label><label>角色<select v-model="form.role"><option value="operator">操作员</option><option value="maintenance_supervisor">维修主管</option><option value="knowledge_admin">知识管理员</option><option value="system_admin">系统管理员</option></select></label><label>组织 ID<input v-model="form.organization_id" placeholder="可留空使用默认范围"></label></div><button class="button primary" type="button" :disabled="!form.username || form.password.length < 8" @click="create">创建账号</button></section>
      <section class="panel"><span class="eyebrow">USER DIRECTORY</span><h3>账号目录</h3><div class="toolbar directory-toolbar"><input v-model="query" placeholder="搜索用户名、角色或组织" aria-label="搜索用户"></div><div v-for="item in pagedRows" :key="item.id" class="list-row static-row"><span class="avatar small">{{ item.username.slice(0,1).toUpperCase() }}</span><div><strong>{{ item.username }}</strong><small>{{ roleLabel(item.role) }} · {{ item.organization_id || '未绑定组织' }}</small></div><button class="text-button" type="button" @click="toggle(item)">{{ item.status === 'active' ? '停用' : '启用' }}</button></div><div v-if="!pagedRows.length" class="empty-panel">{{ rows.length ? '没有符合条件的用户。' : '暂无用户。' }}</div><PaginationControl v-if="filteredRows.length" v-model:page="page" v-model:page-size="pageSize" :pages="pages" :total="filteredRows.length" :start="rangeStart" :end="rangeEnd" /></section>
    </div>
  </section>
</template>