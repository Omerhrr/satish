/**
 * "≈ ₦48,200" next to bitcoin amounts. Shown only on real bitcoin (mainnet):
 * test coins have no value. Display only; nothing is charged at this rate.
 */
const price = reactive({ ngn: 0, at: 0, loading: false });

export function usePrice() {
  const api = useXpApi();
  const config = useRuntimeConfig();
  const enabled = config.public.bitcoinNetwork === "mainnet";

  async function load() {
    if (!enabled || price.loading || (price.ngn && Date.now() - price.at < 120_000)) return;
    price.loading = true;
    try {
      const p = await api.btcPrice();
      price.ngn = p.btc_ngn;
      price.at = Date.now();
    } catch {
      /* no price: naira lines just stay hidden */
    } finally {
      price.loading = false;
    }
  }

  onMounted(load);

  /** "≈ ₦48,200" for an amount in sats, or "" when unknown / test network. */
  function naira(sats: number): string {
    if (!enabled || !price.ngn || !Number.isFinite(sats)) return "";
    const value = (sats / 1e8) * price.ngn;
    const rounded = value >= 100 ? Math.round(value) : Math.round(value * 100) / 100;
    return "≈ ₦" + rounded.toLocaleString("en-NG");
  }

  return { naira, enabled, load };
}
