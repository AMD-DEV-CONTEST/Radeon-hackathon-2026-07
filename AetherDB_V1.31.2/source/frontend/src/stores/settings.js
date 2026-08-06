import { defineStore } from "pinia";

export const useSettingsStore = defineStore("settings", {
  state: () => ({
    theme: "light",
    apiKey: "",
    apiBase: "/api",
  }),
  actions: {
    setTheme(t) {
      this.theme = t;
      document.documentElement.setAttribute("data-theme", t);
    },
    setApiKey(key) {
      this.apiKey = key;
    },
  },
});
