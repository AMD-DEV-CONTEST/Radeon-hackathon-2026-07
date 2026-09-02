<script setup>
import { Languages } from "@lucide/vue";
import { setLocale } from "../i18n/index.js";


function choose(locale) {
  setLocale(locale);
}
</script>

<template>
  <div class="language-gate" role="presentation">
    <section
      class="language-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="language-dialog-title"
      aria-describedby="language-dialog-description"
    >
      <div class="language-mark" aria-hidden="true">
        <Languages :size="24" />
      </div>
      <h1 id="language-dialog-title">选择界面语言</h1>
      <p class="english-heading">Choose your language</p>
      <p id="language-dialog-description" class="language-description">
        语言选择会保存在此设备上，之后可在设置中随时更改。
      </p>
      <div class="language-actions">
        <button type="button" class="language-choice" aria-label="使用简体中文" @click="choose('zh-CN')">
          <strong>简体中文</strong>
          <span>Chinese (Simplified)</span>
        </button>
        <button type="button" class="language-choice" aria-label="Use English" @click="choose('en-US')">
          <strong>English</strong>
          <span>英语 / English</span>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.language-gate {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(16, 19, 24, 0.72);
  backdrop-filter: blur(10px);
}

.language-dialog {
  width: min(440px, 100%);
  padding: 28px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-surface);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28);
  color: var(--text-primary);
}

.language-mark {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  margin-bottom: 18px;
  border-radius: 6px;
  background: var(--accent-primary);
  color: white;
}

h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.3;
  letter-spacing: 0;
}

.english-heading {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 16px;
}

.language-description {
  margin: 18px 0 22px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.language-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.language-choice {
  min-width: 0;
  min-height: 82px;
  padding: 14px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--bg-app);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.language-choice:hover,
.language-choice:focus-visible {
  border-color: var(--accent-primary);
  outline: none;
}

.language-choice strong,
.language-choice span {
  display: block;
  overflow-wrap: anywhere;
  letter-spacing: 0;
}

.language-choice span {
  margin-top: 5px;
  color: var(--text-secondary);
  font-size: 12px;
}

@media (max-width: 520px) {
  .language-actions {
    grid-template-columns: 1fr;
  }
}
</style>
