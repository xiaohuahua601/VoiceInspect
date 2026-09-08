import { createRouter, createWebHistory } from 'vue-router'
import { canAccess, getStoredUser } from './api'
import LoginView from './views/LoginView.vue'
import AppLayout from './views/AppLayout.vue'
import DashboardView from './views/DashboardView.vue'
import DiagnosisView from './views/DiagnosisView.vue'
import SessionsView from './views/SessionsView.vue'
import FaultsView from './views/FaultsView.vue'
import DevicesView from './views/DevicesView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import ReportsView from './views/ReportsView.vue'
import AuditView from './views/AuditView.vue'
import UsersView from './views/UsersView.vue'
import SettingsView from './views/SettingsView.vue'
import AccountView from './views/AccountView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: DashboardView },
        { path: 'diagnosis', component: DiagnosisView },
        { path: 'sessions', component: SessionsView },
        { path: 'sessions/:id', component: SessionsView, props: true },
        { path: 'faults', component: FaultsView },
        { path: 'faults/:id', component: FaultsView, props: true },
        { path: 'devices', component: DevicesView },
        { path: 'devices/:id', component: DevicesView, props: true },
        { path: 'knowledge', component: KnowledgeView },
        { path: 'knowledge/:id', component: KnowledgeView, props: true },
        { path: 'reports', component: ReportsView },
        { path: 'audit', component: AuditView },
        { path: 'account', component: AccountView },
        { path: 'users', component: UsersView, meta: { roles: ['system_admin'] } },
        { path: 'settings', component: SettingsView, meta: { roles: ['system_admin'] } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})
const pageTitles: Record<string, string> = {
  '/dashboard': '运营总览',
  '/diagnosis': '多模态诊断',
  '/sessions': '诊断会话',
  '/faults': '故障闭环',
  '/devices': '设备资产',
  '/knowledge': '知识库',
  '/reports': '报告中心',
  '/audit': '审计追踪',
  '/account': '账号安全',
  '/users': '用户与权限',
  '/settings': '系统设置',
}
router.afterEach((to) => {
  const key = Object.keys(pageTitles).find(path => to.path === path || to.path.startsWith(path + '/'))
  document.title = (key ? pageTitles[key] : '页面') + ' — VoiceInspect'
})

router.beforeEach((to) => {
  const user = getStoredUser()
  if (to.meta.public && user) return '/dashboard'
  if (!to.meta.public && !user) return { path: '/login', query: { redirect: to.fullPath } }
  const roles = to.meta.roles as string[] | undefined
  if (roles && !canAccess(user?.role, roles)) return '/dashboard'
  return true
})
export default router
