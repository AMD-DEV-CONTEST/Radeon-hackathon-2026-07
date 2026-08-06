const { defineConfig } = require("vite");
const vue = require("@vitejs/plugin-vue");
const { viteSingleFile } = require("vite-plugin-singlefile");

module.exports = defineConfig({
    plugins: [
        vue(),
        viteSingleFile(),
    ],
});
