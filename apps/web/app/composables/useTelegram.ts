/**
 * Telegram Mini App bridge (phase 2 head start).
 *
 * The SDK script is injected when running inside Telegram; outside Telegram
 * (plain browser, preview) everything degrades gracefully. Local storage is
 * NOT treated as a key vault - only display preferences live here.
 */

interface TelegramWebApp {
  initData: string;
  version: string;
  colorScheme: "light" | "dark";
  ready: () => void;
  expand: () => void;
  setHeaderColor?: (color: string) => void;
  openTelegramLink?: (url: string) => void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export function useTelegram() {
  const webApp = computed<TelegramWebApp | null>(() => window?.Telegram?.WebApp ?? null);

  onMounted(() => {
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
      window.Telegram.WebApp.setHeaderColor?.("#0b0e11");
    }
  });

  const isInsideTelegram = computed(() => webApp.value !== null);
  const initData = computed(() => webApp.value?.initData ?? "");

  return { webApp, isInsideTelegram, initData };
}
