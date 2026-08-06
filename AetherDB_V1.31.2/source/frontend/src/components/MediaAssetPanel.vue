<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  Archive,
  Check,
  Image,
  Languages,
  Link2,
  Music2,
  RefreshCw,
  Trash2,
  Unlink2,
  Upload,
  Video,
} from "@lucide/vue";
import {
  approveMediaAsset,
  archiveMediaAsset,
  createMediaBinding,
  deleteMediaAsset,
  deleteMediaBinding,
  getMediaAsset,
  listEffectiveChapterMedia,
  listMediaAssets,
  loadMediaContent,
  uploadMediaAsset,
} from "../api/mediaAssets.js";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();
const fileInput = ref(null);
const assets = ref([]);
const selected = ref(null);
const previewUrl = ref("");
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const modality = ref("");
const bindingScope = ref("all_languages");
const effectiveCount = ref(0);

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const canUpload = computed(() => Boolean(databaseId.value && bookId.value));
const activeLanguage = computed(() => store.activeChapter?.language_code || "und");
const activeContentGroupId = computed(() => store.activeChapter?.content_group_id || "");
const relevantBindings = computed(() => (selected.value?.bindings || []).filter((item) => (
  (
    item.target_type === "chapter"
    && item.target_id === store.activeChapter?.chapter_id
  )
  || (
    item.target_type === "content_group"
    && item.target_id === activeContentGroupId.value
  )
)));
const selectedScopeBindings = computed(() => relevantBindings.value.filter((item) => (
  bindingScope.value === "all_languages"
    ? item.target_type === "content_group"
    : item.target_type === "chapter"
)));
const canBindSelectedScope = computed(() => (
  selected.value?.lifecycle_status === "approved"
  && store.activeChapter
  && (
    bindingScope.value === "current_language"
    || Boolean(activeContentGroupId.value)
  )
  && !selectedScopeBindings.value.length
));

const modalityIcon = { image: Image, audio: Music2, video: Video };
const statusLabel = {
  temporary: "待审批",
  pending: "待审批",
  pending_review: "审核中",
  approved: "已批准",
  archived: "已归档",
  soft_deleted: "已删除",
  rejected: "已拒绝",
};

function releasePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = "";
}

async function refresh() {
  if (!canUpload.value) {
    assets.value = [];
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const response = await listMediaAssets({
      database_id: databaseId.value,
      book_id: bookId.value,
      modality: modality.value || undefined,
      limit: 200,
    });
    assets.value = response.assets || [];
    if (store.activeChapter?.chapter_id) {
      const effective = await listEffectiveChapterMedia({
        database_id: databaseId.value,
        book_id: bookId.value,
        chapter_id: store.activeChapter.chapter_id,
        language_code: activeLanguage.value,
        modality: modality.value || undefined,
        limit: 1,
      });
      effectiveCount.value = effective.total || 0;
    } else {
      effectiveCount.value = 0;
    }
    if (selected.value && !assets.value.some((item) => item.asset_id === selected.value.asset_id)) {
      selected.value = null;
      releasePreview();
    }
  } catch (reason) {
    error.value = reason?.message || t("媒体资产加载失败");
  } finally {
    loading.value = false;
  }
}

async function selectAsset(asset) {
  error.value = "";
  releasePreview();
  try {
    const response = await getMediaAsset(asset.asset_id, databaseId.value);
    selected.value = response.asset;
    const blob = await loadMediaContent(asset.asset_id, databaseId.value);
    previewUrl.value = URL.createObjectURL(blob);
  } catch (reason) {
    error.value = reason?.message || t("媒体预览加载失败");
  }
}

async function importFiles(event) {
  const files = [...(event.target.files || [])];
  if (!files.length || !canUpload.value) return;
  busy.value = true;
  error.value = "";
  try {
    for (const file of files) {
      await uploadMediaAsset({
        databaseId: databaseId.value,
        bookId: bookId.value,
        file,
      });
    }
    store.notifyAction(t("已导入 {count} 个媒体资产，批准后才能绑定", { count: files.length }));
    await refresh();
  } catch (reason) {
    error.value = reason?.message || t("媒体导入失败");
  } finally {
    event.target.value = "";
    busy.value = false;
  }
}

async function approve() {
  if (!selected.value) return;
  busy.value = true;
  try {
    const response = await approveMediaAsset(selected.value.asset_id, databaseId.value);
    selected.value = { ...selected.value, ...response.asset };
    await refresh();
  } catch (reason) {
    error.value = reason?.message || t("审批失败");
  } finally {
    busy.value = false;
  }
}

async function archive() {
  if (!selected.value) return;
  busy.value = true;
  try {
    const response = await archiveMediaAsset(selected.value.asset_id, databaseId.value);
    selected.value = { ...selected.value, ...response.asset };
    await refresh();
  } catch (reason) {
    error.value = reason?.message || t("归档失败");
  } finally {
    busy.value = false;
  }
}

