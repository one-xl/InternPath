export function LoadingState({ label = "正在处理..." }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="spinner" />
      {label}
    </div>
  );
}
