<template>
  <div class="card center"><span class="spinner" /></div>
</template>

<script setup lang="ts">
// The wallet now lives on the home screen. Old links and bot buttons
// (/wallet?pay=..., /wallet?request=1) are forwarded with their query intact.
const route = useRoute();
await navigateTo({ path: "/", query: route.query }, { replace: true });
</script>
