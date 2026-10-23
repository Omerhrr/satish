<template>
  <div class="page-wrap">
    <nav v-if="showSubTabs" class="tabbar" :aria-label="group === 'ai' ? 'Satish AI' : 'Wallet'">
      <template v-if="group === 'wallet'">
        <NuxtLink v-for="t in walletTabs" :key="t.key" :to="t.key === 'home' ? '/' : { path: '/', query: { s: t.key } }" :class="{ on: walletOn(t.key) }">
          {{ t.label }}
        </NuxtLink>
      </template>
      <template v-else>
        <NuxtLink v-for="t in aiTabs" :key="t.to" :to="t.to" :class="{ on: aiOn(t) }">{{ t.label }}</NuxtLink>
      </template>
    </nav>

    <main class="page">
      <slot />
    </main>

    <nav class="bottomnav" aria-label="Main">
      <NuxtLink to="/" :class="{ on: group === 'wallet' }">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H18a1 1 0 0 1 1 1v2h.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-14A2.5 2.5 0 0 1 3 16.5v-9Zm2.5-.5a.5.5 0 0 0 0 1H17V7H5.5ZM16 13.25a1.25 1.25 0 1 0 2.5 0 1.25 1.25 0 0 0-2.5 0Z" /></svg>
        Wallet
      </NuxtLink>
      <NuxtLink to="/tasks" :class="{ on: group === 'ai' }">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l1.9 4.6 4.6 1.9-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.9L12 2.5Zm6.5 11 .95 2.3 2.3.95-2.3.95-.95 2.3-.95-2.3-2.3-.95 2.3-.95.95-2.3ZM6 15l.75 1.75L8.5 17.5l-1.75.75L6 20l-.75-1.75L3.5 17.5l1.75-.75L6 15Z" /></svg>
        Satish AI
      </NuxtLink>
    </nav>
  </div>
</template>

<script setup lang="ts">
useTelegram();
const route = useRoute();

const AI_PATHS = ["/ai", "/tasks", "/automations", "/billing", "/tk", "/xp", "/connections"];
const wallet = useWallet();
const group = computed(() => (AI_PATHS.some((p) => route.path === p || route.path.startsWith(p + "/")) ? "ai" : "wallet"));

const walletTabs = [
  { key: "home", label: "Home" },
  { key: "history", label: "History" },
  { key: "activity", label: "Activity" },
  { key: "contacts", label: "Address book" },
  { key: "settings", label: "Settings" },
];
const aiTabs = [
  { to: "/tasks", label: "Ask", also: ["/ai"] },
  { to: "/automations", label: "Automations", also: [] },
  { to: "/billing", label: "Credits", also: ["/tk", "/xp"] },
  { to: "/connections", label: "Connect", also: [] },
];

// Wallet sub-tabs only make sense once there is a wallet.
const showSubTabs = computed(() => group.value === "ai" || !!wallet.state.stored);

function aiOn(t: { to: string; also: string[] }) {
  return route.path === t.to || t.also.includes(route.path);
}

function walletOn(key: string) {
  if (route.path === "/settings" || route.path === "/recovery") return key === "settings";
  if (route.path !== "/") return false;
  return ((route.query.s as string) || "home") === key;
}
</script>
