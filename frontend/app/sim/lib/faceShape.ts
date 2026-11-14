"use client";
// Face landmarks for the head-shape fit (backend hornsim/head_shape.py), run in the browser so the
// front photo never leaves the device: only the 478 normalised landmarks are sent. MediaPipe's face
// landmarker follows the skin outline, so hair does not count toward the head's shape.
import type { FaceLandmarker } from "@mediapipe/tasks-vision";

const VERSION = "1.2.0"; // keep in step with package.json
const WASM = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION}/wasm`;
const MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

let landmarker: Promise<FaceLandmarker> | null = null;

/** MediaPipe's WASM runtime prints its TFLite/glog status lines ("INFO: Created TensorFlow Lite XNNPACK
 * delegate for CPU.", "W0000 ...") through console.error, which the Next.js dev overlay reports as
 * errors. Drop only those lines while `fn` runs (and its WASM calls, which are synchronous). */
const MEDIAPIPE_LOG = /^(INFO:|WARNING:|[IW]\d{4} )|TensorFlow Lite|XNNPACK|gl_context|landmark_projection_calculator/;
async function quietly<T>(fn: () => Promise<T> | T): Promise<T> {
  const orig = console.error;
  console.error = (...args: unknown[]) => {
    if (typeof args[0] === "string" && MEDIAPIPE_LOG.test(args[0])) return;
    orig(...args);
  };
  try { return await fn(); } finally { console.error = orig; }
}

function load() {
  landmarker ??= quietly(async () => {
    const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
    const files = await FilesetResolver.forVisionTasks(WASM);
    const make = (delegate: "GPU" | "CPU") => FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: MODEL, delegate },
      runningMode: "IMAGE", numFaces: 2, outputFacialTransformationMatrixes: true,
    });
    try { return await make("GPU"); } catch { return await make("CPU"); }
  });
  landmarker.catch(() => { landmarker = null; });   // let a later attempt retry after a network failure
  return landmarker;
}

// ---------------------------------------------------------------- ear photos
// A side-on ear photo turns the face too far for the landmarker, but BlazeFace (the face detector)
// still finds it, with keypoints for the eyes, nose tip, mouth and both ear tragions.
const DETECTOR = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";
const EYE_TO_MOUTH_MM = 70;    // adult mean, eye line to mouth centre: sizes the ear box
const EAR_BOX_MM = [75, 90];   // around the ear (adult ear ~62 mm tall) with room for error
let detector: Promise<import("@mediapipe/tasks-vision").FaceDetector> | null = null;

function loadDetector() {
  detector ??= quietly(async () => {
    const { FaceDetector, FilesetResolver } = await import("@mediapipe/tasks-vision");
    const files = await FilesetResolver.forVisionTasks(WASM);
    return FaceDetector.createFromOptions(files, { baseOptions: { modelAssetPath: DETECTOR, delegate: "CPU" }, runningMode: "IMAGE", minDetectionConfidence: 0.5 });
  });
  detector.catch(() => { detector = null; });
  return detector;
}

export type EarLocation = { side: "left" | "right"; box: [number, number, number, number]; score: number };

/** Which ear an ear photo shows, and a box around it in the photo's pixels, or null if no face is found.
 * Side: the nose points away from the visible ear's side of the head. In a camera image that is NOT
 * mirrored, a nose pointing to the image's left means the subject's left ear faces the camera. Mirrored
 * selfies (some phone and Photo Booth settings) swap this, which is why the chat lets you change it. */
export async function locateEar(img: HTMLImageElement): Promise<EarLocation | null> {
  const det = await loadDetector();
  const r = await quietly(() => det.detect(img));
  const best = [...r.detections].sort((a, b) => (b.categories[0]?.score ?? 0) - (a.categories[0]?.score ?? 0))[0];
  if (!best || best.keypoints.length < 6) return null;
  const W = img.naturalWidth, H = img.naturalHeight;
  const k = best.keypoints.map((p) => [p.x * W, p.y * H]);
  const [eyeR, eyeL, nose, mouth, tragR, tragL] = k;
  const eyeX = (eyeR[0] + eyeL[0]) / 2, eyeY = (eyeR[1] + eyeL[1]) / 2;
  const away = nose[0] < eyeX ? 1 : -1;                    // +1: ear is to the image's right of the nose
  const side = away > 0 ? "left" : "right";
  // the visible ear's tragion is the one farther from the nose; the ear sits just behind it
  const trag = Math.abs(tragR[0] - nose[0]) > Math.abs(tragL[0] - nose[0]) ? tragR : tragL;
  const mmPerPx = EYE_TO_MOUTH_MM / Math.max(8, Math.hypot(mouth[0] - eyeX, mouth[1] - eyeY));
  const cx = trag[0] + (away * 8) / mmPerPx, cy = trag[1] + 5 / mmPerPx;
  const bw = EAR_BOX_MM[0] / mmPerPx, bh = EAR_BOX_MM[1] / mmPerPx;
  const clamp = (v: number, hi: number) => Math.round(Math.min(hi - 1, Math.max(0, v)));
  return { side, box: [clamp(cx - bw / 2, W), clamp(cy - bh / 2, H), clamp(cx + bw / 2, W), clamp(cy + bh / 2, H)], score: best.categories[0]?.score ?? 0 };
}

export type FaceResult ={ landmarks: number[][]; image_w: number; image_h: number; yaw_deg: number | null };

/** Landmarks of the one face in `img`, or an error a person can act on. */
export async function detectFace(img: HTMLImageElement): Promise<FaceResult> {
  const lm = await load();
  const r = await quietly(() => lm.detect(img));   // the first detect builds the CPU delegate and logs about it
  if (!r.faceLandmarks.length) throw new Error("No face found. Use a well-lit photo looking straight at the camera.");
  if (r.faceLandmarks.length > 1) throw new Error("More than one face in the photo. Use a photo of just the patient.");
  const pts = r.faceLandmarks[0];
  if (pts.length < 478) throw new Error("The face landmarker returned no iris points; try a sharper photo.");
  // yaw from the face's rotation matrix (column-major 4x4): atan2(R02, R22)
  const m = r.facialTransformationMatrixes?.[0]?.data;
  const yaw = m ? (Math.atan2(m[8], m[10]) * 180) / Math.PI : null;
  return { landmarks: pts.map((p) => [p.x, p.y, p.z]), image_w: img.naturalWidth, image_h: img.naturalHeight, yaw_deg: yaw };
}
