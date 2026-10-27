<script setup>
import { computed } from 'vue'
const props = defineProps({ label: String, value: Number })
const tone = computed(() => (props.value >= 85 ? 'bad' : props.value >= 70 ? 'warn' : ''))
</script>

<template>
  <div class="meter">
    <span>{{ label }}</span>
    <div class="track"><i :class="tone" :style="{ width: (value ?? 0) + '%' }" /></div>
    <span class="num mono">{{ value == null ? '—' : value + '%' }}</span>
  </div>
</template>
