<template>
  <div class="page-wrap">
    <header class="site-header">
      <div class="brand">
        <span class="brand-badge">X</span>
        <span>XP</span>
      </div>
    </header>

    <nav class="tabbar" aria-label="Primary">
      <NuxtLink to="/">Home</NuxtLink>
      <NuxtLink to="/wallet">Wallet</NuxtLink>
      <NuxtLink to="/billing">Buy XP</NuxtLink>
      <NuxtLink to="/xp">History</NuxtLink>
      <NuxtLink to="/tasks">Tasks</NuxtLink>
      <NuxtLink to="/automations">Automations</NuxtLink>
      <NuxtLink to="/connections">Connect</NuxtLink>
      <NuxtLink to="/settings">Security</NuxtLink>
    </nav>

    <main class="page">
      <slot />
    </main>

    <footer class="site-footer">
      XP · AI work, paid in bitcoin
    </footer>
  </div>
</template>

<script setup lang="ts">
useTelegram();
</script>
