/**
 * Telegram login: when the Mini App opens inside Telegram, exchange the
 * signed initData for an XP session before any page calls the API.
 * Outside Telegram (plain browser) nothing happens and DEV_MODE applies.
 */
import { useXpApi } from "~/composables/useXpApi";

export default defineNuxtPlugin(async () => {
  const tg = window.Telegram?.WebApp;
  if (!tg || !tg.initData) return;
  tg.ready();
  tg.expand();
  try {
    const session = await useXpApi().authTelegram(tg.initData);
    sessionStorage.setItem("xp_session_token", session.session_token);
    localStorage.removeItem("xp_session_token");
  } catch (e) {
    console.error("[xp] Telegram login failed", e);
  }
});
