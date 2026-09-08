<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { renderMarkdown } from '../utils/markdown'
import { getDevicePrompts, getDeviceTypeLabel } from '../utils/devicePrompts'

type User = { id: string; username: string; role: string }
type Device = { id: string; code: string; model: string; name: string; metadata?: Record<string, unknown> }
type Citation = { citation_id: string; document: string; version: string; page: number | null; section: string; quote_text: string; score: number }
type StageState = Record<string, string | number>
type Message = { id: string; role: 'user' | 'assistant'; text: string | null; status: string; citations: Citation[]; stage_states: StageState; observations?: Record<string, unknown>; created_at: string }
type Session = { id: string; title: string; status: string; device_id: string | null; created_at: string; messages?: Message[] }

const apiBase = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'
const token = ref(localStorage.getItem('voiceinspect_token') ?? '')
const user = ref<User | null>(JSON.parse(localStorage.getItem('voiceinspect_user') ?? 'null'))
const username = ref('operator')
const password = ref('change-me')
const loginError = ref('')
const isBusy = ref(false)
const loadingStageIndex = ref(0)
const loadingStages = [
  '正在读取当前设备上下文',
  '正在检索已发布知识',
  '正在整理可验证的诊断建议',
]
const sessions = ref<Session[]>([])
const activeSession = ref<Session | null>(null)
const devices = ref<Device[]>([])
const selectedDeviceId = ref('')
const question = ref('')
const errorMessage = ref('')
const notice = ref('')
const health = ref<{ status: string; database: boolean; ollama: { available: boolean; models?: string[]; reason?: string } } | null>(null)
const citationsOpen = ref<string | null>(null)
const capabilities = ref<Record<string, any>>({})
const audioAssetId = ref('')
const imageAssetId = ref('')
const uploadState = ref('')
const recording = ref(false)
const recordSeconds = ref(0)
const imageInput = ref<HTMLInputElement | null>(null)
const faultDraft = ref<any>(null)
const faultDialogOpen = ref(false)
const historyOpen = ref(false)
const auditOpen = ref(false)
const historyRecords = ref<any[]>([])
const auditEvents = ref<any[]>([])
const speakingId = ref('' )
let activeAudio: HTMLAudioElement | null = null
let activeAudioUrl = ''
let recorder: MediaRecorder | null = null
let recorderStream: MediaStream | null = null
let recorderChunks: Blob[] = []
let recordTimer: number | undefined
let loadingStageTimer: number | undefined
let streamingController: AbortController | null = null
const streamingText = ref('')
const streamingStageStates = ref<StageState>({ llm: 'running' })

const isLoggedIn = computed(() => Boolean(token.value && user.value))
const activeDevice = computed(() => devices.value.find((device) => device.id === selectedDeviceId.value))
const canSend = computed(() => Boolean(question.value.trim() || audioAssetId.value || imageAssetId.value))
const quickPrompts = computed(() => getDevicePrompts(activeDevice.value))
const deviceTypeLabel = computed(() => getDeviceTypeLabel(activeDevice.value))
const emptyStateTitle = computed(() => activeDevice.value ? `从${activeDevice.value.name}开始` : '从现场现象开始')
const emptyStateDescription = computed(() => activeDevice.value ? `描述${activeDevice.value.name}的报警、状态或想确认的资料条目。示例问题已按当前设备调整；也可以录音或附加现场图片。` : '描述报警、设备状态或想确认的手册条目。可以直接输入文字，也可以录音或附加现场图片。')

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
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
  const [sessionList, deviceList, healthResult, capabilityResult] = await Promise.all([
    request<Session[]>('/sessions'),
    request<Device[]>('/devices'),
    request<typeof health.value>('/health'),
    request<Record<string, any>>('/capabilities'),
  ])
  sessions.value = sessionList
  devices.value = deviceList
  health.value = healthResult
  capabilities.value = capabilityResult
  if (sessions.value.length) await selectSession(sessions.value[0].id)
  else await createSession()
}

