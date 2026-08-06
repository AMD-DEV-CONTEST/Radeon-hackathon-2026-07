import '@unocss/reset/tailwind.css'
import 'uno.css'
import '@/rendering/markdown/styles.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import { useStartupStore } from './stores/startup'
import { useAppUpdateStore } from './stores/appUpdate'

// Naive UI
import naive from 'naive-ui'

async function bootstrap() {
  const app = createApp(App)
  const pinia = createPinia()

  app.use(pinia)
  app.use(router)
  app.use(naive)

  app.mount('#app')
  void useAppUpdateStore(pinia).checkAtStartup()
  await useStartupStore(pinia).initialize()
}

void bootstrap().catch((error) => {
  console.error('Application initialization failed:', error)
})
