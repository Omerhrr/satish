/**
 * App look: an accent colour and a light or dark mode. Saved on this device only.
 *
 * The accent drives --orange (the name is historical: every accent-coloured
 * thing in the app reads it), --orange-soft and --on-accent (text drawn on
 * top of the accent). "auto" mode follows Telegram's theme, or the device's.
 */

export type ThemeMode = "dark" | "light" | "auto";

export interface Accent {
  id: string;
  name: string;
  /** used on dark backgrounds */
  dark: string;
  /** a deeper shade that stays readable on white */
  light: string;
  /** text on top of the accent */
  on: string;
}

export const ACCENTS: Accent[] = [
  { id: "orange", name: "Bitcoin orange", dark: "#f7931a", light: "#e07a00", on: "#14181f" },
  { id: "gold", name: "Lightning gold", dark: "#facc15", light: "#b48600", on: "#14181f" },
  { id: "blue", name: "Ocean blue", dark: "#3b82f6", light: "#2563eb", on: "#ffffff" },
  { id: "green", name: "Naira green", dark: "#22c55e", light: "#15803d", on: "#ffffff" },
  { id: "teal", name: "Teal", dark: "#14b8a6", light: "#0f766e", on: "#ffffff" },
  { id: "purple", name: "Purple", dark: "#a855f7", light: "#7e22ce", on: "#ffffff" },
  { id: "pink", name: "Pink", dark: "#ec4899", light: "#be185d", on: "#ffffff" },
  { id: "red", name: "Red", dark: "#ef4444", light: "#b91c1c", on: "#ffffff" },
];

const KEY_MODE = "satish_theme_mode";
const KEY_ACCENT = "satish_theme_accent";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: the choice lasts this visit */
  }
}

const mode = ref<ThemeMode>("dark");
const accentId = ref("orange");
let started = false;

function systemIsLight(): boolean {
  const tg = (window as any).Telegram?.WebApp;
  if (tg?.initData && tg.colorScheme) return tg.colorScheme === "light";
  return !!window.matchMedia?.("(prefers-color-scheme: light)").matches;
}

function hexToRgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

export function applyTheme() {
  if (typeof document === "undefined") return;
  const light = mode.value === "light" || (mode.value === "auto" && systemIsLight());
  const accent = ACCENTS.find((a) => a.id === accentId.value) || ACCENTS[0]!;
  const color = light ? accent.light : accent.dark;
  const root = document.documentElement;
  root.dataset.mode = light ? "light" : "dark";
  root.dataset.accent = accent.id;
  root.style.setProperty("--orange", color);
  root.style.setProperty("--orange-rgb", hexToRgb(color));
  root.style.setProperty("--orange-soft", `rgba(${hexToRgb(color)}, ${light ? 0.12 : 0.14})`);
  root.style.setProperty("--on-accent", accent.on);
  const bg = light ? "#f5f6f8" : "#0b0e11";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  const tg = (window as any).Telegram?.WebApp;
  try {
    tg?.setHeaderColor?.(bg);
    tg?.setBackgroundColor?.(bg);
  } catch {
    /* older Telegram */
  }
}

export function startTheme() {
  if (started || typeof window === "undefined") return;
  started = true;
  const m = read(KEY_MODE);
  if (m === "dark" || m === "light" || m === "auto") mode.value = m;
  const a = read(KEY_ACCENT);
  if (a && ACCENTS.some((x) => x.id === a)) accentId.value = a;
  applyTheme();
  window.matchMedia?.("(prefers-color-scheme: light)").addEventListener?.("change", () => mode.value === "auto" && applyTheme());
  (window as any).Telegram?.WebApp?.onEvent?.("themeChanged", () => mode.value === "auto" && applyTheme());
}

export function useTheme() {
  startTheme();
  function setMode(m: ThemeMode) {
    mode.value = m;
    write(KEY_MODE, m);
    applyTheme();
  }
  function setAccent(id: string) {
    accentId.value = id;
    write(KEY_ACCENT, id);
    applyTheme();
  }
  return { mode: readonly(mode), accentId: readonly(accentId), setMode, setAccent, ACCENTS };
}
