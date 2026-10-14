/**
 * XP API access for the Mini App. Wraps the shared @xp/api-client with Nuxt
 * runtime config so transport mode (gateway XTransformPort vs. direct base)
 * stays deployment-specific.
 */

import { createXpClient, type XpClient } from "@xp/api-client";

let cached: XpClient | null = null;

export function useXpApi(): XpClient {
  if (cached) return cached;
  const config = useRuntimeConfig();
  cached = createXpClient({
    apiPort: config.public.apiPort || undefined,
    apiBase: config.public.apiBase || undefined,
  });
  return cached;
}