async function changeDevice() {
  if (!activeSession.value) return
  const previous = activeSession.value.device_id
  if (previous === selectedDeviceId.value) return
  errorMessage.value = ''
  try {
    const updated = await request<Session>(`/sessions/${activeSession.value.id}`, { method: 'PATCH', body: JSON.stringify({ device_id: selectedDeviceId.value || null }) })
    activeSession.value = { ...activeSession.value, ...updated }
    sessions.value = sessions.value.map((session) => session.id === updated.id ? { ...session, device_id: updated.device_id } : session)
    notice.value = `已切换当前设备：${activeDevice.value?.name ?? '未选择设备'}，示例问题已更新`
  } catch (error) {
    selectedDeviceId.value = previous ?? ''
    errorMessage.value = error instanceof Error ? error.message : '当前设备切换失败'
  }
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


async function showHistory() {
  if (!selectedDeviceId.value) return
  try {
    const result = await request<{ records: any[] }>('/devices/' + selectedDeviceId.value + '/history')
    historyRecords.value = result.records
    historyOpen.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取设备历史失败'
  }
}

async function showAudit() {
  try {
    auditEvents.value = await request<any[]>('/audit-events')
    auditOpen.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取审计记录失败'
  }
}

function stopAudio() {
  activeAudio?.pause()
  activeAudio = null
  if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl)
  activeAudioUrl = ''
  speakingId.value = ''
}

async function playAnswer(message: Message) {
  if (speakingId.value === message.id) {
    stopAudio()
    return
  }
  if (!message.text || capabilities.value.tts?.available === false) return
  stopAudio()
  speakingId.value = message.id
  try {
    const response = await fetch(apiBase + '/tts', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token.value, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: message.text }),
    })
    if (!response.ok) throw new Error('语音播报暂不可用')
    activeAudioUrl = URL.createObjectURL(await response.blob())
    activeAudio = new Audio(activeAudioUrl)
    activeAudio.onended = stopAudio
    await activeAudio.play()
  } catch (error) {
    stopAudio()
    errorMessage.value = error instanceof Error ? error.message : '语音播报失败'
  }
}
async function uploadAsset(file: File, kind: 'audio' | 'image') {
  const form = new FormData()
  form.append('file', file)
  form.append('kind', kind)
  if (activeSession.value) form.append('session_id', activeSession.value.id)
  uploadState.value = kind === 'audio' ? '正在转存音频…' : '正在转存图片…'
  try {
    const result = await request<{ id: string }>('/assets', { method: 'POST', body: form })
    if (kind === 'audio') audioAssetId.value = result.id
    else imageAssetId.value = result.id
    uploadState.value = kind === 'audio' ? '语音已就绪，可编辑补充文字' : '图片已就绪，可开始诊断'
  } catch (error) {
    uploadState.value = error instanceof Error ? error.message : '附件上传失败'
  }
}

async function chooseImage(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) await uploadAsset(file, 'image')
  ;(event.target as HTMLInputElement).value = ''
}

async function toggleRecording() {
  if (recording.value) {
    recorder?.stop()
    recorderStream?.getTracks().forEach((track) => track.stop())
    recording.value = false
    if (recordTimer) window.clearInterval(recordTimer)
    return
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    uploadState.value = '当前浏览器不支持本地录音，请直接输入文字'
    return
  }
  try {
    recorderStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    recorderChunks = []
    recorder = new MediaRecorder(recorderStream)
    recorder.ondataavailable = (event) => { if (event.data.size) recorderChunks.push(event.data) }
    recorder.onstop = async () => {
      const blob = new Blob(recorderChunks, { type: recorder?.mimeType || 'audio/webm' })
      await uploadAsset(new File([blob], '现场录音.webm', { type: blob.type }), 'audio')
    }
    recorder.start()
    recordSeconds.value = 0
    recording.value = true
    recordTimer = window.setInterval(() => { recordSeconds.value += 1 }, 1000)
  } catch {
    uploadState.value = '无法访问麦克风，请检查浏览器权限'
  }
}

