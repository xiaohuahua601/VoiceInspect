<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { clearAuth, getStoredUser, request, roleLabel } from '../api'

const router = useRouter()
const route = useRoute()
const user = computed(() => getStoredUser())
const notifications = ref<any[]>([])
const notificationsOpen = ref(false)
const unreadCount = computed(() => notifications.value.filter(item => !item.read).length)
async function loadNotifications() {
  try { notifications.value = await request<any[]>('/notifications') } catch { notifications.value = [] }
}
async function markNotification(item: any) {
  if (item.read) return
  try { await request(`/notifications/${item.id}/read`, { method: 'POST' }); item.read = true } catch { /* keep unread when network fails */ }
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
onMounted(loadNotifications)
</script>

<template>
  <div class="admin-shell" :class="{ 'is-diagnosis': route.path === '/diagnosis' }">
    <aside class="admin-sidebar">
      <div class="admin-brand"><span class="pulse-dot"></span><span>VOICE<br>INSPECT</span></div>
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
      <header class="admin-topbar"><div><span class="eyebrow">VOICEINSPECT / OPERATIONS</span><h1>工业设备智能诊断后台</h1></div><div class="topbar-actions"><div class="notification-menu"><button class="notification-button" type="button" aria-label="查看通知" :aria-expanded="notificationsOpen" @click="notificationsOpen = !notificationsOpen"><span aria-hidden="true">♢</span><b v-if="unreadCount">{{ unreadCount > 9 ? '9+' : unreadCount }}</b></button><div v-if="notificationsOpen" class="notification-popover" role="dialog" aria-label="通知"><div class="notification-popover-heading"><strong>通知</strong><button class="link-button" type="button" @click="loadNotifications">刷新</button></div><div v-if="!notifications.length" class="notification-empty">暂无通知</div><button v-for="item in notifications" :key="item.id" class="notification-item" :class="{ 'is-unread': !item.read }" type="button" @click="markNotification(item)"><span class="notification-dot" aria-hidden="true"></span><span><strong>{{ item.title }}</strong><small>{{ item.body }}</small></span></button></div></div><span class="health-chip"><span class="status-dot is-ok"></span>本地服务</span><RouterLink class="button primary compact" to="/diagnosis">开始诊断 →</RouterLink></div></header>
      <div v-if="user?.must_change_password" class="password-required-banner" role="alert"><span><strong>需要更新登录密码</strong><small>当前账号仍在使用初始密码，请先设置符合安全策略的新密码。</small></span><RouterLink class="button secondary compact" to="/account">立即修改</RouterLink></div><div class="admin-content"><RouterView /></div>
    </main>
  </div>
</template>
