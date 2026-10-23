<template>
  <div class="page-wrap">
    <header class="site-header">
      <div class="brand">
        <span class="brand-badge">S</span>
        <span>Satish</span>
      </div>
    </header>

    <nav class="maintabs" aria-label="Main">
      <NuxtLink to="/" :class="{ on: group === 'wallet' }">💰 Wallet</NuxtLink>
      <NuxtLink to="/ai" :class="{ on: group === 'ai' }">🤖 Satish AI</NuxtLink>
    </nav>

    <nav class="tabbar" :aria-label="group === 'ai' ? 'Satish AI' : 'Wallet'">
      <template v-if="group === 'wallet'">
        <NuxtLink v-for="t in walletTabs" :key="t.key" :to="t.key === 'home' ? '/' : { path: '/', query: { s: t.key } }" :class="{ on: walletOn(t.key) }">
          {{ t.label }}
        </NuxtLink>
      </template>
      <template v-else>
        <NuxtLink v-for="t in aiTabs" :key="t.to" :to="t.to" :class="{ on: route.path === t.to }">{{ t.label }}</NuxtLink>
      </template>
    </nav>

    <main class="page">
      <slot />
    </main>

    <footer class="site-footer">
      Satish · your bitcoin wallet in Telegram
    </footer>
  </div>
</template>

<script setup lang="ts">
useTelegram();
const route = useRoute();

const AI_PATHS = ["/ai", "/tasks", "/automations", "/billing", "/tk", "/xp", "/connections"];
const group = computed(() => (AI_PATHS.some((p) => route.path === p || route.path.startsWith(p + "/")) ? "ai" : "wallet"));

const walletTabs = [
  { key: "home", label: "Home" },
  { key: "history", label: "History" },
  { key: "activity", label: "Activity" },
  { key: "contacts", label: "Address book" },
  { key: "settings", label: "Settings" },
];
const aiTabs = [
  { to: "/ai", label: "Assistant" },
  { to: "/tasks", label: "Tasks" },
  { to: "/automations", label: "Automations" },
  { to: "/billing", label: "Buy TK" },
  { to: "/tk", label: "TK history" },
  { to: "/connections", label: "Connect" },
];

function walletOn(key: string) {
  if (route.path === "/settings" || route.path === "/recovery") return key === "settings";
  if (route.path !== "/") return false;
  return ((route.query.s as string) || "home") === key;
}
</script>
