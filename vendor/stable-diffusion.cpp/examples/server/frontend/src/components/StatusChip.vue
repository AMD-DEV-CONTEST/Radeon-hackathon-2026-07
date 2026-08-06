<script setup lang="ts">
import { computed } from "vue";

const STATUS_TONES: Record<string, string> = {
    online: "online",
    completed: "online",
    queued: "queued",
    generating: "generating",
    failed: "failed",
    cancelled: "cancelled",
    offline: "offline",
};

const props = withDefaults(defineProps<{
    status?: string;
    label?: string;
}>(), {
    status: "",
    label: "",
});

const tone = computed(() => STATUS_TONES[props.status] || "");

const classes = computed(() => ["chip", tone.value && `chip--${tone.value}`].filter(Boolean));
</script>

<template>
    <span :class="classes">{{ label || status || "idle" }}</span>
</template>
