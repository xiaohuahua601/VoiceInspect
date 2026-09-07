<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request, setAuth, roleLabel } from '../api'
const router = useRouter(); const route = useRoute()
const username = ref('operator'); const password = ref('change-me'); const busy = ref(false); const error = ref('')
async function login() {
  error.value = ''; busy.value = true
  try {
    const result = await request<{ access_token: string; user: any }>('/auth/login', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
    setAuth(result.access_token, result.user)
    router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard')
  } catch (e) { error.value = e instanceof Error ? e.message : '登录失败' } finally { busy.value = false }
}
</script>
<template>
  <main class="login-stage"><div class="login-copy"><div class="login-mark"><span class="pulse-dot"></span><span>VOICEINSPECT</span></div><p class="eyebrow">ENTERPRISE DIAGNOSTICS / 02</p><h1>让每一次判断<br><em>都有依据。</em></h1><p>统一管理组织、设备、故障、知识和诊断证据，形成可追溯的现场闭环。</p></div><form class="login-form" @submit.prevent="login"><label for="login-user">账号</label><input id="login-user" v-model="username" autocomplete="username"><label for="login-password">密码</label><input id="login-password" v-model="password" type="password" autocomplete="current-password"><p v-if="error" class="inline-error" role="alert">{{ error }}</p><button class="button primary full" :disabled="busy">{{ busy ? '正在验证…' : '进入企业后台' }}</button><p class="login-hint">演示账号：operator / change-me · 管理员：admin / change-me-admin</p></form></main>
</template>