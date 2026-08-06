<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getEntities, getRelations } from "../api/entities.js";
import { buildGraphDataset, radialGraphLayout } from "../domain/graph.js";
import { normalizeEntityList } from "../domain/entities.js";
import { normalizeRelationList } from "../domain/relations.js";

const entities = ref([]);
const { t } = useI18n();
const relations = ref([]);
const selectedId = ref("");
const loading = ref(true);
const relationLoading = ref(false);
const error = ref("");

const selectedEntity = computed(() => entities.value.find((entity) => entity.id === selectedId.value));
const dataset = computed(() => buildGraphDataset(entities.value, relations.value, selectedId.value));
const layout = computed(() => radialGraphLayout(dataset.value, 760, 520));

async function loadEntities() {
  loading.value = true;
  error.value = "";
  try {
    const payload = await getEntities({ limit: 80 });
    entities.value = normalizeEntityList(payload);
    if (!selectedId.value && entities.value.length) {
      await selectEntity(entities.value[0].id);
    }
  } catch (err) {
    error.value = err.message || t("图谱数据加载失败");
  } finally {
    loading.value = false;
  }
}

async function selectEntity(id) {
  selectedId.value = id;
  relationLoading.value = true;
  error.value = "";
  try {
    relations.value = normalizeRelationList(await getRelations(id, "both"));
  } catch (err) {
    relations.value = [];
    error.value = err.message || t("关系加载失败");
  } finally {
    relationLoading.value = false;
  }
}

function nodeById(id) {
  return layout.value.nodes.find((node) => node.id === id);
}

function edgeLine(edge) {
  const source = nodeById(edge.sourceId);
  const target = nodeById(edge.targetId);
  if (!source || !target) return null;
  return { source, target };
}

onMounted(loadEntities);
</script>

<template>
  <div class="page-shell graph-page">
    <header class="page-header">
      <div>
        <h1>{{ t("知识图谱") }}</h1>
        <p>{{ t("以实体和关系为中心浏览世界结构。当前渲染层可替换，后续可接入 D3 力导向布局。") }}</p>
      </div>
      <span class="status-pill">{{ t("{nodes} 节点 / {edges} 关系", { nodes: dataset.nodes.length, edges: dataset.edges.length }) }}</span>
    </header>

    <div class="graph-layout">
      <aside class="panel entity-panel">
        <h2 class="panel-title">{{ t("实体索引") }}</h2>
        <div v-if="loading" class="empty-state"><strong>{{ t("正在加载实体") }}</strong></div>
        <div v-else-if="!entities.length" class="empty-state">
          <strong>{{ t("暂无实体") }}</strong>
          <small>{{ t("导入或创建实体后，图谱会在这里形成节点。") }}</small>
        </div>
        <div v-else class="entity-list">
          <button
            v-for="entity in entities"
            :key="entity.id"
            type="button"
            :class="{ active: selectedId === entity.id }"
            @click="selectEntity(entity.id)"
          >
            <strong>{{ entity.title }}</strong>
            <small>{{ t(entity.typeLabel) }} · {{ t("{count} 关系", { count: entity.relationCount }) }}</small>
          </button>
        </div>
      </aside>

      <main class="panel graph-canvas">
        <div v-if="error" class="notice">{{ error }}</div>
        <div v-if="!dataset.nodes.length" class="empty-state">
          <strong>{{ t("图谱等待数据") }}</strong>
          <small>{{ t("这里不会使用静态示例。实体与关系来自接口返回。") }}</small>
        </div>
        <svg v-else class="graph-svg" :viewBox="`0 0 ${layout.width} ${layout.height}`" role="img" :aria-label="t('实体关系图谱')">
          <g class="edges">
            <template v-for="edge in layout.edges" :key="edge.id">
              <g v-if="edgeLine(edge)">
                <line
                  :x1="edgeLine(edge).source.x"
                  :y1="edgeLine(edge).source.y"
                  :x2="edgeLine(edge).target.x"
                  :y2="edgeLine(edge).target.y"
                />
                <text
                  :x="(edgeLine(edge).source.x + edgeLine(edge).target.x) / 2"
                  :y="(edgeLine(edge).source.y + edgeLine(edge).target.y) / 2"
                >
                  {{ edge.type }}
                </text>
              </g>
            </template>
          </g>
          <g class="nodes">
            <g
              v-for="node in layout.nodes"
              :key="node.id"
              class="node"
              :class="{ selected: node.id === selectedId }"
              role="button"
              tabindex="0"
              @click="selectEntity(node.id)"
            >
              <circle :cx="node.x" :cy="node.y" :r="node.id === selectedId ? 42 : 34" />
              <text :x="node.x" :y="node.y + 4">{{ node.title.slice(0, 8) }}</text>
            </g>
          </g>
        </svg>
        <div v-if="relationLoading" class="loading-line">{{ t("正在加载关系...") }}</div>
      </main>

      <aside class="panel detail-panel">
        <h2 class="panel-title">{{ t("节点详情") }}</h2>
        <div v-if="selectedEntity" class="detail-content">
          <span class="status-pill">{{ t(selectedEntity.typeLabel) }}</span>
          <h3>{{ selectedEntity.title }}</h3>
          <p>{{ selectedEntity.summary || t("暂无摘要") }}</p>
          <div class="tag-list">
            <span v-for="tag in selectedEntity.tags" :key="tag" class="tag">{{ tag }}</span>
          </div>
          <h4>{{ t("相关关系") }}</h4>
          <div v-if="relations.length" class="relation-list">
            <div v-for="relation in relations" :key="relation.id" class="relation-item">
              <strong>{{ relation.sourceTitle }} → {{ relation.targetTitle }}</strong>
              <small>{{ relation.type }}</small>
            </div>
          </div>
          <div v-else class="empty-state compact">
            <strong>{{ t("暂无关系") }}</strong>
          </div>
        </div>
        <div v-else class="empty-state">
          <strong>{{ t("未选择节点") }}</strong>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.graph-layout {
  display: grid;
  grid-template-columns: 260px minmax(520px, 1fr) 300px;
  gap: 18px;
}

