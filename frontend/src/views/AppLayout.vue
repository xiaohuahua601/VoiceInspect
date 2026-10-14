<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { clearAuth, getStoredUser, request, roleLabel } from '../api'
import BrandLogo from '../components/BrandLogo.vue'

const router = useRouter()
const route = useRoute()
const user = computed(() => getStoredUser())
const notifications = ref<any[]>([])
const notificationsOpen = ref(false)
const notificationMenu = ref<HTMLElement | null>(null)
const notificationBusy = ref(false)
const notificationError = ref('')
const notificationNotice = ref('')
const unreadCount = computed(() => notifications.value.filter(item => !item.read).length)
async function loadNotifications() {
  notificationError.value = ''
  try {
    const data = await request<any[] | { items: any[] }>('/notifications')
    notifications.value = Array.isArray(data) ? data : data.items
  } catch (error) {
    notifications.value = []
    notificationError.value = error instanceof Error ? error.message : '通知加载失败，请重试'
  }
}
async function markNotification(item: any) {
  notificationError.value = ''
  notificationNotice.value = ''
  if (!item.read) {
    try {
      await request(`/notifications/${item.id}/read`, { method: 'POST' })
      item.read = true
    } catch (error) {
      notificationError.value = error instanceof Error ? error.message : '通知状态更新失败，请重试'
      return
    }
  }
  notificationsOpen.value = false
  if (item.target_type === 'fault' && item.target_id) {
    await router.push(`/faults/${encodeURIComponent(item.target_id)}`)
  } else {
    notificationNotice.value = '这条通知没有可定位的处理页面'
  }
}
async function markAllNotificationsRead() {
  if (!unreadCount.value || notificationBusy.value) return
  notificationBusy.value = true
  notificationError.value = ''
  notificationNotice.value = ''
  const count = unreadCount.value
  try {
    await request('/notifications/read-all', { method: 'POST' })
    notifications.value.forEach(item => { item.read = true })
    notificationNotice.value = `已将 ${count} 条通知标记为已读`
  } catch (error) {
    notificationError.value = error instanceof Error ? error.message : '批量标记失败，请重试'
  } finally {
    notificationBusy.value = false
  }
}
function closeNotificationsOnOutsidePointer(event: PointerEvent) {
  if (!notificationsOpen.value) return
  const target = event.target
  if (target instanceof Node && !notificationMenu.value?.contains(target)) {
    notificationsOpen.value = false
  }
}
function closeNotificationsOnEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && notificationsOpen.value) {
    notificationsOpen.value = false
  }
}

const nav = [
  { path: '/dashboard', label: '运营总览', icon: '⌂' },
  { path: '/diagnosis', label: '多模态诊断', icon: '⌁' },
  { path: '/sessions', label: '诊断会话', icon: '◷' },
  { path: '/faults', label: '故障闭环', icon: '!' },
  { path: '/devices', label: '设备资产', icon: '▣' },
  { path: '/knowledge', label: '知识库', icon: '▤' },
  { path: '/reports', label: '报告中心', icon: '↗' },
  { path: '/audit', label: '审计追踪', icon: '⌕' },
  { path: '/account', label: '账号安全', icon: '◉' },
]
const adminNav = [
  { path: '/users', label: '用户与权限', icon: '◎' },
  { path: '/settings', label: '系统设置', icon: '⚙' },
]
async function logout() {
  try { await request('/auth/logout', { method: 'POST' }) } catch { /* local logout still clears a failed network session */ }
  clearAuth(); router.replace('/login')
}
watch(notificationsOpen, open => { if (open) loadNotifications() })
onMounted(() => {
  loadNotifications()
  document.addEventListener('pointerdown', closeNotificationsOnOutsidePointer)
  document.addEventListener('keydown', closeNotificationsOnEscape)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeNotificationsOnOutsidePointer)
  document.removeEventListener('keydown', closeNotificationsOnEscape)
})
</script>

