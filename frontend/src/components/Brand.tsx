/** Official ALXPRGS artwork, bundled locally; see public/brand/source-manifest.json. */
export function Brand({
  variant = "navigation",
}: {
  variant?: "auth" | "navigation";
}) {
  const full = variant === "auth";
  return (
    <div
      className={`brand-identity brand-${variant}`}
      data-testid="brand-identity"
    >
      {full && (
        <svg
          className="brand-art brand-full"
          viewBox="0 0 1448 1086"
          width={112}
          height={84}
          role="img"
          aria-label="ALXPRGS"
        >
          <use href="/brand/logo-adaptive.svg#logo" />
        </svg>
      )}
      <img
        className={`brand-art${full ? " brand-compact" : ""}`}
        src="/brand/logo-mark.svg"
        alt="ALXPRGS"
        width={full ? 44 : 40}
        height={full ? 44 : 40}
        decoding="async"
      />
      <span className="font-semibold tracking-tight text-base">
        {!full && "ALXPRGS "}
        <span className="text-secondary font-normal">SSO</span>
      </span>
    </div>
  );
}