.entity-panel,
.detail-panel {
  max-height: calc(100vh - 120px);
  overflow: auto;
}

.entity-list {
  display: grid;
  gap: 8px;
}

.entity-list button {
  display: grid;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  padding: 10px;
}

.entity-list button.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.entity-list small,
.relation-item small {
  color: var(--text-secondary);
  font-size: 12px;
}

.graph-canvas {
  position: relative;
  min-height: 620px;
  overflow: hidden;
}

.notice,
.loading-line {
  position: absolute;
  z-index: 2;
  top: 14px;
  left: 14px;
  border-radius: 8px;
  background: #fff7ed;
  color: #9a5b18;
  padding: 8px 10px;
  font-size: 12px;
}

.loading-line {
  top: auto;
  bottom: 14px;
  background: var(--accent-soft);
  color: var(--accent);
}

.graph-svg {
  width: 100%;
  height: 560px;
}

.edges line {
  stroke: #d8d1ee;
  stroke-width: 1.5;
}

.edges text {
  fill: var(--text-muted);
  font-size: 11px;
  text-anchor: middle;
}

.node {
  cursor: pointer;
}

.node circle {
  fill: #fff;
  stroke: var(--accent);
  stroke-width: 2;
  filter: drop-shadow(0 8px 18px rgba(114, 87, 232, 0.18));
}

.node.selected circle {
  fill: var(--accent);
}

.node text {
  fill: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
  text-anchor: middle;
  pointer-events: none;
}

.node.selected text {
  fill: #fff;
}

.detail-content {
  display: grid;
  gap: 12px;
}

.detail-content h3 {
  font-size: 20px;
}

.detail-content p {
  color: var(--text-secondary);
  line-height: 1.7;
  font-size: 13px;
}

.detail-content h4 {
  font-size: 14px;
}

.relation-list {
  display: grid;
  gap: 8px;
}

.relation-item {
  display: grid;
  gap: 4px;
  border-radius: 8px;
  background: var(--bg-secondary);
  padding: 10px;
}

.compact {
  min-height: 70px;
}

@media (max-width: 1180px) {
  .graph-layout {
    grid-template-columns: 1fr;
  }

  .entity-panel,
  .detail-panel {
    max-height: none;
  }
}
</style>
