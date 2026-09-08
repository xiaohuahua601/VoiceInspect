<script setup lang="ts">
import { computed } from 'vue'

type Evidence = Record<string, any>
const props = defineProps<{ evidence?: Evidence }>()
const vision = computed(() => props.evidence || {})
const diagnosis = computed(() => vision.value.diagnosis || {})
const observations = computed(() => diagnosis.value.observed_evidence || vision.value.observations || [])
const measurements = computed(() => vision.value.measurements || [])
const anomalies = computed(() => diagnosis.value.candidate_causes || vision.value.candidate_anomalies || [])
const checks = computed(() => diagnosis.value.recommended_checks || [])
const safety = computed(() => diagnosis.value.safety_actions || vision.value.safety_flags || [])
const uncertainties = computed(() => diagnosis.value.uncertainties || vision.value.uncertainties || [])
const confidenceLabel = computed(() => ({ low: '低置信度', medium: '中等置信度', high: '高置信度' } as Record<string, string>)[diagnosis.value.confidence] || '')

function textOf(item: any): string {
  if (typeof item === 'string') return item
  return item?.description || item?.name || item?.code || '未命名证据'
}
function evidenceOf(item: any): string {
  const evidence = item?.evidence
  return Array.isArray(evidence) ? evidence.join('、') : String(evidence || '')
}
</script>

<template>
  <section v-if="observations.length || measurements.length || anomalies.length || safety.length || uncertainties.length || checks.length" class="diagnostic-evidence" aria-label="图片与诊断证据">
    <div class="diagnostic-evidence-head">
      <div><p class="eyebrow">EVIDENCE REVIEW</p><strong>证据与判断边界</strong></div>
      <span v-if="confidenceLabel" class="evidence-confidence">{{ confidenceLabel }}</span>
    </div>
    <p v-if="diagnosis.summary" class="evidence-summary">{{ diagnosis.summary }}</p>
    <div class="evidence-grid">
      <section v-if="observations.length" class="evidence-card"><h4>图片观察</h4><ul><li v-for="(item, index) in observations" :key="'observation-' + index"><span>{{ textOf(item) }}</span><small v-if="item?.evidence">位置：{{ item.evidence }}</small><small v-if="item?.confidence != null">置信度 {{ Math.round(item.confidence * 100) }}%</small></li></ul></section>
      <section v-if="measurements.length" class="evidence-card"><h4>仪表读数</h4><ul><li v-for="(item, index) in measurements" :key="'measurement-' + index"><span>{{ item.name }}：{{ item.value == null ? '无法确认' : item.value }} {{ item.unit }}</span><small v-if="item.confidence != null">置信度 {{ Math.round(item.confidence * 100) }}%</small></li></ul></section>
      <section v-if="anomalies.length" class="evidence-card anomaly-card"><h4>疑似异常 · 待人工确认</h4><ul><li v-for="(item, index) in anomalies" :key="'anomaly-' + index"><span>{{ textOf(item) }}</span><small v-if="evidenceOf(item)">图片证据：{{ evidenceOf(item) }}</small><small>{{ item.severity || 'medium' }} · 置信度 {{ Math.round((item.confidence || 0.5) * 100) }}%</small></li></ul></section>
      <section v-if="checks.length" class="evidence-card"><h4>建议补充与检查</h4><ul><li v-for="(item, index) in checks" :key="'check-' + index"><span>{{ textOf(item) }}</span></li></ul></section>
      <section v-if="safety.length" class="evidence-card safety-card"><h4>安全提示</h4><ul><li v-for="(item, index) in safety" :key="'safety-' + index"><span>{{ textOf(item) }}</span></li></ul></section>
      <section v-if="uncertainties.length" class="evidence-card uncertainty-card"><h4>不确定性</h4><ul><li v-for="(item, index) in uncertainties" :key="'uncertainty-' + index"><span>{{ textOf(item) }}</span></li></ul></section>
    </div>
  </section>
</template>