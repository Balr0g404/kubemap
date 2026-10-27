<script setup>
defineProps({ tone: { type: String, default: 'muted' } })
</script>

<template>
  <VChip :color="({ ok: 'success', bad: 'error', warn: 'warning', accent: 'secondary' })[tone]" size="x-small" variant="tonal" class="pill" :class="tone"><slot /></VChip>
</template>
