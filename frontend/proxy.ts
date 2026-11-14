import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// gates /dashboard on a verified Supabase user — getUser() hits the auth server, getSession() would trust a forgeable cookie. Callback route (app/auth/callback) owns the other half: it sets the session cookie.
export async function proxy(request: NextRequest) {
  const response = NextResponse.next({ request });
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        // Refreshed tokens must be written to the response — dropping them logs the user out mid-session.
        setAll: (all) => all.forEach(({ name, value, options }) => response.cookies.set(name, value, options)),
      },
    },
  );
  const { data } = await supabase.auth.getUser();
  if (!data.user) return NextResponse.redirect(new URL("/", request.url));
  return response;
}

export const config = { matcher: "/dashboard/:path*" };
