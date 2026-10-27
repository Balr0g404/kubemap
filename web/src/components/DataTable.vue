<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, required: true },
  rowKey: { type: Function, default: (_, i) => i },
  initialSort: { type: String, default: null },
  pageSize: { type: Number, default: 300 },
})
const emit = defineEmits(['select'])

const sortKey = ref(props.initialSort)
const dir = ref(1)
const shown = ref(props.pageSize)
watch(() => props.rows.length, () => (shown.value = Math.max(shown.value, props.pageSize)))

const sorted = computed(() => {
  const col = props.columns.find((c) => c.key === sortKey.value)
  if (!col) return props.rows
  const f = col.sort ?? ((r) => r[col.key])
  return [...props.rows].sort((a, b) => {
    const x = f(a), y = f(b)
    return (x > y ? 1 : x < y ? -1 : 0) * dir.value
  })
})
const visible = computed(() => sorted.value.slice(0, shown.value))

function sortBy(col) {
  if (sortKey.value === col.key) dir.value *= -1
  else { sortKey.value = col.key; dir.value = 1 }
}
</script>

<template>
  <div class="table-wrap">
    <VTable density="compact">
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key" :aria-sort="sortKey === c.key ? (dir > 0 ? 'ascending' : 'descending') : 'none'">
            <button class="table-sort" @click="sortBy(c)">{{ c.label }} <span v-if="sortKey === c.key">{{ dir > 0 ? '↑' : '↓' }}</span></button>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in visible" :key="rowKey(r, i)" class="clickable" tabindex="0" @click="emit('select', r)" @keydown.enter.self="emit('select', r)" @keydown.space.self.prevent="emit('select', r)">
          <td v-for="c in columns" :key="c.key" :class="c.class">
            <slot :name="'cell-' + c.key" :row="r">{{ r[c.key] }}</slot>
          </td>
        </tr>
      </tbody>
    </VTable>
    <div v-if="!rows.length" class="empty">Aucun résultat</div>
    <div v-else-if="sorted.length > shown" class="empty">
      {{ shown }} sur {{ sorted.length }} lignes ·
      <VBtn size="small" variant="tonal" class="btn" @click="shown += pageSize">Afficher plus</VBtn>
    </div>
  </div>
</template>
