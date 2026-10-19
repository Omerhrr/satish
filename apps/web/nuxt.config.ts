// XP Telegram Mini App - Nuxt 4 configuration.
// SPA mode: Telegram Mini Apps load inside a webview where SSR adds no value
// and complicates auth; the app talks to the FastAPI service directly.
export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  ssr: false,
  devtools: { enabled: false },
  srcDir: "app/",
  typescript: { strict: true, typeCheck: false },
  runtimeConfig: {
    public: {
      // Sandbox gateway mode: NUXT_PUBLIC_API_PORT="8001" makes the app call
      // same-origin paths with ?XTransformPort=8001 (single exposed port).
      apiPort: process.env.NUXT_PUBLIC_API_PORT || "",
      // Direct mode (local dev on your machine): full API origin.
      apiBase: process.env.NUXT_PUBLIC_API_BASE || "http://127.0.0.1:8001",
      appName: "XP"
    }
  },
  app: {
    head: {
      title: "XP - Bitcoin-Native AI Workforce",
      htmlAttrs: { lang: "en" },
      meta: [
        { charset: "utf-8" },
        { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" },
        { name: "theme-color", content: "#0b0e11" },
        {
          name: "description",
          content:
            "Self-custody Bitcoin wallet + AI work platform, native to Telegram. Pay for research and documents in sats via XP credits."
        }
      ],
      script: [{ src: "https://telegram.org/js/telegram-web-app.js" }],
      link: [
        {
          rel: "icon",
          type: "image/svg+xml",
          href:
            "data:image/svg+xml," +
            encodeURIComponent(
              '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="15" fill="#f7931a"/><text x="16" y="22" font-size="16" font-family="Arial" font-weight="bold" text-anchor="middle" fill="#0b0e11">X</text></svg>'
            )
        }
      ]
    }
  }
})
