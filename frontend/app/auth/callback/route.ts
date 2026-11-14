import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  const { origin, searchParams } = request.nextUrl;
  const code = searchParams.get("code");
  if (code) {
    const store = await cookies();
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll: () => store.getAll(),
          setAll: (all) => all.forEach(({ name, value, options }) => store.set(name, value, options)),
        },
      },
    );
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    // The popup flow (components/GoogleSignIn.tsx) sets this cookie. Its window must NOT navigate to /dashboard — it tells the landing page and closes, so the landing page stays loaded and plays the outro.
    if (request.cookies.get("auris_popup")) {
      const res = new NextResponse(
        `<!doctype html><script>try{opener.postMessage(${error ? '"auris-failed"' : '"auris-signed-in"'},location.origin)}catch(e){}close()</script>You can close this window.`,
        { headers: { "content-type": "text/html" } },
      );
      res.cookies.delete("auris_popup");
      return res;
    }
  }
  return NextResponse.redirect(`${origin}/dashboard`);
}
