<template>
  <div class="page-wrap">
    <header class="site-header">
      <div class="brand">
        <span class="brand-badge">S</span>
        <span>Satish</span>
      </div>
    </header>

    <nav class="tabbar" aria-label="Primary">
      <NuxtLink to="/">Wallet</NuxtLink>
      <NuxtLink to="/ai">AI assistant</NuxtLink>
      <NuxtLink to="/tasks">Tasks</NuxtLink>
      <NuxtLink to="/billing">Buy TK</NuxtLink>
      <NuxtLink to="/tk">TK history</NuxtLink>
      <NuxtLink to="/automations">Automations</NuxtLink>
      <NuxtLink to="/connections">Connect</NuxtLink>
      <NuxtLink to="/settings">Security</NuxtLink>
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
</script>