async function bindChapter() {
  if (!selected.value || !store.activeChapter) return;
  const allLanguages = bindingScope.value === "all_languages";
  if (allLanguages && !activeContentGroupId.value) {
    error.value = t("当前章节尚未建立内容组");
    return;
  }
  busy.value = true;
  try {
    await createMediaBinding(selected.value.asset_id, databaseId.value, {
      book_id: bookId.value,
      target_type: allLanguages ? "content_group" : "chapter",
      target_id: allLanguages
        ? activeContentGroupId.value
        : store.activeChapter.chapter_id,
      language_code: allLanguages ? undefined : activeLanguage.value,
      binding_type: selected.value.modality === "audio" ? "soundtrack" : "chapter_illustration",
    });
    await selectAsset(selected.value);
    await refresh();
    store.notifyAction(t(
      allLanguages ? "媒体资产已绑定该章节的所有语言版本" : "媒体资产已绑定当前语言版本",
    ));
  } catch (reason) {
    error.value = reason?.message || t("章节绑定失败");
  } finally {
    busy.value = false;
  }
}

async function unbindChapter(bindingId) {
  if (!selected.value) return;
  busy.value = true;
  try {
    await deleteMediaBinding(selected.value.asset_id, bindingId, databaseId.value);
    await selectAsset(selected.value);
  } catch (reason) {
    error.value = reason?.message || t("解除绑定失败");
  } finally {
    busy.value = false;
  }
}

async function removeAsset() {
  if (!selected.value || !window.confirm(t("确定删除这个媒体资产？已绑定资产必须先解除绑定。"))) return;
  busy.value = true;
  try {
    await deleteMediaAsset(selected.value.asset_id, databaseId.value);
    selected.value = null;
    releasePreview();
    await refresh();
  } catch (reason) {
    error.value = reason?.message || t("删除失败");
  } finally {
    busy.value = false;
  }
}

watch(
  [
    databaseId,
    bookId,
    modality,
    () => store.activeChapter?.chapter_id,
    activeLanguage,
  ],
  refresh,
  { immediate: true },
);
onBeforeUnmount(releasePreview);
defineExpose({ refresh });
</script>

