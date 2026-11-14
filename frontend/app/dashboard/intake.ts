"use client";
// Photos from the dashboard chat -> what /sim needs: a patient record per ear (POST /api/patients runs
// the ear pipeline) and a head shape from a front photo (face landmarks found in the browser, fitted by
// POST /api/sim/head_shapes; the face photo itself is never uploaded).
import { createHeadShape, type HeadShapeFit } from "../sim/lib/api";
import { detectFace, locateEar, type EarLocation } from "../sim/lib/faceShape";

export type PhotoKind = "left" | "right" | "face";
export const KIND_LABEL: Record<PhotoKind, string> = { left: "Left ear", right: "Right ear", face: "Front face" };

async function toImage(blob: Blob) {
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.src = url;
  try {
    await img.decode();
  } catch {
    URL.revokeObjectURL(url);
    throw new Error("this browser cannot open that photo; use JPEG or PNG");
  }
  return { img, done: () => URL.revokeObjectURL(url) };
}

/** What a photo shows. A face the landmarker finds looking roughly at the camera is a front photo;
 * otherwise it is an ear photo, and the face detector (if it finds the turned face) says which ear and
 * where it is. ear = null: no face found (e.g. a close-up of just the ear), so side and box are unknown. */
export async function classifyPhoto(blob: Blob): Promise<{ kind: "face" } | { kind: "ear"; ear: EarLocation | null }> {
  const { img, done } = await toImage(blob);
  try {
    try {
      const f = await detectFace(img);
      if (f.yaw_deg === null || Math.abs(f.yaw_deg) < 35) return { kind: "face" };
    } catch { /* not a front photo */ }
    return { kind: "ear", ear: await locateEar(img).catch(() => null) };
  } finally {
    done();
  }
}

export async function fitHead(blob: Blob): Promise<HeadShapeFit> {
  const { img, done } = await toImage(blob);
  try {
    return await createHeadShape(await detectFace(img));
  } finally {
    done();
  }
}

/** Start the ear pipeline for one side. `box` (photo pixels) is where the ear is, from locateEar; without
 * one the whole photo is used, which only works when the ear fills most of the frame (SAM 2 picks the
 * object at the box's centre). */
export async function uploadEar(blob: Blob, side: "left" | "right", earBox?: [number, number, number, number]): Promise<string> {
  let box: string;
  if (earBox) box = earBox.join(",");
  else {
    const { img, done } = await toImage(blob);
    const w = img.naturalWidth, h = img.naturalHeight;
    done();
    const m = 0.04;
    box = [w * m, h * m, w * (1 - m), h * (1 - m)].map(Math.round).join(",");
  }
  const fd = new FormData();
  fd.append("photo", blob, `${side}-ear.jpg`);
  fd.append("box", box);
  fd.append("side", side);
  const r = await fetch("/api/patients", { method: "POST", body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ? String(j.detail) : `upload failed (HTTP ${r.status})`);
  return j.id as string;
}

export type PatientJob = {
  status: "queued" | "running" | "done" | "error"; step: string | null; error?: string; log?: string[];
  results?: { side_check?: { side: string; fit: Record<string, number>; margin: number; agrees: boolean }; [k: string]: unknown };
};
export const patientStatus = (id: string) => fetch(`/api/patients/${id}`).then((r) => (r.ok ? r.json() as Promise<PatientJob> : Promise.reject(new Error(`HTTP ${r.status}`))));

/** /sim can use an ear once its context step has run (the scene grid needs the ear mesh and canal fit). */
export const earReadyForSim = (j: PatientJob) => j.status === "done" || !!j.results?.context;
