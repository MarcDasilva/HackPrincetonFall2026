import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

// false during server rendering and hydration, true once running in the browser.
// Gate browser-only components (WebGL, canvas) on it so the server HTML and the first
// client render match; otherwise React throws a hydration mismatch.
export function useMounted(): boolean {
  return useSyncExternalStore(subscribe, () => true, () => false);
}
