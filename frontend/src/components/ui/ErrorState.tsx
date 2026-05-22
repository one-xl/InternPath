export function ErrorState({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="error-state" role="alert">
      {message}
    </div>
  );
}
