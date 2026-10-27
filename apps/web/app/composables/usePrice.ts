/**
 * Bitcoin in your own money: "≈ ₦48,200" next to amounts, and typing ₦, $,
 * £ or any currency where an amount in sats is needed.
 *
 * Rates come from the Satish API (CoinGecko + open.er-api.com, cached on the
 * server). Display and conversion only: what is sent is always the sats
 * shown, never re-priced later. On the test network the coins have no value;
 * the conversion still works so demos read naturally, and the app labels it.
 */

const price = reactive({ rates: {} as Record<string, number>, at: 0, loading: false });
const CURRENCY_KEY = "satish_currency";

function initialCurrency(): string {
  try {
    const saved = localStorage.getItem(CURRENCY_KEY);
    if (saved) return saved;
  } catch {
    /* ignore */
  }
  // A sensible default from the phone's region; Satish is Nigeria-first.
  const region = (navigator.language || "").split("-")[1]?.toUpperCase();
  const byRegion: Record<string, string> = {
    NG: "NGN", GH: "GHS", KE: "KES", ZA: "ZAR", US: "USD", GB: "GBP", CA: "CAD", IN: "INR",
    EG: "EGP", UG: "UGX", TZ: "TZS", RW: "RWF", CM: "XAF", SN: "XOF", CI: "XOF", MA: "MAD",
    BR: "BRL", MX: "MXN", FR: "EUR", DE: "EUR", ES: "EUR", IT: "EUR", NL: "EUR", PT: "EUR", AE: "AED", SA: "SAR",
  };
  return (region && byRegion[region]) || "NGN";
}

const currency = ref<string>(typeof window !== "undefined" ? initialCurrency() : "NGN");

/** Currencies shown first in pickers. */
export const POPULAR_CURRENCIES = ["NGN", "USD", "EUR", "GBP", "GHS", "KES", "ZAR", "XOF", "XAF", "EGP", "CAD", "INR", "AED"];

export function usePrice() {
  const api = useXpApi();
  const config = useRuntimeConfig();
  const testnet = config.public.bitcoinNetwork !== "mainnet";

  async function load(force = false) {
    if (price.loading || (!force && price.at && Date.now() - price.at < 120_000)) return;
    price.loading = true;
    try {
      const r = await api.btcRates();
      price.rates = r.btc;
      price.at = Date.now();
    } catch {
      try {
        const p = await api.btcPrice(); // older servers
        price.rates = { NGN: p.btc_ngn, ...(p.btc_usd ? { USD: p.btc_usd } : {}) };
        price.at = Date.now();
      } catch {
        /* no prices: fiat lines just stay hidden */
      }
    } finally {
      price.loading = false;
    }
  }

  onMounted(() => void load());

  const currencies = computed(() => {
    const all = Object.keys(price.rates).sort();
    return [...POPULAR_CURRENCIES.filter((c) => all.includes(c)), ...all.filter((c) => !POPULAR_CURRENCIES.includes(c))];
  });

  function setCurrency(code: string) {
    currency.value = code;
    try {
      localStorage.setItem(CURRENCY_KEY, code);
    } catch {
      /* ignore */
    }
  }

  function format(value: number, code: string): string {
    const digits = value >= 100 ? 0 : value >= 1 ? 2 : 4;
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency: code, maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
    } catch {
      return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })} ${code}`;
    }
  }

  /** Value of `sats` in `code` (default: the user's currency), or null. */
  function toFiat(sats: number, code = currency.value): number | null {
    const rate = price.rates[code];
    if (!rate || !Number.isFinite(sats)) return null;
    return (sats / 1e8) * rate;
  }

  /** Sats for an amount of money, rounded to the nearest sat (null if unknown). */
  function toSats(amount: number, code = currency.value): number | null {
    const rate = price.rates[code];
    if (!rate || !Number.isFinite(amount) || amount < 0) return null;
    return Math.round((amount / rate) * 1e8);
  }

  /** "≈ ₦48,200" in the user's currency, or "" when unknown. */
  function fiat(sats: number, code = currency.value): string {
    const v = toFiat(sats, code);
    return v === null || !sats ? "" : "≈ " + format(v, code);
  }

  /** Kept for existing screens: same as fiat() in the user's currency. */
  function naira(sats: number): string {
    return fiat(sats);
  }

  return { naira, fiat, toFiat, toSats, format, currency, setCurrency, currencies, rates: price, testnet, enabled: true, load };
}
