import { useEffect, useState } from "react";

/** False on the server AND during hydration, true after. metal-fx renders a different DOM on the server than on the client, so mounting it during hydration throws a mismatch and React rebuilds the whole tree — which tears down metal-fx's shared WebGL renderer and re-creates it in the same tick, and its async context-lost event then marks the NEW renderer dead (rings never draw). Gate every MetalFx/MetalText on this. */
export function useMounted() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
