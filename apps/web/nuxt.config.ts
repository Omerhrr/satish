// Satish Telegram Mini App - Nuxt 4 configuration.
// SPA mode: Telegram Mini Apps load inside a webview where SSR adds no value
// and complicates auth; the app talks to the FastAPI service directly.
// Two builds from one app: the Telegram Mini App (default) and the Satish
// browser extension (SATISH_TARGET=extension, see scripts/build-extension.mjs).
const isExtension = process.env.SATISH_TARGET === "extension";

export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  ssr: false,
  // Extension pages are files (chrome-extension://id/index.html): hash routes.
  router: isExtension ? { options: { hashMode: true } } : {},
  // Import maps must be inline, which extension pages forbid.
  experimental: isExtension ? { entryImportMap: false } : {},
  // Serve pre-compressed files (the Lightning module is 12 MB raw, about 4 MB with brotli).
  nitro: { compressPublicAssets: { gzip: true, brotli: true } },
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
      appName: "Satish",
      // "telegram" (Mini App) or "extension" (browser extension build).
      platform: isExtension ? "extension" : "telegram",
      // Wallet network: "testnet" (default, free test coins) or "mainnet".
      bitcoinNetwork: process.env.NUXT_PUBLIC_BITCOIN_NETWORK || "testnet",
      // Optional custom Esplora API; defaults to mempool.space for the network.
      esploraUrl: process.env.NUXT_PUBLIC_ESPLORA_URL || "",
      // Telegram bot username (without @), for "Pay with Satish on Telegram" links.
      botUsername: process.env.NUXT_PUBLIC_BOT_USERNAME || "",
      // Mainnet beta: above this balance (sats) the wallet suggests moving savings elsewhere.
      walletBetaLimitSats: process.env.NUXT_PUBLIC_WALLET_BETA_LIMIT_SATS || "1000000",
      // Lightning (Breez SDK, Spark). Network defaults to "regtest" (free test coins, no key)
      // with a testnet wallet, and "mainnet" with a mainnet wallet, which needs a Breez API key
      // (free from https://breez.technology/request-api-key/). It's a client key, safe to ship.
      lightningNetwork: process.env.NUXT_PUBLIC_LIGHTNING_NETWORK || "",
      breezApiKey: process.env.NUXT_PUBLIC_BREEZ_API_KEY || ""
    }
  },
  app: {
    // Chrome refuses extensions with files or folders starting with "_" (Nuxt's default is /_nuxt/).
    ...(isExtension ? { buildAssetsDir: "/assets/" } : {}),
    head: {
      title: isExtension ? "Satish" : "Satish - your bitcoin wallet in Telegram",
      htmlAttrs: { lang: "en" },
      meta: [
        { charset: "utf-8" },
        { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" },
        { name: "theme-color", content: "#0b0e11" },
        {
          name: "description",
          content:
            "Satish: a self-custodial bitcoin wallet in Telegram. Send, receive, pay by @username, and pay an AI assistant with bitcoin."
        }
      ],
      // Extensions may not load remote scripts; Telegram's SDK is only for the Mini App.
      script: isExtension ? [] : [{ src: "https://telegram.org/js/telegram-web-app.js" }],
      link: [
        { rel: "icon", type: "image/png", sizes: "32x32", href: "/icon-32.png" },
        { rel: "icon", type: "image/png", sizes: "192x192", href: "/icon-192.png" },
        { rel: "apple-touch-icon", href: "/icon-180.png" }
      ]
    }
  }
})
