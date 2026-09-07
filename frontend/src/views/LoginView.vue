<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request, setAuth } from '../api'

const router = useRouter()
const route = useRoute()
const username = ref('operator')
const password = ref('change-me')
const busy = ref(false)
const error = ref('')

type DemoAccount = { username: string; password: string; role: string; description: string }
const demoAccounts: DemoAccount[] = [
  { username: 'operator', password: 'change-me', role: '操作员', description: '创建诊断、查看授权范围故障' },
  { username: 'supervisor', password: 'change-me-supervisor', role: '维修主管', description: '确认、分派和关闭故障' },
  { username: 'knowledge-admin', password: 'change-me-knowledge', role: '知识管理员', description: '导入、索引和发布知识' },
  { username: 'admin', password: 'change-me-admin', role: '系统管理员', description: '组织、用户和系统设置' },
]

function fillDemo(account: DemoAccount) {
  username.value = account.username
  password.value = account.password
  error.value = ''
}

async function login() {
  error.value = ''
  busy.value = true
  try {
    const result = await request<{ access_token: string; user: any }>('/auth/login', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
    setAuth(result.access_token, result.user)
    router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard')
  } catch (e) { error.value = e instanceof Error ? e.message : '登录失败' }
  finally { busy.value = false }
}
</script>

<template>
  <main class="login-stage">
    <div class="login-copy"><div class="login-mark"><span class="pulse-dot" aria-hidden="true"></span><span>VOICEINSPECT</span></div><p class="eyebrow">ENTERPRISE DIAGNOSTICS / 02</p><h1>让每一次判断<br><em>都有依据。</em></h1><p>统一管理组织、设备、故障、知识和诊断证据，形成可追溯的现场闭环。</p></div>
    <form class="login-form" novalidate @submit.prevent="login">
      <div class="login-form-heading"><span class="eyebrow">LOCAL DEMO ACCESS</span><h2>进入企业后台</h2><p>选择角色可自动填充本地演示账号。</p></div>
      <label for="login-user">账号</label><input id="login-user" v-model="username" autocomplete="username" placeholder="输入账号">
      <label for="login-password">密码</label><input id="login-password" v-model="password" type="password" autocomplete="current-password" placeholder="输入密码">
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
      <button class="button primary full" type="submit" :disabled="busy" :aria-busy="busy">{{ busy ? '正在验证…' : '进入企业后台' }}</button>
      <div class="demo-account-panel"><div class="demo-account-heading"><span>演示账户</span><small>仅用于本地开发测试</small></div><div class="demo-account-list"><button v-for="account in demoAccounts" :key="account.username" class="demo-account" type="button" @click="fillDemo(account)"><span class="demo-account-avatar">{{ account.role.slice(0, 1) }}</span><span class="demo-account-copy"><strong>{{ account.role }}</strong><small>{{ account.username }} / {{ account.password }}</small><em>{{ account.description }}</em></span><span class="demo-account-action">填充</span></button></div></div>
    </form>
  </main>
</template>