<template>
  <section class="media-panel">
    <header class="media-toolbar">
      <div>
        <strong>{{ t("媒体资产") }}</strong>
        <span>{{ t("{count} 项内容", { count: assets.length }) }}</span>
        <span v-if="store.activeChapter">{{ t("当前章节可用 {count} 项", { count: effectiveCount }) }}</span>
      </div>
      <label>
        <span class="sr-only">{{ t("媒体类型") }}</span>
        <select v-model="modality">
          <option value="">{{ t("全部类型") }}</option>
          <option value="image">{{ t("图片") }}</option>
          <option value="audio">{{ t("音频") }}</option>
          <option value="video">{{ t("视频") }}</option>
        </select>
      </label>
      <button class="icon-button" type="button" :title="t('刷新')" :disabled="loading" @click="refresh">
        <RefreshCw :size="16" :class="{ spinning: loading }" />
      </button>
      <button type="button" :disabled="!canUpload || busy" @click="fileInput?.click()">
        <Upload :size="16" />{{ t("导入") }}
      </button>
      <input
        ref="fileInput"
        class="file-input"
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,audio/wav,audio/flac,audio/ogg,audio/mpeg,video/mp4,video/webm"
        multiple
        @change="importFiles"
      />
    </header>

    <p v-if="error" class="media-error">{{ error }}</p>
    <div v-if="!canUpload" class="media-empty">{{ t("选择数据库和作品后可管理媒体资产。") }}</div>
    <div v-else class="media-body">
      <div class="asset-list">
        <button
          v-for="asset in assets"
          :key="asset.asset_id"
          type="button"
          :class="{ active: selected?.asset_id === asset.asset_id }"
          @click="selectAsset(asset)"
        >
          <component :is="modalityIcon[asset.modality]" :size="20" />
          <span>
            <strong>{{ asset.original_filename }}</strong>
            <small>{{ t(statusLabel[asset.lifecycle_status] || asset.lifecycle_status) }} · {{ Math.ceil(asset.file_size_bytes / 1024) }} KB</small>
          </span>
        </button>
        <div v-if="!loading && !assets.length" class="media-empty compact">{{ t("当前作品暂无媒体资产。") }}</div>
      </div>

      <article class="asset-detail">
        <template v-if="selected">
          <div class="preview">
            <img v-if="selected.modality === 'image' && previewUrl" :src="previewUrl" :alt="selected.original_filename" />
            <audio v-else-if="selected.modality === 'audio' && previewUrl" :src="previewUrl" controls />
            <video v-else-if="selected.modality === 'video' && previewUrl" :src="previewUrl" controls />
            <component v-else :is="modalityIcon[selected.modality]" :size="36" />
          </div>
          <header>
            <div><strong>{{ selected.original_filename }}</strong><small>{{ selected.mime_type }} · {{ t(statusLabel[selected.lifecycle_status] || selected.lifecycle_status) }}</small></div>
            <span>{{ selected.metadata?.width ? `${selected.metadata.width} × ${selected.metadata.height}` : "" }}</span>
          </header>
          <section v-if="store.activeChapter" class="binding-band">
            <div class="binding-heading">
              <Languages :size="16" />
              <div>
                <strong>{{ t("语言绑定范围") }}</strong>
                <small>{{ t("专属绑定优先于所有语言共用资产") }}</small>
              </div>
            </div>
            <div class="scope-control" role="group" :aria-label="t('语言绑定范围')">
              <button
                type="button"
                :class="{ active: bindingScope === 'all_languages' }"
                :disabled="!activeContentGroupId"
                @click="bindingScope = 'all_languages'"
              >
                {{ t("所有语言") }}
              </button>
              <button
                type="button"
                :class="{ active: bindingScope === 'current_language' }"
                @click="bindingScope = 'current_language'"
              >
                {{ t("当前语言：{language}", { language: activeLanguage }) }}
              </button>
            </div>
            <button
              v-if="canBindSelectedScope"
              class="bind-button"
              type="button"
              :disabled="busy"
              @click="bindChapter"
            >
              <Link2 :size="15" />{{ t("绑定到所选范围") }}
            </button>
            <span v-else-if="selectedScopeBindings.length" class="scope-state">
              <Check :size="14" />{{ t("已绑定所选范围") }}
            </span>
          </section>
          <section
            v-if="relevantBindings.length || selected.annotations?.length"
            class="provenance-band"
          >
            <div v-if="relevantBindings.length" class="provenance-group">
              <strong>{{ t("当前章节绑定") }}</strong>
              <div
                v-for="binding in relevantBindings"
                :key="binding.binding_id"
                class="provenance-row"
              >
                <span>
                  {{ binding.target_type === "content_group"
                    ? t("所有语言共用")
                    : t("语言专属：{language}", { language: binding.language_code || activeLanguage }) }}
                </span>
                <button
                  class="icon-button"
                  type="button"
                  :title="t('解除此绑定')"
                  :aria-label="t('解除此绑定')"
                  :disabled="busy"
                  @click="unbindChapter(binding.binding_id)"
                >
                  <Unlink2 :size="14" />
                </button>
              </div>
            </div>
            <div v-if="selected.annotations?.length" class="provenance-group">
              <strong>{{ t("文字注释状态") }}</strong>
              <div
                v-for="annotation in selected.annotations"
                :key="annotation.annotation_id"
                class="provenance-row"
              >
                <span>{{ annotation.annotation_type }} · {{ annotation.language_code || "und" }}</span>
                <small :class="{ stale: annotation.is_stale }">
                  {{ annotation.is_stale
                    ? t("已过期")
                    : t(statusLabel[annotation.approval_status] || annotation.approval_status) }}
                </small>
              </div>
            </div>
          </section>
          <div class="asset-actions">
            <button v-if="['temporary','pending_review'].includes(selected.lifecycle_status)" type="button" :disabled="busy" @click="approve"><Check :size="15" />{{ t("批准") }}</button>
            <button v-if="selected.lifecycle_status === 'approved'" type="button" :disabled="busy" @click="archive"><Archive :size="15" />{{ t("归档") }}</button>
            <button class="danger" type="button" :disabled="busy" @click="removeAsset"><Trash2 :size="15" />{{ t("删除") }}</button>
          </div>
        </template>
        <div v-else class="media-empty">{{ t("选择一项资产进行预览和管理。") }}</div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.media-panel { min-height: 610px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); }
