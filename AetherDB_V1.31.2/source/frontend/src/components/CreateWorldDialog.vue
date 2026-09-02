<script setup>
import { computed, onMounted, ref } from "vue";
import { BookOpen, Database, FileText, X } from "@lucide/vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { activateBook, activateDatabase, createBook, createDatabase, initializeDatabase, updateBook } from "../api/settings.js";
import { useAppStore } from "../stores/app.js";

const props = defineProps({
  kind: { type: String, default: "world" },
});
const emit = defineEmits(["close", "created"]);
const router = useRouter();
const { t } = useI18n();
const store = useAppStore();
const databaseId = ref("");
const groupName = ref("");
const groupType = ref("");
const title = ref("");
const author = ref("");
const description = ref("");
const startMode = ref("blank");
const loading = ref(false);
const error = ref("");

const isGroup = computed(() => props.kind === "group");
const dialogTitle = computed(() => t(isGroup.value ? "新建分组" : "新建世界"));
const canSubmit = computed(() => isGroup.value
  ? Boolean(groupName.value.trim() && groupType.value.trim())
  : Boolean(databaseId.value && title.value.trim()));

const startModes = [
  { key: "blank", label: "空白开始", icon: BookOpen },
  { key: "text", label: "导入文本", icon: FileText },
  { key: "full_book", label: "导入整本书", icon: Database },
];

function safeBookId(value) {
  const ascii = value.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return ascii || `book_${Date.now().toString(36)}`;
}

function groupDescription() {
  const parts = [t("分组类型：{type}", { type: groupType.value.trim() })];
  if (description.value.trim()) parts.push(description.value.trim());
  return parts.join("\n\n");
}

async function createGroup() {
  const created = await createDatabase({
    name: groupName.value.trim(),
    author: author.value.trim(),
    description: groupDescription(),
  });
  const createdId = created?.database?.database_id;
  if (!createdId) throw new Error(t("后端未返回新分组标识"));
  await initializeDatabase(createdId);
  await activateDatabase(createdId);
  await activateBook("default");
  await store.fetchDashboard();
  store.notifyAction(t("分组“{name}”已创建，可以在其中添加世界", { name: groupName.value.trim() }));
}

async function createWorld() {
  await activateDatabase(databaseId.value);
  const bookId = safeBookId(title.value);
  const created = await createBook({ bookId, title: title.value.trim(), databaseId: databaseId.value });
  const createdBookId = created?.book_id;
  if (!createdBookId) throw new Error(t("后端未返回新世界标识"));
  if (author.value.trim() || description.value.trim()) {
    await updateBook(createdBookId, {
      title: title.value.trim(),
      author: author.value.trim(),
      description: description.value.trim(),
      databaseId: databaseId.value,
    });
  }
  await activateBook(createdBookId);
  await store.fetchDashboard();
  store.notifyAction(t("世界“{name}”已创建并归入所选分组", { name: title.value.trim() }));
  if (startMode.value !== "blank") {
    router.push({ path: "/import", query: { source: startMode.value, from: "create-world", database_id: databaseId.value, book_id: createdBookId } });
  }
}

async function submit() {
  if (!canSubmit.value) return;
  loading.value = true;
  error.value = "";
  try {
    if (isGroup.value) await createGroup();
    else await createWorld();
    emit("created");
    emit("close");
  } catch (err) {
    error.value = err?.detail?.message || err?.message || t("{action}失败", { action: dialogTitle.value });
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  if (!store.databases.length) await store.fetchDashboard();
  databaseId.value = store.activeDatabase?.database_id || store.databases[0]?.database_id || "";
});
</script>