async function createFaultDraft(message: Message) {
  if (!activeSession.value || !selectedDeviceId.value || !message.text) {
    errorMessage.value = '请先选择设备，且诊断结果必须包含故障描述'
    return
  }
  try {
    faultDraft.value = await request('/tool-drafts', {
      method: 'POST',
      body: JSON.stringify({
        session_id: activeSession.value.id,
        tool_name: 'create_fault_record',
        arguments: {
          device_id: selectedDeviceId.value,
          symptom: message.text.slice(0, 2000),
          severity: 'medium',
          idempotency_key: activeSession.value.id + '-' + message.id,
        },
      }),
    })
    faultDialogOpen.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '无法创建故障记录草稿'
  }
}

async function confirmFault() {
  if (!faultDraft.value?.confirmation_token) return
  try {
    const result = await request<{ status?: string }>('/confirmations/' + faultDraft.value.confirmation_token, { method: 'POST' })
    faultDialogOpen.value = false
    notice.value = result.status === 'already_exists' ? '故障记录已存在，未重复创建' : '故障记录已创建并写入审计'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障记录确认失败'
  }
}

function startLoadingProgress() {
  if (loadingStageTimer !== undefined) window.clearInterval(loadingStageTimer)
  loadingStageIndex.value = 0
  loadingStageTimer = window.setInterval(() => {
    loadingStageIndex.value = (loadingStageIndex.value + 1) % loadingStages.length
  }, 1200)
}

function stopLoadingProgress() {
  if (loadingStageTimer !== undefined) window.clearInterval(loadingStageTimer)
  loadingStageTimer = undefined
  loadingStageIndex.value = 0
}

const loadingStage = computed(() => loadingStages[loadingStageIndex.value])

