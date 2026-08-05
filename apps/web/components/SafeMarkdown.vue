<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = defineProps<{ source: string }>()

const rendered = computed(() => DOMPurify.sanitize(
  marked.parse(props.source || '', { async: false }) as string,
  {
    USE_PROFILES: { html: true },
    ALLOW_DATA_ATTR: false,
    FORBID_TAGS: ['img', 'iframe', 'form', 'input', 'button', 'style', 'svg', 'math'],
    FORBID_ATTR: ['style']
  }
))
</script>

<template>
  <div class="safe-markdown" v-html="rendered" />
</template>
