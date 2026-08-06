<template>
  <span
    class="resource-icon"
    :class="presentation.iconClass"
    :style="{ fontSize: `${size}px` }"
    role="img"
    :aria-label="presentation.typeLabel"
  ></span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { resourcePresentation } from '@/utils/resourcePresentation'

const props = withDefaults(
  defineProps<{
    name: string
    mimeType?: string | null
    kind?: 'file' | 'directory' | 'url' | string | null
    expanded?: boolean
    size?: number
  }>(),
  {
    mimeType: null,
    kind: 'file',
    expanded: false,
    size: 18,
  },
)

const presentation = computed(() => resourcePresentation({
  name: props.name,
  mimeType: props.mimeType,
  kind: props.kind,
  expanded: props.expanded,
}))
</script>

<style scoped>
.resource-icon {
  display: inline-block;
  width: 1em;
  height: 1em;
  flex: 0 0 auto;
  background-repeat: no-repeat;
  background-position: center;
  background-size: contain;
}
</style>
