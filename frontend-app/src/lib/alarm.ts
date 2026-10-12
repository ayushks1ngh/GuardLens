import { readPref, writePref } from "./storage";

const MUTE_KEY = "guardlens.alarmMuted";
export const isMuted = (): boolean => readPref(MUTE_KEY) === "1";
export const setMuted = (muted: boolean): void => writePref(MUTE_KEY, muted ? "1" : "0");

let ctx: AudioContext | null = null;

/** Browsers block audio until the user has interacted; call from a click to unlock it. */
export function unlockAudio(): void {
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    ctx = ctx ?? new Ctor();
    if (ctx.state === "suspended") void ctx.resume();
  } catch { /* no audio available */ }
}

/** Three short rising beeps. Silent (returns false) when muted or audio is unavailable. */
export function playAlarm(): boolean {
  if (isMuted()) return false;
  try {
    unlockAudio();
    if (!ctx) return false;
    const audio = ctx;
    [0, 0.28, 0.56].forEach((offset, i) => {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = "square";
      osc.frequency.value = 760 + i * 120;
      const t = audio.currentTime + offset;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
      osc.connect(gain).connect(audio.destination);
      osc.start(t); osc.stop(t + 0.22);
    });
    return true;
  } catch { return false; }
}
