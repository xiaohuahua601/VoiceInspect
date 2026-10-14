<script setup lang="ts">
import BrandLogo from './BrandLogo.vue'

defineProps<{
  eyebrow: string
  description: string
}>()
</script>

<template>
  <div class="login-copy">
    <div class="login-mark"><BrandLogo /></div>
    <p class="eyebrow login-eyebrow">{{ eyebrow }}</p>
    <h1>让每一次判断<br /><em>都有依据。</em></h1>
    <p class="login-description">{{ description }}</p>
  </div>
</template>