async function streamDiagnosis(payload: Record<string, unknown>, onEvent: (event: Record<string, any>) => void) {
  const controller = new AbortController()
  streamingController = controller
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (token.value) headers.set('Authorization', `Bearer ${token.value}`)
  const response = await fetch(`${apiBase}/messages/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data?.error?.message ?? '流式诊断请求失败')
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('当前浏览器不支持流式响应')
  const decoder = new TextDecoder()
  let buffer = ''
  const consume = (flush = false) => {
    if (flush) buffer += decoder.decode()
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    if (flush && buffer.trim()) {
      frames.push(buffer)
      buffer = ''
    }
    for (const frame of frames) {
      const data = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))?.slice(5) ?? ''
      const normalized = data.trim()
      if (!normalized) continue
      if (normalized === '[DONE]' || normalized.startsWith('[DONE]')) {
        continue
      }
      try {
        onEvent(JSON.parse(normalized) as Record<string, any>)
      } catch (error) {
        if (normalized.includes('[DONE]')) {
          continue
        }
        throw error
      }
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    consume()
  }
  consume(true)
}

function stopStreaming() {
  streamingController?.abort()
}

async function sendQuestion() {
  const text = question.value.trim()
  if (!canSend.value || !activeSession.value || isBusy.value) return
  isBusy.value = true
  startLoadingProgress()
  streamingText.value = ''
  streamingStageStates.value = { llm: 'running' }
  errorMessage.value = ''
  notice.value = ''
  const optimistic: Message = { id: `local-${Date.now()}`, role: 'user', text: text || '已上传现场图片，请分析设备状态。', status: 'completed', citations: [], stage_states: { input: 'succeeded' }, created_at: new Date().toISOString() }
  activeSession.value.messages = [...(activeSession.value.messages ?? []), optimistic]
  question.value = ''
  let completed = false
  try {
    await streamDiagnosis({
      session_id: activeSession.value.id,
      text,
      audio_asset_id: audioAssetId.value || null,
      image_asset_id: imageAssetId.value || null,
    }, (event) => {
      if (event.type === 'start') {
        streamingStageStates.value = event.stage_states ?? { llm: 'running' }
      } else if (event.type === 'chunk') {
        streamingText.value += String(event.content ?? '')
      } else if (event.type === 'complete' && event.message) {
        activeSession.value!.messages = [...(activeSession.value!.messages ?? []).filter((item) => item.id !== optimistic.id), optimistic, event.message as Message]
        completed = true
      } else if (event.type === 'error') {
        throw new Error(event.error?.message ?? '诊断回答生成失败，请重试')
      }
    })
    if (!completed) throw new Error('回答流未正常结束，请重试')
    notice.value = '诊断回答已保存，可展开查看资料依据'
    audioAssetId.value = ''
    imageAssetId.value = ''
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      question.value = text
      notice.value = '已停止生成，问题仍保留在输入框中'
    } else {
      errorMessage.value = error instanceof Error ? error.message : '诊断失败'
      notice.value = '问题已保留，请修复服务状态后重试'
    }
  } finally {
    streamingController = null
    streamingText.value = ''
    streamingStageStates.value = { llm: 'running' }
    stopLoadingProgress()
    isBusy.value = false
  }
}
onBeforeUnmount(() => {
  streamingController?.abort()
  stopLoadingProgress()
})

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
      <aside class="sidebar" aria-label="工作区导航"><div class="brand"><span class="pulse-dot" aria-hidden="true"></span><span>VOICE<br />INSPECT</span></div><div class="sidebar-section"><p class="eyebrow">现场工作台</p><button class="nav-item active" type="button" disabled aria-current="page"><span>⌁</span> 诊断会话</button></div><div class="sidebar-section session-section"><div class="section-heading"><p class="eyebrow">最近会话</p><button class="icon-button" type="button" aria-label="创建新会话" @click="createSession">＋</button></div><div class="session-list" role="list"><button v-for="session in sessions" :key="session.id" class="session-item" :class="{ selected: activeSession?.id === session.id }" type="button" @click="selectSession(session.id)"><span class="session-mark">{{ session.title.slice(0, 1) }}</span><span><strong>{{ session.title }}</strong><small>{{ new Date(session.created_at).toLocaleDateString('zh-CN') }}</small></span></button></div></div></aside>
      <section class="main-panel"><header class="topbar"><div><p class="eyebrow">DIAGNOSIS SESSION</p><h2>{{ activeSession?.title ?? '诊断会话' }}</h2></div><div class="topbar-actions"><div class="health-chip" :class="health?.status === 'ok' ? 'is-ok' : 'is-degraded'"><span class="status-dot"></span><span>{{ health?.status === 'ok' ? '本地服务正常' : '服务需检查' }}</span></div><button class="button secondary" type="button" @click="loadWorkspace">刷新状态</button></div></header><div class="context-strip"><div><span class="strip-label">当前设备</span><select v-model="selectedDeviceId" aria-label="选择当前设备" @change="changeDevice"><option value="">未选择设备</option><option v-for="device in devices" :key="device.id" :value="device.id">{{ device.name }} · {{ device.model }}</option></select><div class="context-actions"><button class="button secondary" type="button" :disabled="!selectedDeviceId" @click="showHistory">设备历史</button><button class="button secondary" type="button" @click="showAudit">审计记录</button></div></div><div class="strip-note"><span class="status-dot is-ok"></span><span>当前：{{ activeDevice?.name || '未选择设备' }} · 示例问题已适配</span></div></div>
        <input ref="imageInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" @change="chooseImage" /><div class="timeline" aria-live="polite"><div v-if="!activeSession?.messages?.length" class="empty-state"><div class="empty-orbit"><span></span><span></span><span></span></div><p class="eyebrow">READY FOR {{ deviceTypeLabel.toUpperCase() }}</p><h3>{{ emptyStateTitle }}</h3><p>{{ emptyStateDescription }}</p><div class="quick-prompts" aria-label="当前设备示例问题"><button v-for="prompt in quickPrompts" :key="prompt" type="button" @click="question = prompt">{{ prompt }}</button></div></div><template v-for="message in activeSession?.messages" :key="message.id"><article v-if="message.role === 'user'" class="message user-message"><div class="message-meta"><span class="mini-avatar">{{ user?.username.slice(0, 1).toUpperCase() }}</span><span>你 · {{ new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span></div><p>{{ message.text }}</p></article><article v-else class="answer-block"><div class="answer-head"><div><p class="eyebrow signal-label">ASSISTED FINDING</p><h3>诊断建议</h3></div><span class="verified-stamp">● {{ message.status === 'completed' ? '已保存' : '部分完成' }}</span></div><div class="answer-text answer-markdown" v-html="renderMarkdown(message.text)"></div><div class="stage-row"><span v-for="item in stageEntries(message.stage_states)" :key="item[0]" class="stage-chip" :class="`tone-${statusTone(item[1])}`"><span class="chip-dot"></span>{{ stageLabel(item[0]) }} · {{ statusLabel(item[1]) }}</span><span v-if="message.stage_states.completed_ms" class="latency">{{ message.stage_states.completed_ms }} ms</span></div><div v-if="message.citations?.length" class="evidence-section"><div class="evidence-heading"><span class="evidence-icon">⌁</span><div><p class="eyebrow">资料依据</p><strong>{{ message.citations.length }} 条相关片段</strong></div></div><button v-for="citation in message.citations" :key="citation.citation_id" class="citation-row" type="button" @click="citationsOpen = citationsOpen === citation.citation_id ? null : citation.citation_id"><span class="citation-index">{{ message.citations.indexOf(citation) + 1 }}</span><span><strong>{{ citation.document }}</strong><small>{{ citation.section }} · 相关度 {{ citation.score }}</small></span><span class="citation-arrow">{{ citationsOpen === citation.citation_id ? '−' : '+' }}</span><p v-if="citationsOpen === citation.citation_id" class="citation-quote">{{ citation.quote_text }}</p></button></div><div v-else class="degraded-note"><span>!</span><span>当前没有检索到可绑定的手册依据，请补充设备型号或联系知识库管理员。</span></div><div v-if="message.text && selectedDeviceId" class="answer-actions"><button class="button secondary" type="button" :disabled="capabilities.tts?.available === false" @click="playAnswer(message)">{{ speakingId === message.id ? '停止播报' : '播报建议' }}</button><button class="button secondary" type="button" @click="createFaultDraft(message)">确认创建故障记录</button></div></article></template><article v-if="isBusy && streamingText" class="answer-block streaming-answer" role="status" aria-live="polite" aria-label="正在流式生成诊断回复"><div class="answer-head"><div><p class="eyebrow signal-label">ASSISTED FINDING · GENERATING</p><h3>诊断建议</h3></div><span class="streaming-label"><span class="streaming-pulse" aria-hidden="true"></span>实时生成</span></div><div class="answer-text answer-markdown" v-html="renderMarkdown(streamingText)"></div><div class="streaming-cursor" aria-hidden="true"></div><div class="stage-row"><span v-for="item in stageEntries(streamingStageStates)" :key="item[0]" class="stage-chip" :class="`tone-${statusTone(item[1])}`"><span class="chip-dot"></span>{{ stageLabel(item[0]) }} · {{ statusLabel(item[1]) }}</span></div></article><article v-if="isBusy && !streamingText" class="model-progress" role="status" aria-live="polite" aria-label="正在生成诊断回复"><div class="model-progress-head"><span class="model-progress-orbit" aria-hidden="true"><span></span></span><div class="model-progress-copy"><strong>正在生成诊断回复</strong><small>{{ loadingStage }}</small></div></div><div class="model-progress-track" aria-hidden="true"><span></span></div><div class="model-progress-device">当前设备：{{ activeDevice?.name || "未选择设备" }} · 正在基于本次会话证据处理</div></article><p v-if="errorMessage" class="inline-error workspace-error" role="alert">{{ errorMessage }}</p><p v-if="notice" class="inline-notice" role="status">{{ notice }}</p></div>
        <form class="composer" novalidate @submit.prevent="sendQuestion"><div class="composer-entry"><textarea class="resize-none" v-model="question" rows="2" :disabled="isBusy" :placeholder="`描述${activeDevice?.name || '当前设备'}现象… 也可以只发送图片，Enter 发送，Shift + Enter 换行`" aria-label="诊断问题"></textarea><button v-if="!isBusy" class="button primary composer-submit" type="submit" :disabled="!canSend" :aria-label="imageAssetId && !question.trim() ? '发送图片并开始诊断' : '开始诊断'">{{ imageAssetId && !question.trim() ? '发送图片' : '开始诊断' }} <span aria-hidden="true">→</span></button><button v-else class="button secondary composer-submit" type="button" aria-label="停止生成诊断回答" @click="stopStreaming">停止生成 <span aria-hidden="true">×</span></button></div><div v-if="uploadState" class="upload-state" role="status">{{ uploadState }}</div><div class="composer-actions"><div class="composer-tools"><button type="button" class="input-tool-button" :class="{ recording }" :disabled="isBusy || capabilities.stt?.available === false" :title="capabilities.stt?.available === false ? '本地 STT 未安装' : '录制现场语音'" @click="toggleRecording"><span class="tool-icon" aria-hidden="true">◉</span><span>{{ recording ? '停止录音' : '语音输入' }}<small v-if="recording">{{ recordSeconds }}s</small></span></button><button type="button" class="input-tool-button" :disabled="isBusy || capabilities.vision?.available === false" :title="capabilities.vision?.available === false ? '本地 VLM 未配置' : '附加现场图片'" @click="imageInput?.click()"><span class="tool-icon" aria-hidden="true">▧</span><span>添加图片</span></button></div><div v-if="audioAssetId || imageAssetId" class="attachment-badges"><span v-if="audioAssetId" class="attachment-badge">语音待发送</span><span v-if="imageAssetId" class="attachment-badge">图片待发送</span></div></div></form><div v-if="faultDialogOpen" class="dialog-backdrop" role="presentation"><section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="fault-title"><p class="eyebrow">CONTROLLED WRITE</p><h3 id="fault-title">确认创建故障记录？</h3><p>这会写入设备历史并记录审计信息。重复确认不会重复创建。</p><div class="dialog-actions"><button class="button secondary" type="button" @click="faultDialogOpen = false">取消</button><button class="button primary" type="button" @click="confirmFault">确认写入</button></div></section></div><div v-if="historyOpen || auditOpen" class="dialog-backdrop" role="presentation"><section class="confirm-dialog records-dialog" role="dialog" aria-modal="true" :aria-labelledby="historyOpen ? 'history-title' : 'audit-title'"><p class="eyebrow">{{ historyOpen ? 'DEVICE HISTORY' : 'AUDIT TRAIL' }}</p><h3 :id="historyOpen ? 'history-title' : 'audit-title'">{{ historyOpen ? '设备故障历史' : '审计记录' }}</h3><div v-if="historyOpen && !historyRecords.length" class="degraded-note"><span>!</span><span>当前设备暂无故障记录。</span></div><div v-if="historyOpen" class="record-list"><article v-for="record in historyRecords" :key="record.id" class="record-row"><strong>{{ record.symptom }}</strong><small>{{ record.severity }} · {{ record.status }} · {{ new Date(record.created_at).toLocaleString('zh-CN') }}</small></article></div><div v-if="auditOpen && !auditEvents.length" class="degraded-note"><span>!</span><span>当前账号暂无审计事件。</span></div><div v-if="auditOpen" class="record-list"><article v-for="event in auditEvents" :key="event.id" class="record-row"><strong>{{ event.action }}</strong><small>{{ event.target }} · {{ new Date(event.created_at).toLocaleString('zh-CN') }}</small></article></div><div class="dialog-actions"><button class="button primary" type="button" @click="historyOpen = false; auditOpen = false">关闭</button></div></section></div>
      </section>
    </section>
  </main>
</template>
