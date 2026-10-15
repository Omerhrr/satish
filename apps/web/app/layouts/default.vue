<template>
  <div class="page-wrap">
    <header class="site-header">
      <div class="brand">
        <span class="brand-badge">X</span>
        <span>XP</span>
      </div>
      <span class="env-chip">{{ envLabel }}</span>
    </header>

    <nav class="tabbar" aria-label="Primary">
      <NuxtLink to="/">Console</NuxtLink>
      <NuxtLink to="/wallet">Wallet</NuxtLink>
      <NuxtLink to="/billing">Billing</NuxtLink>
      <NuxtLink to="/xp">XP</NuxtLink>
      <NuxtLink to="/tasks">Tasks</NuxtLink>
      <NuxtLink to="/settings">Security</NuxtLink>
    </nav>

    <main class="page">
      <slot />
    </main>

    <footer class="site-footer">
      XP · Bitcoin-native AI workforce · Phase 1 scaffold — self-custody is real:
      your keys, your bitcoin, never stored by this service.
    </footer>
  </div>
</template>

<script setup lang="ts">
const { isInsideTelegram } = useTelegram();
const envLabel = computed(() =>
  isInsideTelegram.value ? "telegram mini app" : "dev preview"
);
</script>
