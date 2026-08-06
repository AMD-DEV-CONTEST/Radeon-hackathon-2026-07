/**
 * Codec helpers: base64 <-> PCM conversion utilities.
 * 
 * Adapted from hf-realtime-voice reference implementation.
 */

/**
 * Convert ArrayBuffer (Int16 PCM) to base64 string.
 * Uses chunked encoding to avoid stack overflow on large buffers.
 */
export function base64FromArrayBuffer(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  const chunk = 0x8000;  // 32 KB chunks
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      bytes.subarray(i, Math.min(i + chunk, bytes.length))
    );
  }
  return btoa(binary);
}

/**
 * Convert base64 string to Uint8Array bytes.
 */
export function base64ToBytes(b64) {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

/**
 * Convert Int16Array PCM → Float32Array samples (-1.0 to 1.0).
 */
export function pcm16ToFloat32(int16Array) {
  const out = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    out[i] = int16Array[i] / 32768;
  }
  return out;
}

/**
 * Convert Float32Array samples (-1.0 to 1.0) → Int16Array PCM.
 */
export function float32ToPcm16(float32Array) {
  const out = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32Array[i]));
    out[i] = Math.round(clamped * 32767);
  }
  return out;
}
