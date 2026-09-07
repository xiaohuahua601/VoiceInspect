<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type User = { id: string; username: string; role: string }
type Device = { id: string; code: string; model: string; name: string }
type Citation = { citation_id: string; document: string; version: string; page: number | null; section: string; quote_text: string; score: number }
type StageState = Record<string, string | number>
type Message = { id: string; role: 'user' | 'assistant'; text: string | null; status: string; citations: Citation[]; stage_states: StageState; created_at: string }
type Session = { id: string; title: string; status: string; device_id: string | null; created_at: string; messages?: Message[] }

const apiBase = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'
const token = ref(localStorage.getItem('voiceinspect_token') ?? '')
const user = ref<User | null>(JSON.parse(localStorage.getItem('voiceinspect_user') ?? 'null'))
const username = ref('operator')
const password = ref('change-me')
const loginError = ref('')
const isBusy = ref(false)
const sessions = ref<Session[]>([])
const activeSession = ref<Session | null>(null)
const devices = ref<Device[]>([])
const selectedDeviceId = ref('')
const question = ref('')
const errorMessage = ref('')
const notice = ref('')
const health = ref<{ status: string; database: boolean; ollama: { available: boolean; models?: string[]; reason?: string } } | null>(null)
const citationsOpen = ref<string | null>(null)

const isLoggedIn = computed(() => Boolean(token.value && user.value))

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  if (token.value) headers.set('Authorization', `Bearer ${token.value}`)
  const response = await fetch(`${apiBase}${path}`, { ...options, headers })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data?.error?.message ?? '服务暂时不可用')
  return data as T
}

