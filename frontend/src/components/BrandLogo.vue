<script setup lang="ts">
withDefaults(defineProps<{
  compact?: boolean
}>(), {
  compact: false,
})
</script>

<template>
  <span class="brand-logo" :class="{ 'is-compact': compact }">
    <img class="brand-logo-mark" src="/brand/voiceinspect-mark.png" alt="" aria-hidden="true" />
    <span v-if="!compact" class="brand-logo-wordmark" aria-label="VOICE INSPECT">
      <span>VOICE</span>
      <span>INSPECT</span>
    </span>
  </span>
</template>