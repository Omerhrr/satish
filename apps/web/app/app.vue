<script setup lang="ts">
// Global design system - imported directly so SPA mode always bundles it.
import "~/assets/css/main.css";

// Extension mode: sign in with Telegram (bot code) before anything else.
const { isExtension, takePending, onPending } = usePlatform();
const signedIn = ref(!isExtension);
const checking = ref(isExtension);
const router = useRouter();

async function checkSession() {
  try {
    if (!localStorage.getItem("xp_session_token")) throw new Error("none");
    await useXpApi().me();
    signedIn.value = true;
    void handlePending();
  } catch {
    try {
      localStorage.removeItem("xp_session_token");
    } catch {
      /* ignore */
    }
    signedIn.value = false;
  } finally {
    checking.value = false;
  }
}

/** Right-click "Ask Satish AI" / "Pay with Satish" from the background. */
async function handlePending() {
  const p = await takePending();
  if (!p) return;
  if (p.type === "ask") await router.push({ path: "/tasks", query: { ask: p.text } });
  else await router.push({ path: "/", query: { pay: p.uri } });
}

onMounted(() => {
  if (!isExtension) return;
  void checkSession();
  const off = onPending(() => signedIn.value && void handlePending());
  onBeforeUnmount(off);
});
</script>

<template>
  <div v-if="checking" class="boot"><span class="spinner" /></div>
  <ExtensionSignIn v-else-if="!signedIn" @signed-in="checkSession" />
  <NuxtLayout v-else>
    <NuxtPage />
  </NuxtLayout>
</template>

<style>
.boot { display: grid; place-items: center; min-height: 60vh; }
</style>
