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
        { path: 'users', component: UsersView, meta: { roles: ['system_admin'] } },
        { path: 'settings', component: SettingsView, meta: { roles: ['system_admin'] } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
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
