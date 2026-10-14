<script setup lang="ts">
import { computed } from 'vue'
import { navItems } from '@/router/routes'
import PanelPlaceholder from './PanelPlaceholder.vue'

const props = defineProps<{ routeName: string }>()

const item = computed(() => navItems.find((n) => n.name === props.routeName))
</script>

<template>
  <PanelPlaceholder
    v-if="item"
    :title="item.label"
    :icon="item.icon"
    :description="item.description"
    :phase="item.phase"
  />
</template>
