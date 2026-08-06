<script setup>
import { computed, reactive, ref, watch } from "vue";
import { X } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { createEntity } from "../api/entities.js";
import { useAppStore } from "../stores/app.js";

const props = defineProps({
  entityType: { type: Object, required: true },
});
const emit = defineEmits(["close", "created"]);
const store = useAppStore();
const { t } = useI18n();
const loading = ref(false);
const error = ref("");
const tagsText = ref("");
const targetBookId = ref(store.activeBook?.book_id || "default");
const importance = ref(5);
const form = reactive({});

const CONFIGS = {
  character: {
    titleLabel: "角色姓名",
    fields: [
      { key: "age", label: "首次出现年龄", type: "number", min: 0, max: 999, placeholder: "故事开始或首次出现时的年龄" },
      { key: "gender", label: "性别", type: "select", options: ["未设定", "女", "男", "非二元", "其他"] },
      { key: "personality", label: "性格", type: "textarea", full: true, placeholder: "核心性格、行为倾向、优点与缺点..." },
      { key: "life_events", label: "人生经历 / 事件", type: "textarea", full: true, placeholder: "每行记录一项重要经历；后续可通过“创建事件”建立独立事件实体。" },
    ],
  },
  faction: { titleLabel: "势力名称", fields: [
    { key: "category", label: "组织类型", placeholder: "国家、宗门、商会、军团..." }, { key: "leader", label: "领导者", placeholder: "可选" },
    { key: "purpose", label: "目标与立场", type: "textarea", full: true }, { key: "history", label: "发展历史", type: "textarea", full: true },
  ] },
  location: { titleLabel: "地点名称", fields: [
    { key: "region", label: "所属区域", placeholder: "例如 北境" }, { key: "environment", label: "环境类型", placeholder: "城市、荒原、遗迹..." },
    { key: "features", label: "地理与人文特征", type: "textarea", full: true }, { key: "history", label: "历史与现状", type: "textarea", full: true },
  ] },
  event: { titleLabel: "事件名称", fields: [
    { key: "time", label: "发生时间", placeholder: "年份、纪元或相对时间" }, { key: "participants", label: "参与者", placeholder: "角色或势力，使用逗号分隔" },
    { key: "cause", label: "起因", type: "textarea", full: true }, { key: "process", label: "过程", type: "textarea", full: true }, { key: "outcome", label: "结果与影响", type: "textarea", full: true },
  ] },
  item: { titleLabel: "物品名称", fields: [
    { key: "category", label: "物品类型", placeholder: "武器、遗物、工具..." }, { key: "owner", label: "持有者 / 归属", placeholder: "可选" },
    { key: "origin", label: "来源与历史", type: "textarea", full: true }, { key: "ability", label: "能力与限制", type: "textarea", full: true },
  ] },
  concept: { titleLabel: "概念名称", fields: [
    { key: "category", label: "概念类别", placeholder: "文化、宗教、哲学、术语..." }, { key: "definition", label: "定义", type: "textarea", full: true }, { key: "influence", label: "影响范围", type: "textarea", full: true },
  ] },
  rule: { titleLabel: "规则名称", fields: [
    { key: "scope", label: "适用范围", placeholder: "整个世界、某地区或某体系" }, { key: "conditions", label: "触发条件", type: "textarea", full: true },
    { key: "effects", label: "规则效果", type: "textarea", full: true }, { key: "exceptions", label: "例外与代价", type: "textarea", full: true },
  ] },
  system: { titleLabel: "系统名称", fields: [
    { key: "category", label: "系统类型", placeholder: "魔法、科技、政治、经济..." }, { key: "components", label: "组成部分", type: "textarea", full: true },
    { key: "mechanism", label: "运行机制", type: "textarea", full: true }, { key: "limitations", label: "限制与风险", type: "textarea", full: true },
  ] },
};

const config = computed(() => CONFIGS[props.entityType.key]);
const targetBooks = computed(() => {
  const books = store.books.filter((book) => book.book_id !== "default");
  return [{ book_id: "default", title: t("分组公共设定") }, ...books];
});

watch(config, (value) => {
  Object.keys(form).forEach((key) => delete form[key]);
  form.title = "";
  value.fields.forEach((field) => { form[field.key] = field.type === "select" ? field.options[0] : ""; });
}, { immediate: true });

function buildContent() {
  const lines = [`# ${form.title.trim()}`];
  for (const field of config.value.fields) {
    const value = String(form[field.key] ?? "").trim();
    if (!value || value === "未设定") continue;
    lines.push(`\n## ${t(field.label)}\n${value}`);
  }
  return lines.join("\n");
}

