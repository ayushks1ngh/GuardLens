import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Camera, FacePolicy, Meta, PersonRow } from "../types";

export const POLICY_CHOICES: { value: FacePolicy; label: string; help: string }[] = [
  { value: "label_only", label: "Only name people", help: "Show names on the video, never raise an alert because of a face." },
  { value: "alert_unknown", label: "Alert on unknown people", help: "Raise an alert when someone who is not enrolled is seen." },
  { value: "alert_watchlist", label: "Alert on watchlist people", help: "Raise an alert only when an enrolled person marked as watchlist is seen." },
];

export function FacesPage(_props: { meta: Meta | null }) {
  const [people, setPeople] = useState<PersonRow[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [policy, setPolicy] = useState<FacePolicy>("label_only");
  const [name, setName] = useState("");
  const [watchlist, setWatchlist] = useState(false);
  const [notes, setNotes] = useState("");
  const [captureCamera, setCaptureCamera] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const [p, c, pol] = await Promise.all([
      api<PersonRow[]>("/api/persons"), api<Camera[]>("/api/cameras"), api<{ policy: FacePolicy }>("/api/faces/policy"),
    ]);
    setPeople(p); setCameras(c); setPolicy(pol.policy);
    setCaptureCamera((current) => current ?? c[0]?.id ?? null);
  }, []);
  useEffect(() => { load().catch((e: Error) => setMessage(e.message)); }, [load]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    setMessage(""); setNotice("");
    try { await action(); setNotice(success); await load(); }
    catch (e) { setMessage(e instanceof ApiError ? e.message : "Something went wrong."); }
  };

  const add = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) { setMessage("Enter the person's name."); return; }
    void run(async () => {
      await api("/api/persons", { method: "POST", json: { name: name.trim(), watchlist, notes: notes.trim() || null } });
      setName(""); setWatchlist(false); setNotes("");
    }, "Person added. Now add at least one clear photo of their face.");
  };

  const upload = (person: PersonRow, file: File | undefined) => {
    if (!file) return;
    const form = new FormData(); form.append("image", file);
    void run(() => api(`/api/persons/${person.id}/images`, { method: "POST", body: form }), `Photo added for ${person.name}.`);
  };
  const capture = (person: PersonRow) => {
    if (captureCamera === null) { setMessage("Choose a camera first."); return; }
    void run(() => api(`/api/persons/${person.id}/capture`, { method: "POST", json: { camera_id: captureCamera } }),
      `Captured a photo of ${person.name} from the camera.`);
  };
  const remove = (person: PersonRow) => {
    if (!window.confirm(`Remove ${person.name} and all of their photos?`)) return;
    void run(() => api(`/api/persons/${person.id}`, { method: "DELETE" }), `${person.name} removed.`);
  };
  const choosePolicy = (value: FacePolicy) => {
    void run(() => api("/api/faces/policy", { method: "PATCH", json: { policy: value } }), "Face alert setting saved.");
  };

  return (
    <section>
      <header className="page-head"><h2>Faces</h2></header>
      <p className="card privacy-note" role="note">
        <strong>Privacy:</strong> only enrol people who have agreed to it. Face photos are stored on this device and are
        used only to recognise the people you add. Remove someone here at any time to delete their photos.
      </p>

      <fieldset className="card">
        <legend>When a face is recognised</legend>
        {POLICY_CHOICES.map((choice) => (
          <label key={choice.value} className="choice">
            <input type="radio" name="face-policy" checked={policy === choice.value} onChange={() => choosePolicy(choice.value)} />
            <span><strong>{choice.label}</strong><span className="hint block">{choice.help}</span></span>
          </label>
        ))}
      </fieldset>

      <form className="card" onSubmit={add}>
        <h3>Add a person</h3>
        <div className="schema-form">
          <div className="field"><label htmlFor="person-name">Name</label>
            <input id="person-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="field"><label htmlFor="person-notes">Notes (optional)</label>
            <input id="person-notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
          <div className="field">
            <label className="switch"><input type="checkbox" role="switch" checked={watchlist} onChange={(e) => setWatchlist(e.target.checked)} />
              <span>Watchlist person: {watchlist ? "yes" : "no"}</span></label>
            <p className="hint">Mark people you want to be alerted about. This cannot be changed later; remove and re-add to change it.</p>
          </div>
        </div>
        <div className="actions"><button type="submit" className="primary">Add person</button></div>
      </form>

      {message && <p className="error" role="alert">{message}</p>}
      {notice && <p className="hint" role="status">{notice}</p>}

      {cameras.length > 0 && (
        <p className="field"><label htmlFor="capture-camera">Camera for “Take photo from camera”</label>
          <select id="capture-camera" value={captureCamera ?? ""} onChange={(e) => setCaptureCamera(Number(e.target.value))}>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></p>
      )}

      <ul className="list">
        {people.map((person) => (
          <li key={person.id} className="row wrap">
            <div className="grow">
              <strong>{person.name}</strong> {person.watchlist && <span className="badge warning">Watchlist</span>}
              <div className="hint">
                {person.image_count === 0 ? "No photos yet. Recognition needs at least one." : `${person.image_count} photo${person.image_count === 1 ? "" : "s"}`}
                {person.notes ? ` · ${person.notes}` : ""}
              </div>
            </div>
            <label className="button-like">
              Upload photo
              <input type="file" accept="image/*" className="sr-only" aria-label={`Upload a photo of ${person.name}`}
                onChange={(e) => { upload(person, e.target.files?.[0]); e.target.value = ""; }} />
            </label>
            <button type="button" onClick={() => capture(person)} disabled={captureCamera === null}>Take photo from camera</button>
            <button type="button" onClick={() => remove(person)}>Remove</button>
          </li>
        ))}
        {!people.length && <li className="hint">Nobody is enrolled yet.</li>}
      </ul>
    </section>
  );
}
