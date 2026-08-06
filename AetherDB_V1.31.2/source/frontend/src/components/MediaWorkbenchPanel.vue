<script setup>
import { nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";
import { AudioLines, Images, Search, WandSparkles } from "@lucide/vue";
import AudioContractPanel from "./AudioContractPanel.vue";
import ImageGenerationPanel from "./ImageGenerationPanel.vue";
import MediaAssetPanel from "./MediaAssetPanel.vue";
import VisualRetrievalPanel from "./VisualRetrievalPanel.vue";

const { t } = useI18n();
const activeTool = ref("assets");
const assetsPanel = ref(null);

async function openAssets() {
  activeTool.value = "assets";
  await nextTick();
  await assetsPanel.value?.refresh();
}
</script>

<template>
  <div class="media-workbench">
    <div class="media-tool-tabs" role="tablist" :aria-label="t('媒体工具')">
      <button
        type="button"
        role="tab"
        :aria-selected="activeTool === 'vision'"
        :class="{ active: activeTool === 'vision' }"
        @click="activeTool = 'vision'"
      >
        <Search :size="16" />{{ t("视觉检索") }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTool === 'assets'"
        :class="{ active: activeTool === 'assets' }"
        @click="activeTool = 'assets'"
      >
        <Images :size="16" />{{ t("资产审批") }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTool === 'image'"
        :class="{ active: activeTool === 'image' }"
        @click="activeTool = 'image'"
      >
        <WandSparkles :size="16" />{{ t("图像生成") }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTool === 'audio'"
        :class="{ active: activeTool === 'audio' }"
        @click="activeTool = 'audio'"
      >
        <AudioLines :size="16" />{{ t("音频创作") }}
      </button>
    </div>

    <MediaAssetPanel v-if="activeTool === 'assets'" ref="assetsPanel" />
    <ImageGenerationPanel v-else-if="activeTool === 'image'" @open-assets="openAssets" />
    <VisualRetrievalPanel v-else-if="activeTool === 'vision'" @open-assets="openAssets" />
    <AudioContractPanel v-else @open-assets="openAssets" />
  </div>
</template>

<style scoped>
.media-workbench { min-width: 0; display: grid; gap: 9px; }
.media-tool-tabs { width: max-content; max-width: 100%; display: inline-grid; grid-template-columns: repeat(4,minmax(0,1fr)); overflow: hidden; border: 1px solid var(--border); border-radius: 7px; background: #fff; }
.media-tool-tabs button { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-right: 1px solid var(--border); background: #fff; color: var(--text-secondary); padding: 6px 12px; cursor: pointer; font-size: 11px; white-space: nowrap; }
.media-tool-tabs button:last-child { border-right: 0; }
.media-tool-tabs button.active { background: var(--accent-soft); color: var(--accent); font-weight: 700; }
@media (max-width: 560px) {
  .media-tool-tabs { width: 100%; }
  .media-tool-tabs button { min-width: 0; padding-inline: 5px; white-space: normal; }
}
</style>
