export function LoadingState({
  title = "Loading",
  message = "Please wait while the page finishes loading."
}: {
  title?: string;
  message?: string;
}) {
  return (
    <section className="page-grid single-column public-page">
      <div className="hero-card">
        <p className="eyebrow">Loading</p>
        <h1>{title}</h1>
        <p className="lede">{message}</p>
      </div>
    </section>
  );
}
