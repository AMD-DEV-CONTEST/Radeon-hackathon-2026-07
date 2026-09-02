import { createApp } from "vue";
import { createPinia } from "pinia";
import DesktopBootstrap from "./components/DesktopBootstrap.vue";
import router from "./router/index.js";
import { i18n } from "./i18n/index.js";
import "./styles/main.css";

const app = createApp(DesktopBootstrap);
app.use(createPinia());
app.use(router);
app.use(i18n);
app.mount("#app");
