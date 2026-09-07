<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  pages: number
  total: number
  pageSize: number
  start: number
  end: number
}>()
const emit = defineEmits<{
  'update:page': [value: number]
  'update:page-size': [value: number]
}>()

const pageNumbers = computed(() => {
  const total = props.pages
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1)
  if (props.page <= 4) return [1, 2, 3, 4, 5, -1, total]
  if (props.page >= total - 3) return [1, -1, total - 4, total - 3, total - 2, total - 1, total]
  return [1, -1, props.page - 1, props.page, props.page + 1, -1, total]
})

function go(page: number) {
  if (page < 1 || page > props.pages || page === props.page) return
  emit('update:page', page)
}
</script>

<template>
  <div v-if="total" class="pagination-bar" aria-label="分页">
    <span class="pagination-summary">显示 {{ start }}–{{ end }} 条，共 {{ total }} 条</span>
    <div class="pagination-options">
      <label>每页
        <select :value="pageSize" aria-label="每页显示数量" @change="emit('update:page-size', Number(($event.target as HTMLSelectElement).value))">
          <option :value="10">10 条</option>
          <option :value="20">20 条</option>
          <option :value="50">50 条</option>
        </select>
      </label>
      <nav class="pagination-controls" aria-label="页码">
        <button class="pagination-button pagination-arrow" type="button" :disabled="page === 1" aria-label="上一页" @click="go(page - 1)">‹</button>
        <template v-for="(item, index) in pageNumbers" :key="item + '-' + index">
          <span v-if="item === -1" class="pagination-ellipsis" aria-hidden="true">…</span>
          <button v-else class="pagination-button" :class="{ active: item === page }" type="button" :aria-current="item === page ? 'page' : undefined" :aria-label="'第 ' + item + ' 页'" @click="go(item)">{{ item }}</button>
        </template>
        <button class="pagination-button pagination-arrow" type="button" :disabled="page === pages" aria-label="下一页" @click="go(page + 1)">›</button>
      </nav>
    </div>
  </div>
</template>