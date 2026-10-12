/** One-line status under a drawing canvas that uses a camera snapshot as its background. */
export function SnapshotStatus({ loading, error, hasImage, onRefresh }: {
  loading: boolean; error: string; hasImage: boolean; onRefresh: () => void;
}) {
  return (
    <p className="hint" role="status">
      {loading ? "Getting a picture from the camera…"
        : error ? `${error} You can still draw on the blank grid.`
        : hasImage ? "Showing what the camera sees right now." : "Choose a camera to see its picture."}
      {" "}
      <button type="button" onClick={onRefresh} disabled={loading}>Refresh picture</button>
    </p>
  );
}
