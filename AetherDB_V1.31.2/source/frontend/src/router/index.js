import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", name: "Home", component: () => import("../views/Home.vue") },
  { path: "/workspace", name: "Workspace", component: () => import("../views/Workspace.vue") },
  { path: "/worlds", name: "WorldList", component: () => import("../views/WorldList.vue") },
  { path: "/reader", name: "Reader", component: () => import("../views/Reader.vue") },
  { path: "/search", name: "Search", component: () => import("../views/Search.vue") },
  { path: "/graph", name: "Graph", component: () => import("../views/Graph.vue") },
  { path: "/import", name: "Import", component: () => import("../views/Import.vue") },
  { path: "/settings", name: "Settings", component: () => import("../views/Settings.vue") },
  { path: "/logs", name: "Logs", component: () => import("../views/Logs.vue") },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
