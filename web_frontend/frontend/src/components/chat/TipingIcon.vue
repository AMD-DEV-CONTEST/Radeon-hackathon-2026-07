<template>
  <img
    class="tiping-icon"
    :class="{ 'tiping-icon-scroll-motion': scrollMotion }"
    :src="tipingMarkerUrl"
    :width="size"
    :height="size"
    alt=""
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import tipingMarkerUrl from '@/assets/tiping-marker.png'

withDefaults(defineProps<{
  size?: number
  scrollMotion?: boolean
}>(), {
  size: 18,
  scrollMotion: false,
})
</script>

<style scoped>
.tiping-icon {
  display: block;
  flex: none;
  object-fit: contain;
  user-select: none;
  pointer-events: none;
}

.tiping-icon-scroll-motion {
  animation: tiping-icon-scroll-sway linear both;
  animation-timeline: scroll(nearest block);
}

@keyframes tiping-icon-scroll-sway {
  0%, 100% { transform: translateY(0) rotate(-3deg); }
  25% { transform: translateY(-1px) rotate(4deg); }
  50% { transform: translateY(1px) rotate(-2deg); }
  75% { transform: translateY(-1px) rotate(3deg); }
}

@media (prefers-reduced-motion: reduce) {
  .tiping-icon-scroll-motion { animation: none; }
}
</style>