function parseTags() {
  return [...new Set(tagsText.value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean))].slice(0, 30);
}

async function submit() {
  if (!form.title.trim() || !store.activeDatabase?.database_id) return;
  loading.value = true;
  error.value = "";
  try {
    const result = await createEntity({
      entity_type: props.entityType.key,
      title: form.title.trim(),
      content: buildContent(),
      tags: parseTags(),
      importance: Number(importance.value),
      book_id: targetBookId.value,
    });
    store.notifyAction(t("{type}“{name}”已写入当前分组", {
      type: t(props.entityType.label.replace("创建", "")),
      name: form.title.trim(),
    }));
    await store.fetchStats();
    emit("created", result);
    emit("close");
  } catch (err) {
    error.value = err?.detail?.message || err?.message || t("实体创建失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="dialog-backdrop" @click.self="emit('close')">
    <form class="entity-dialog" @submit.prevent="submit">
      <header><div><span>{{ t("快速创建 · {name}", { name: store.activeDatabase?.name || store.activeDatabase?.title || store.activeDatabase?.database_id }) }}</span><h2>{{ t(entityType.label) }}</h2><p>{{ t("保存后直接写入当前分组；选择具体世界时同时归入对应作品。") }}</p></div><button class="icon-button" type="button" :title="t('关闭')" @click="emit('close')"><X :size="18" /></button></header>
      <div class="form-grid">
        <div class="field-row full"><label>{{ t(config.titleLabel) }}</label><input v-model.trim="form.title" required maxlength="200" :placeholder="t('输入{label}', { label: t(config.titleLabel) })" /></div>
        <div v-for="field in config.fields" :key="field.key" class="field-row" :class="{ full: field.full }">
          <label>{{ t(field.label) }}</label>
          <select v-if="field.type === 'select'" v-model="form[field.key]"><option v-for="option in field.options" :key="option" :value="option">{{ t(option) }}</option></select>
          <textarea v-else-if="field.type === 'textarea'" v-model="form[field.key]" rows="3" maxlength="4000" :placeholder="field.placeholder ? t(field.placeholder) : t('填写{label}', { label: t(field.label) })" />
          <input v-else v-model="form[field.key]" :type="field.type || 'text'" :min="field.min" :max="field.max" maxlength="300" :placeholder="field.placeholder ? t(field.placeholder) : t('填写{label}', { label: t(field.label) })" />
        </div>
        <div class="field-row"><label>{{ t("归属范围") }}</label><select v-model="targetBookId"><option v-for="book in targetBooks" :key="book.book_id" :value="book.book_id">{{ book.title || book.book_id }}</option></select></div>
        <div class="field-row"><label>{{ t("重要程度") }}</label><select v-model.number="importance"><option v-for="value in 10" :key="value" :value="value">{{ value }}{{ value === 5 ? ` · ${t("普通")}` : value === 10 ? ` · ${t("核心")}` : "" }}</option></select></div>
        <div class="field-row full"><label>{{ t("标签") }}</label><input v-model="tagsText" maxlength="500" :placeholder="t('使用逗号分隔，例如 主角，北境，第一卷')" /></div>
      </div>
      <div v-if="error" class="error-notice">{{ error }}</div>
      <footer><button class="btn btn-secondary" type="button" @click="emit('close')">{{ t("取消") }}</button><button class="btn btn-primary" type="submit" :disabled="loading || !form.title.trim()">{{ t(loading ? "保存中..." : "保存实体") }}</button></footer>
    </form>
  </div>
</template>

<style scoped>
.dialog-backdrop { position: fixed; inset: 0; z-index: 72; display: grid; place-items: center; padding: 20px; background: rgba(28,25,44,.45); }
.entity-dialog { width: min(760px,100%); max-height: calc(100vh - 40px); overflow-y: auto; display: grid; gap: 18px; border-radius: 8px; background: #fff; box-shadow: 0 26px 80px rgba(28,25,44,.25); padding: 24px; }
.entity-dialog > header { display: flex; justify-content: space-between; gap: 16px; }
.entity-dialog header span { color: var(--accent); font-size: 11px; }
.entity-dialog h2 { margin: 3px 0 5px; font-size: 21px; }
.entity-dialog p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.icon-button { width: 34px; height: 34px; display: grid; place-items: center; flex: 0 0 auto; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 13px; }
.form-grid .full { grid-column: 1 / -1; }
.error-notice { border-radius: 8px; background: #fff0f0; color: #a33f3f; padding: 10px 12px; font-size: 12px; }
footer { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } .form-grid .full { grid-column: auto; } }
</style>