<template>
  <div class="admin-shell" :class="{ 'is-diagnosis': route.path === '/diagnosis' }">
    <aside class="admin-sidebar">
      <RouterLink class="admin-brand" to="/dashboard" aria-label="VoiceInspect 运营总览"><BrandLogo /></RouterLink>
      <div class="scope-card"><span class="eyebrow">CURRENT SCOPE</span><strong>{{ user?.organization_id ? '演示制造集团' : '默认组织' }}</strong><small>组织级数据范围</small></div>
      <nav class="admin-nav" aria-label="后台导航">
        <span class="nav-group-label">工作台</span>
        <RouterLink v-for="item in nav" :key="item.path" :to="item.path" class="admin-nav-item"><span>{{ item.icon }}</span>{{ item.label }}</RouterLink>
        <template v-if="user?.role === 'system_admin'">
          <span class="nav-group-label admin-group">管理</span>
          <RouterLink v-for="item in adminNav" :key="item.path" :to="item.path" class="admin-nav-item"><span>{{ item.icon }}</span>{{ item.label }}</RouterLink>
        </template>
      </nav>
      <div class="admin-user"><span class="avatar">{{ user?.username?.slice(0, 1).toUpperCase() }}</span><div><strong>{{ user?.username }}</strong><small>{{ roleLabel(user?.role) }}</small></div><button class="logout-button" type="button" @click="logout">退出</button></div>
    </aside>
    <main class="admin-main">
      <header class="admin-topbar">
        <div><span class="eyebrow">VOICEINSPECT / OPERATIONS</span><h1>工业设备智能诊断后台</h1></div>
        <div class="topbar-actions">
          <div ref="notificationMenu" class="notification-menu">
            <button class="notification-button" type="button" :aria-label="`通知，${unreadCount} 条未读`" :aria-expanded="notificationsOpen" aria-haspopup="dialog" @click="notificationsOpen = !notificationsOpen">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>
              <b v-if="unreadCount" aria-hidden="true">{{ unreadCount > 99 ? '99+' : unreadCount }}</b>
            </button>
            <div v-if="notificationsOpen" class="notification-popover" role="dialog" aria-label="通知">
              <div class="notification-popover-heading"><strong>通知</strong><div class="notification-heading-actions"><button class="link-button" type="button" @click="loadNotifications">刷新</button><button class="link-button" type="button" :disabled="!unreadCount || notificationBusy" :aria-busy="notificationBusy" @click="markAllNotificationsRead">{{ notificationBusy ? '处理中…' : '全部已读' }}</button></div></div>
              <p v-if="notificationError" class="notification-feedback is-error" role="alert">{{ notificationError }} <button class="link-button" type="button" @click="loadNotifications">重试</button></p>
              <p v-if="notificationNotice" class="notification-feedback" role="status">{{ notificationNotice }}</p>
              <div v-if="!notifications.length && !notificationError" class="notification-empty">暂无通知</div>
              <button v-for="item in notifications" :key="item.id" class="notification-item" :class="{ 'is-unread': !item.read }" type="button" @click="markNotification(item)"><span class="notification-dot" aria-hidden="true"></span><span class="notification-copy"><strong>{{ item.title }}</strong><small>{{ item.body }}</small><em v-if="item.target_type === 'fault' && item.target_id">点击查看故障处理</em></span><span class="notification-arrow" aria-hidden="true">→</span></button>
            </div>
          </div>
          <span class="health-chip"><span class="status-dot is-ok"></span>本地服务</span><RouterLink class="button primary compact" to="/diagnosis">开始诊断 →</RouterLink>
        </div>
      </header>
      <div v-if="user?.must_change_password" class="password-required-banner" role="alert"><span><strong>需要更新登录密码</strong><small>当前账号仍在使用初始密码，请先设置符合安全策略的新密码。</small></span><RouterLink class="button secondary compact" to="/account">立即修改</RouterLink></div><div class="admin-content"><RouterView /></div>
    </main>
  </div>
</template>