async function login() {
  loginError.value = ''
  isBusy.value = true
  try {
    const result = await request<{ access_token: string; user: User }>('/auth/login', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
    token.value = result.access_token
    user.value = result.user
    localStorage.setItem('voiceinspect_token', result.access_token)
    localStorage.setItem('voiceinspect_user', JSON.stringify(result.user))
    await loadWorkspace()
  } catch (error) {
    loginError.value = error instanceof Error ? error.message : '登录失败'
  } finally {
    isBusy.value = false
  }
}

function logout() {
  token.value = ''
  user.value = null
  activeSession.value = null
  sessions.value = []
  localStorage.removeItem('voiceinspect_token')
  localStorage.removeItem('voiceinspect_user')
}

async function loadWorkspace() {
  const [sessionList, deviceList, healthResult] = await Promise.all([
    request<Session[]>('/sessions'),
    request<Device[]>('/devices'),
    request<typeof health.value>('/health'),
  ])
  sessions.value = sessionList
  devices.value = deviceList
  health.value = healthResult
  if (sessions.value.length) await selectSession(sessions.value[0].id)
  else await createSession()
}

async function createSession() {
  errorMessage.value = ''
  try {
    const session = await request<Session>('/sessions', { method: 'POST', body: JSON.stringify({ title: '新诊断会话', device_id: selectedDeviceId.value || null }) })
    sessions.value = [session, ...sessions.value]
    activeSession.value = { ...session, messages: [] }
    notice.value = '已创建新的诊断会话'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建会话失败'
  }
}

async function selectSession(id: string) {
  try {
    activeSession.value = await request<Session>(`/sessions/${id}`)
    selectedDeviceId.value = activeSession.value.device_id ?? ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取会话失败'
  }
}

async function sendQuestion() {
  const text = question.value.trim()
  if (!text || !activeSession.value || isBusy.value) return
  isBusy.value = true
  errorMessage.value = ''
  notice.value = ''
  const optimistic: Message = { id: `local-${Date.now()}`, role: 'user', text, status: 'completed', citations: [], stage_states: { input: 'succeeded' }, created_at: new Date().toISOString() }
  activeSession.value.messages = [...(activeSession.value.messages ?? []), optimistic]
  question.value = ''
  try {
    const result = await request<{ message: Message }>('/messages', { method: 'POST', body: JSON.stringify({ session_id: activeSession.value.id, text, device_id: selectedDeviceId.value || null }) })
    activeSession.value.messages = [...(activeSession.value.messages ?? []).filter((item) => item.id !== optimistic.id), optimistic, result.message]
    notice.value = '诊断回答已保存，可展开查看资料依据'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '诊断失败'
    notice.value = '问题已保留，请修复服务状态后重试'
  } finally {
    isBusy.value = false
  }
}

function stageLabel(stage: string) { return ({ stt: '语音转写', vision: '图片观察', rag: '资料检索', llm: '回答生成', tts: '语音播报' } as Record<string, string>)[stage] ?? stage }
function statusLabel(status: string | number) { return ({ pending: '排队', running: '处理中', succeeded: '完成', partial: '部分完成', failed: '失败', skipped: '未启用', needs_review: '待确认' } as Record<string, string>)[String(status)] ?? String(status) }
function stageEntries(states: StageState) { return Object.entries(states).filter(([stage, status]) => ['stt', 'vision', 'rag', 'llm', 'tts'].includes(stage) && typeof status === 'string') as [string, string][] }
function statusTone(status: string | number) { if (status === 'succeeded') return 'success'; if (status === 'failed') return 'danger'; if (status === 'partial' || status === 'needs_review') return 'warning'; if (status === 'running') return 'running'; return 'neutral' }

onMounted(async () => {
  if (!isLoggedIn.value) return
  try { await loadWorkspace() } catch (error) { errorMessage.value = error instanceof Error ? error.message : '无法连接服务' }
})
</script>

<template>
  <main class="app-shell">
    <section v-if="!isLoggedIn" class="login-stage">
      <div class="login-copy"><div class="login-mark"><span class="pulse-dot" aria-hidden="true"></span><span>VOICEINSPECT</span></div><p class="eyebrow">LOCAL FIELD DIAGNOSTICS / 01</p><h1>让每一次判断<br /><em>都有依据。</em></h1><p>在设备旁用语音、图片和本地手册，形成可追溯的诊断记录。</p></div>
      <form class="login-form" novalidate @submit.prevent="login"><label for="username">账号</label><input id="username" v-model="username" autocomplete="username" placeholder="输入账号" /><label for="password">密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" placeholder="输入密码" /><p v-if="loginError" class="inline-error" role="alert">{{ loginError }}</p><button class="button primary full" type="submit" :disabled="isBusy" :aria-busy="isBusy">{{ isBusy ? '正在验证…' : '进入工作台' }}</button><p class="login-hint">演示账号：operator / change-me</p></form>
    </section>

    <section v-else class="workspace">
      <aside class="sidebar" aria-label="工作区导航"><div class="brand"><span class="pulse-dot" aria-hidden="true"></span><span>VOICE<br />INSPECT</span></div><div class="sidebar-section"><p class="eyebrow">现场工作台</p><button class="nav-item active" type="button" disabled aria-current="page"><span>⌁</span> 诊断会话</button></div><div class="sidebar-section session-section"><div class="section-heading"><p class="eyebrow">最近会话</p><button class="icon-button" type="button" aria-label="创建新会话" @click="createSession">＋</button></div><button v-for="session in sessions" :key="session.id" class="session-item" :class="{ selected: activeSession?.id === session.id }" type="button" @click="selectSession(session.id)"><span class="session-mark">{{ session.title.slice(0, 1) }}</span><span><strong>{{ session.title }}</strong><small>{{ new Date(session.created_at).toLocaleDateString('zh-CN') }}</small></span></button></div><div class="sidebar-footer"><div class="user-chip"><span class="avatar">{{ user?.username.slice(0, 1).toUpperCase() }}</span><span><strong>{{ user?.username }}</strong><small>{{ user?.role === 'system_admin' ? '系统管理员' : '现场操作员' }}</small></span></div><button class="logout-button" type="button" @click="logout">退出</button></div></aside>
      <section class="main-panel"><header class="topbar"><div><p class="eyebrow">DIAGNOSIS SESSION</p><h2>{{ activeSession?.title ?? '诊断会话' }}</h2></div><div class="topbar-actions"><div class="health-chip" :class="health?.status === 'ok' ? 'is-ok' : 'is-degraded'"><span class="status-dot"></span><span>{{ health?.status === 'ok' ? '本地服务正常' : '服务需检查' }}</span></div><button class="button secondary" type="button" @click="loadWorkspace">刷新状态</button></div></header><div class="context-strip"><div><span class="strip-label">当前设备</span><select v-model="selectedDeviceId" aria-label="选择当前设备"><option value="">未选择设备</option><option v-for="device in devices" :key="device.id" :value="device.id">{{ device.name }} · {{ device.model }}</option></select></div><div class="strip-note"><span class="status-dot is-ok"></span><span>默认本地处理 · 不上传云端</span></div></div>
        <div class="timeline" aria-live="polite"><div v-if="!activeSession?.messages?.length" class="empty-state"><div class="empty-orbit"><span></span><span></span><span></span></div><p class="eyebrow">READY FOR INPUT</p><h3>从现场现象开始</h3><p>描述报警、设备状态或想确认的手册条目。语音和图片能力会在本地模型就绪后加入当前会话。</p><div class="quick-prompts"><button type="button" @click="question = '空压机 A-01 出现压力波动，应该先检查什么？'">压力波动怎么查？</button><button type="button" @click="question = '请根据当前设备手册说明报警含义。'">解释设备报警</button></div></div><template v-for="message in activeSession?.messages" :key="message.id"><article v-if="message.role === 'user'" class="message user-message"><div class="message-meta"><span class="mini-avatar">{{ user?.username.slice(0, 1).toUpperCase() }}</span><span>你 · {{ new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span></div><p>{{ message.text }}</p></article><article v-else class="answer-block"><div class="answer-head"><div><p class="eyebrow signal-label">ASSISTED FINDING</p><h3>诊断建议</h3></div><span class="verified-stamp">● {{ message.status === 'completed' ? '已保存' : '部分完成' }}</span></div><p class="answer-text">{{ message.text }}</p><div class="stage-row"><span v-for="item in stageEntries(message.stage_states)" :key="item[0]" class="stage-chip" :class="`tone-${statusTone(item[1])}`"><span class="chip-dot"></span>{{ stageLabel(item[0]) }} · {{ statusLabel(item[1]) }}</span><span v-if="message.stage_states.completed_ms" class="latency">{{ message.stage_states.completed_ms }} ms</span></div><div v-if="message.citations?.length" class="evidence-section"><div class="evidence-heading"><span class="evidence-icon">⌁</span><div><p class="eyebrow">资料依据</p><strong>{{ message.citations.length }} 条相关片段</strong></div></div><button v-for="citation in message.citations" :key="citation.citation_id" class="citation-row" type="button" @click="citationsOpen = citationsOpen === citation.citation_id ? null : citation.citation_id"><span class="citation-index">{{ message.citations.indexOf(citation) + 1 }}</span><span><strong>{{ citation.document }}</strong><small>{{ citation.section }} · 相关度 {{ citation.score }}</small></span><span class="citation-arrow">{{ citationsOpen === citation.citation_id ? '−' : '+' }}</span><p v-if="citationsOpen === citation.citation_id" class="citation-quote">{{ citation.quote_text }}</p></button></div><div v-else class="degraded-note"><span>!</span><span>当前没有检索到可绑定的手册依据，请补充设备型号或联系知识库管理员。</span></div></article></template><p v-if="errorMessage" class="inline-error workspace-error" role="alert">{{ errorMessage }}</p><p v-if="notice" class="inline-notice" role="status">{{ notice }}</p></div>
        <form class="composer" novalidate @submit.prevent="sendQuestion"><textarea class="resize-none" v-model="question" rows="2" :disabled="isBusy" placeholder="描述设备现象… Enter 发送，Shift + Enter 换行" aria-label="诊断问题"></textarea><div class="composer-actions"><div class="composer-tools"><button type="button" class="tool-button" disabled title="语音能力将在本地 STT 就绪后启用">◉ <span>语音</span></button><button type="button" class="tool-button" disabled title="视觉能力将在本地 VLM 就绪后启用">▧ <span>图片</span></button></div><button class="button primary" type="submit" :disabled="isBusy || !question.trim()" :aria-busy="isBusy">{{ isBusy ? '正在分析…' : '开始诊断' }} <span aria-hidden="true">→</span></button></div></form>
      </section>
    </section>
  </main>
</template>
