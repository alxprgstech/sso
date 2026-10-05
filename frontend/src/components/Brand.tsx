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
      <picture>
        {full && (
          <source media="(max-width: 639px)" srcSet="/brand/logo-mark.svg" />
        )}
        <img
          className="brand-art"
          src={full ? "/brand/logo.svg" : "/brand/logo-mark.svg"}
          alt="ALXPRGS"
          width={full ? 112 : 40}
          height={full ? 84 : 40}
          decoding="async"
        />
      </picture>
      <span className="font-semibold tracking-tight text-base">
        {!full && "ALXPRGS "}
        <span className="text-secondary font-normal">SSO</span>
      </span>
    </div>
  );
}
