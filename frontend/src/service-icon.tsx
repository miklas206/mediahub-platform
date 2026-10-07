import {
  Box,
  FolderSymlink,
  House,
  Film,
  Shield,
  MapPin,
  Camera,
  Package,
  Globe,
  ChartNoAxesCombined,
  type LucideProps,
} from "lucide-react";

// Only artwork with verified redistribution permission is bundled. These are
// ordinary interface icons, not approximations of unlicensed product marks.
const fjordFallbacks = {
  fjordhub: House,
  fjordflix: Film,
  fjordvpn: Shield,
  "urban-explorer": MapPin,
  urbanexplorer: MapPin,
  fjordlens: Camera,
  fjordparcel: Package,
  orbitmap: Globe,
  fjordbudget: ChartNoAxesCombined,
};

/** Product marks identify services; interface actions still use the Lucide line family. */
export function ServiceIcon({
  packageId,
  size = 24,
  className,
  ...props
}: LucideProps & { packageId: string }) {
  const id = packageId.toLowerCase();
  const appId = id.replace(/^org\.mediahub\./, "");
  const Fallback = fjordFallbacks[appId as keyof typeof fjordFallbacks];
  if (Fallback)
    return (
      <Fallback
        size={size}
        className={className}
        data-brand-fallback={appId}
        {...props}
      />
    );
  if (["fjord3d", "jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"].includes(appId))
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        className={className}
        aria-hidden={props["aria-label"] ? undefined : true}
        {...props}
      >
        <image href={`/assets/services/${appId}.png`} width="32" height="32" />
      </svg>
    );
  if (id === "org.mediahub.windows-share")
    return <FolderSymlink size={size} className={className} {...props} />;
  const brand = id.includes("plex")
    ? "plex"
    : /seedbox|qbittorrent/.test(id)
      ? "qbittorrent"
      : /cloudflare/.test(id)
        ? "cloudflare"
        : id.includes("docker")
          ? "docker"
          : id.includes("fjordhub")
            ? "fjordhub"
            : /mediahub.*core|^mediahub$|^core$/.test(id)
              ? "mediahub"
              : undefined;
  if (!brand) return <Box size={size} className={className} {...props} />;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden={props["aria-label"] ? undefined : true}
      role={props["aria-label"] ? "img" : undefined}
      className={["service-mark", `service-mark-${brand}`, className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    >
      {brand === "plex" ? (
        <>
          <circle cx="16" cy="16" r="15" fill="#131d26" stroke="#705a21" />
          <path d="M10 6h6l8 10-8 10h-6l8-10Z" fill="#e8ad27" />
        </>
      ) : brand === "qbittorrent" ? (
        <>
          <circle cx="16" cy="16" r="15" fill="#1684df" />
          <image
            href="/assets/services/qbittorrent.svg"
            x="1"
            y="1"
            width="30"
            height="30"
          />
        </>
      ) : brand === "fjordhub" ? (
        <image href="/assets/services/fjordhub.png" width="32" height="32" />
      ) : brand === "mediahub" ? (
        <image href="/favicon.svg" width="32" height="32" />
      ) : (
        <image
          href={`/assets/services/${brand}.svg`}
          x="1"
          y="1"
          width="30"
          height="30"
        />
      )}
    </svg>
  );
}