.media-toolbar { min-height: 48px; display: flex; align-items: center; gap: 7px; border-bottom: 1px solid var(--border); padding: 7px 9px; }
.media-toolbar > div { min-width: 0; display: flex; align-items: baseline; gap: 7px; margin-right: auto; }
.media-toolbar strong { font-size: 12px; }
.media-toolbar span, .asset-detail small { color: var(--text-muted); font-size: 10px; }
.media-toolbar select, .media-toolbar button, .asset-actions button { min-height: 32px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); padding: 5px 9px; font-size: 10px; }
.media-toolbar button, .asset-actions button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; cursor: pointer; }
.media-toolbar button:last-of-type { border-color: var(--accent); background: var(--accent); color: #fff; }
.media-toolbar .icon-button { width: 32px; padding: 0; }
.media-toolbar button:disabled, .asset-actions button:disabled { cursor: not-allowed; opacity: .55; }
.file-input { display: none; }
.media-body { min-height: 560px; display: grid; grid-template-columns: minmax(190px, 32%) minmax(0,1fr); }
.asset-list { max-height: 680px; overflow: auto; border-right: 1px solid var(--border); }
.asset-list > button { width: 100%; min-height: 58px; display: grid; grid-template-columns: 24px minmax(0,1fr); align-items: center; gap: 8px; border: 0; border-bottom: 1px solid var(--border); background: #fff; color: var(--text-secondary); cursor: pointer; padding: 8px 10px; text-align: left; }
.asset-list > button:hover, .asset-list > button.active { background: var(--accent-soft); color: var(--accent); }
.asset-list > button span { min-width: 0; display: grid; gap: 3px; }
.asset-list strong, .asset-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-list strong { font-size: 10px; }
.asset-list small { color: var(--text-muted); font-size: 9px; }
.asset-detail { min-width: 0; display: grid; grid-template-rows: minmax(320px,1fr) auto auto; align-content: start; }
.preview { min-height: 320px; display: grid; place-items: center; overflow: hidden; background: #f6f7f9; color: var(--text-muted); }
.preview img, .preview video { width: 100%; height: 100%; max-height: 520px; object-fit: contain; }
.preview audio { width: min(90%, 620px); }
.asset-detail > header { min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid var(--border); padding: 10px 12px; }
.asset-detail > header div { min-width: 0; display: grid; gap: 3px; }
.asset-detail > header strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.binding-band { min-width: 0; display: grid; grid-template-columns: minmax(150px,1fr) auto auto; align-items: center; gap: 10px; border-top: 1px solid var(--border); padding: 9px 12px; }
.binding-heading { min-width: 0; display: flex; align-items: center; gap: 7px; color: var(--text-secondary); }
.binding-heading div { min-width: 0; display: grid; gap: 2px; }
.binding-heading strong, .provenance-group > strong { font-size: 10px; }
.binding-heading small, .scope-state, .provenance-row { color: var(--text-muted); font-size: 9px; }
.scope-control { display: inline-flex; align-items: stretch; overflow: hidden; border: 1px solid var(--border); border-radius: 7px; background: #fff; }
.scope-control button { min-height: 30px; border: 0; border-right: 1px solid var(--border); background: transparent; color: var(--text-secondary); padding: 5px 9px; font-size: 9px; cursor: pointer; }
.scope-control button:last-child { border-right: 0; }
.scope-control button.active { background: var(--accent-soft); color: var(--accent); }
.scope-control button:disabled { cursor: not-allowed; opacity: .45; }
.bind-button { min-height: 30px; display: inline-flex; align-items: center; justify-content: center; gap: 5px; border: 1px solid var(--accent); border-radius: 7px; background: var(--accent); color: #fff; padding: 5px 9px; font-size: 9px; cursor: pointer; }
.scope-state { display: inline-flex; align-items: center; gap: 4px; color: #387052; white-space: nowrap; }
.provenance-band { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; border-top: 1px solid var(--border); padding: 9px 12px; }
.provenance-group { min-width: 0; display: grid; align-content: start; gap: 5px; }
.provenance-row { min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.provenance-row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.provenance-row .icon-button { width: 26px; height: 26px; flex: 0 0 26px; display: grid; place-items: center; border: 0; border-radius: 6px; background: transparent; color: var(--text-muted); cursor: pointer; }
.provenance-row .icon-button:hover { background: var(--accent-soft); color: var(--accent); }
.provenance-row small { white-space: nowrap; }
.provenance-row small.stale { color: #a84040; }
.asset-actions { display: flex; flex-wrap: wrap; gap: 6px; border-top: 1px solid var(--border); padding: 9px 12px; }
.asset-actions button:hover { border-color: var(--accent); color: var(--accent); }
.asset-actions button.danger { margin-left: auto; color: #a84040; }
.media-empty { min-height: 240px; display: grid; place-items: center; color: var(--text-muted); padding: 20px; text-align: center; font-size: 11px; }
.media-empty.compact { min-height: 120px; }
.media-error { margin: 8px; border-radius: 7px; background: #fff0f0; color: #a84040; padding: 8px 10px; font-size: 10px; }
.spinning { animation: spin .8s linear infinite; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .media-toolbar { flex-wrap: wrap; }
  .media-body { grid-template-columns: 1fr; }
  .asset-list { max-height: 240px; border-right: 0; border-bottom: 1px solid var(--border); }
  .binding-band { grid-template-columns: 1fr; }
  .scope-control { width: 100%; }
  .scope-control button { flex: 1; }
  .provenance-band { grid-template-columns: 1fr; }
}
</style>