<template>
  <div class="dialog-backdrop" @click.self="emit('close')">
    <form class="world-dialog" @submit.prevent="submit">
      <header>
        <div><span>{{ t(isGroup ? "世界数据库" : "分组内作品") }}</span><h2>{{ dialogTitle }}</h2><p>{{ t(isGroup ? "同一分组用于管理题材和规则体系相近的多部作品。" : "选择一个分组，将新世界作为该数据库中的一部作品创建。") }}</p></div>
        <button class="icon-button" type="button" :title="t('关闭')" @click="emit('close')"><X :size="18" /></button>
      </header>

      <div v-if="isGroup" class="form-grid">
        <div class="field-row"><label>{{ t("分组名称") }}</label><input v-model.trim="groupName" required maxlength="80" :placeholder="t('例如 东方幻想系列')" /></div>
        <div class="field-row"><label>{{ t("分组类型") }}</label><input v-model.trim="groupType" required maxlength="80" :placeholder="t('例如 东方幻想、硬科幻')" /></div>
        <div class="field-row"><label>{{ t("创建者") }}</label><input v-model.trim="author" maxlength="80" :placeholder="t('可选')" /></div>
        <div class="field-row full"><label>{{ t("分组说明") }}</label><textarea v-model="description" rows="4" maxlength="800" :placeholder="t('记录该分组下作品共享的题材边界与基础规则...')" /></div>
      </div>

      <template v-else>
        <div v-if="!store.databases.length" class="no-database"><Database :size="24" /><div><strong>{{ t("尚无可用分组") }}</strong><span>{{ t("请先关闭此窗口并使用“新建分组”。") }}</span></div></div>
        <div v-else class="form-grid">
          <div class="field-row full"><label>{{ t("所属分组") }}</label><select v-model="databaseId" required><option disabled value="">{{ t("选择目标分组") }}</option><option v-for="database in store.databases" :key="database.database_id" :value="database.database_id">{{ database.name || database.title || database.database_id }}</option></select></div>
          <div class="field-row"><label>{{ t("世界名称") }}</label><input v-model.trim="title" required maxlength="100" :placeholder="t('例如 苍云界海')" /></div>
          <div class="field-row"><label>{{ t("作者") }}</label><input v-model.trim="author" maxlength="80" :placeholder="t('可选')" /></div>
          <div class="field-row full"><label>{{ t("世界简介") }}</label><textarea v-model="description" rows="3" maxlength="800" :placeholder="t('记录这部作品独有的背景、主题和时间范围...')" /></div>
        </div>
        <div v-if="store.databases.length" class="start-mode"><span>{{ t("创建后") }}</span><div><button v-for="item in startModes" :key="item.key" type="button" :class="{ active: startMode === item.key }" @click="startMode = item.key"><component :is="item.icon" :size="16" />{{ t(item.label) }}</button></div></div>
      </template>

      <div v-if="error" class="error-notice">{{ error }}</div>
      <footer><button class="btn btn-secondary" type="button" @click="emit('close')">{{ t("取消") }}</button><button class="btn btn-primary" type="submit" :disabled="loading || !canSubmit">{{ t(loading ? "创建中..." : isGroup ? "创建分组" : "创建世界") }}</button></footer>
    </form>
  </div>
</template>

<style scoped>
.dialog-backdrop { position: fixed; inset: 0; z-index: 70; display: grid; place-items: center; padding: 20px; background: rgba(28,25,44,.45); }
.world-dialog { width: min(680px,100%); max-height: calc(100vh - 40px); overflow-y: auto; display: grid; gap: 18px; border-radius: 8px; background: #fff; box-shadow: 0 26px 80px rgba(28,25,44,.25); padding: 24px; }
.world-dialog > header { display: flex; justify-content: space-between; gap: 16px; }
.world-dialog header span { color: var(--accent); font-size: 11px; }
.world-dialog h2 { margin: 3px 0 5px; font-size: 21px; }
.world-dialog p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.icon-button { width: 34px; height: 34px; display: inline-grid; place-items: center; flex: 0 0 auto; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 13px; }
.form-grid .full { grid-column: 1 / -1; }
.start-mode { display: grid; gap: 8px; }
.start-mode > span { color: var(--text-secondary); font-size: 12px; }
.start-mode > div { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; }
.start-mode button { min-height: 38px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.start-mode button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.no-database { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 11px; border: 1px solid #e8cfaa; border-radius: 8px; background: #fff9ef; color: #9a5b18; padding: 14px; }
.no-database div { display: grid; gap: 3px; }
.no-database span { color: #8a755e; font-size: 11px; }
.error-notice { border-radius: 8px; background: #fff0f0; color: #a33f3f; padding: 10px 12px; font-size: 12px; }
footer { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 620px) { .form-grid, .start-mode > div { grid-template-columns: 1fr; } .form-grid .full { grid-column: auto; } }
</style>
