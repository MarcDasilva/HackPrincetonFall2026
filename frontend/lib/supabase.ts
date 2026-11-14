import { createBrowserClient } from "@supabase/ssr";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// createBrowserClient THROWS at construction when either value is missing — an unguarded call here crashes every page that imports this file. NEXT_PUBLIC_* values are inlined at build time, so restart `next dev` after editing .env.local.
export const supabase = url && key ? createBrowserClient(url, key) : null;
