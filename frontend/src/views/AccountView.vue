<script setup lang="ts">
import { computed, ref } from 'vue'
import { getStoredUser, request, roleLabel, setAuth, type User } from '../api'

const user = ref(getStoredUser())
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const policy = computed(() => {
  const value = newPassword.value
  return [
    { label: '至少 12 个字符', valid: value.length >= 12 },
    { label: '包含大写字母', valid: /[A-Z]/.test(value) },
    { label: '包含小写字母', valid: /[a-z]/.test(value) },
    { label: '包含数字', valid: /\d/.test(value) },
  ]
})
const valid = computed(() => policy.value.every(item => item.valid) && newPassword.value === confirmPassword.value && Boolean(currentPassword.value))

async function submit() {
  error.value = ''
  notice.value = ''
  if (!valid.value) {
    error.value = newPassword.value !== confirmPassword.value ? '两次输入的新密码不一致' : '请先满足全部密码安全要求'
    return
  }
  busy.value = true
  try {
    await request('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword.value, new_password: newPassword.value }) })
    if (user.value) {
      const updated: User = { ...user.value, must_change_password: false }
      user.value = updated
      setAuth(localStorage.getItem('voiceinspect_token') ?? '', updated)
    }
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    notice.value = '密码已更新，后续登录将使用新密码。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '密码更新失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="page-view account-view">
    <div class="page-heading"><div><span class="eyebrow">ACCOUNT SECURITY</span><h2>账号安全</h2><p>为本地账号更新密码；密码只在服务端进行校验和哈希保存。</p></div></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="inline-notice" role="status">{{ notice }}</p>
    <section class="panel account-panel">
      <div class="account-summary"><span class="avatar">{{ user?.username?.slice(0, 1).toUpperCase() }}</span><div><strong>{{ user?.username }}</strong><small>{{ roleLabel(user?.role) }} · {{ user?.organization_id || '全局账号' }}</small></div></div>
      <form class="form-grid single" novalidate @submit.prevent="submit">
        <label for="current-password">当前密码<input id="current-password" v-model="currentPassword" type="password" autocomplete="current-password" required></label>
        <label for="new-password">新密码<input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" required><span class="password-policy"><span v-for="item in policy" :key="item.label" :class="{ valid: item.valid }">{{ item.valid ? '✓' : '○' }} {{ item.label }}</span></span></label>
        <label for="confirm-password">确认新密码<input id="confirm-password" v-model="confirmPassword" type="password" autocomplete="new-password" required></label>
        <button class="button primary" type="submit" :disabled="busy || !valid" :aria-busy="busy">{{ busy ? '正在保存…' : '更新密码' }}</button>
      </form>
    </section>
  </section>
</template>
