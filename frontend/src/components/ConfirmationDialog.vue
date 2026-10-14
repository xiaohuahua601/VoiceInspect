<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  open: boolean
  eyebrow?: string
  title: string
  description: string
  confirmLabel?: string
  busy?: boolean
  error?: string
}>(), {
  eyebrow: 'CONFIRM ACTION',
  confirmLabel: '确认',
  busy: false,
  error: '',
})

const emit = defineEmits<{ cancel: []; confirm: [] }>()
const cancelButton = ref<HTMLButtonElement | null>(null)
const dialog = ref<HTMLElement | null>(null)

function cancel() {
  if (!props.busy) emit('cancel')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancel()
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = Array.from(dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)'))
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => props.open, (open) => {
  if (open) nextTick(() => cancelButton.value?.focus())
})
</script>

<template>
  <div v-if="open" class="dialog-backdrop" role="presentation" @mousedown.self="cancel">
    <section ref="dialog" class="confirm-dialog confirm-dialog-danger" role="alertdialog" aria-modal="true" aria-labelledby="confirmation-dialog-title" aria-describedby="confirmation-dialog-description" @keydown="handleKeydown">
      <p class="eyebrow">{{ eyebrow }}</p>
      <h3 id="confirmation-dialog-title">{{ title }}</h3>
      <p id="confirmation-dialog-description">{{ description }}</p>
      <p v-if="error" class="inline-error confirmation-error" role="alert">{{ error }}</p>
      <div class="dialog-actions">
        <button ref="cancelButton" class="button secondary" type="button" :disabled="busy" @click="cancel">取消</button>
        <button class="button danger" type="button" :disabled="busy" :aria-busy="busy" @click="emit('confirm')">{{ busy ? '正在删除…' : confirmLabel }}</button>
      </div>
    </section>
  </div>
</template>
