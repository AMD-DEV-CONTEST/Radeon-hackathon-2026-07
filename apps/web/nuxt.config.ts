export default defineNuxtConfig({
  compatibilityDate: '2026-07-25',
  devtools: { enabled: false },
  ssr: false,
  css: ['~/assets/css/main.css'],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8080',
      runTransport: process.env.NUXT_PUBLIC_RUN_TRANSPORT || 'stream'
    }
  },
  app: {
    head: {
      title: 'XiangLens — Private Profile Image Agent',
      meta: [
        {
          name: 'description',
          content: 'Private, source-backed profile image review on AMD Radeon and ROCm.'
        }
      ]
    }
  }
})
