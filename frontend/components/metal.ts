// ONE import point for metal-fx — import from here, never from "metal-fx" directly, or the patch below is skipped.
export * from "metal-fx";

// metal-fx disposes its shared offscreen WebGL renderer with loseContext() when the last instance unmounts. The resulting "webglcontextlost" event fires ASYNCHRONOUSLY and its handler flips contextLost on the module-global renderer — which is the NEW one whenever a renderer was created in between (dev StrictMode remount, landing -> dashboard navigation). That renderer then never draws: every ring stays hidden (black tiles, no border). Offscreen contexts are garbage-collected without it, so make the call a no-op for them. Remove when metal-fx scopes that handler to its own renderer.
if (typeof WebGL2RenderingContext !== "undefined" && typeof OffscreenCanvas !== "undefined") {
  const getExtension = WebGL2RenderingContext.prototype.getExtension;
  WebGL2RenderingContext.prototype.getExtension = function (this: WebGL2RenderingContext, name: string) {
    if (name === "WEBGL_lose_context" && this.canvas instanceof OffscreenCanvas) return null;
    return (getExtension as (this: WebGL2RenderingContext, n: string) => unknown).call(this, name);
  } as typeof getExtension;
}
