import { normalizeEntity } from "./entities.js";
import { normalizeRelation } from "./relations.js";

export function buildGraphDataset(entities = [], relations = [], selectedId = "") {
  const nodeMap = new Map();
  entities.map(normalizeEntity).forEach((entity) => {
    if (!entity.id) return;
    nodeMap.set(entity.id, {
      id: entity.id,
      title: entity.title,
      type: entity.type,
      typeLabel: entity.typeLabel,
      summary: entity.summary,
      tags: entity.tags,
      isSelected: entity.id === selectedId,
      raw: entity.raw,
    });
  });

  const edges = relations.map(normalizeRelation).filter((relation) => relation.sourceId && relation.targetId);
  edges.forEach((edge) => {
    if (!nodeMap.has(edge.sourceId)) {
      nodeMap.set(edge.sourceId, {
        id: edge.sourceId,
        title: edge.sourceTitle,
        type: "concept",
        typeLabel: "实体",
        summary: "",
        tags: [],
        isSelected: edge.sourceId === selectedId,
        raw: {},
      });
    }
    if (!nodeMap.has(edge.targetId)) {
      nodeMap.set(edge.targetId, {
        id: edge.targetId,
        title: edge.targetTitle,
        type: "concept",
        typeLabel: "实体",
        summary: "",
        tags: [],
        isSelected: edge.targetId === selectedId,
        raw: {},
      });
    }
  });

  return {
    nodes: Array.from(nodeMap.values()),
    edges,
    selectedId,
  };
}

export function radialGraphLayout(dataset, width = 760, height = 520) {
  const centerX = width / 2;
  const centerY = height / 2;
  const selected = dataset.nodes.find((node) => node.id === dataset.selectedId);
  const others = dataset.nodes.filter((node) => node.id !== dataset.selectedId);
  const radius = Math.max(130, Math.min(width, height) * 0.34);
  const positioned = new Map();

  if (selected) {
    positioned.set(selected.id, { ...selected, x: centerX, y: centerY });
  }

  others.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(others.length, 1) - Math.PI / 2;
    positioned.set(node.id, {
      ...node,
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    });
  });

  if (!selected && dataset.nodes.length) {
    const cols = Math.ceil(Math.sqrt(dataset.nodes.length));
    dataset.nodes.forEach((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      positioned.set(node.id, {
        ...node,
        x: 120 + col * 150,
        y: 100 + row * 110,
      });
    });
  }

  return {
    width,
    height,
    nodes: dataset.nodes.map((node) => positioned.get(node.id) || node),
    edges: dataset.edges,
  };
}
