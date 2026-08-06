<script setup>
import { onMounted } from "vue";
import Sidebar from "./components/Sidebar.vue";
import LanguageSelectionDialog from "./components/LanguageSelectionDialog.vue";
import { localeSelectionRequired } from "./i18n/index.js";
import { useAppStore } from "./stores/app.js";

const store = useAppStore();

onMounted(() => {
  store.loadAuthStatus();
});
</script>

<template>
  <div class="app-layout">
    <Sidebar />
    <main class="main-content">
      <router-view />
    </main>
    <LanguageSelectionDialog v-if="localeSelectionRequired" />
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-app);
}
</style>
