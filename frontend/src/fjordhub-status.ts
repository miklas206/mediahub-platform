export type FjordHubInstallation = {
  state: string;
  verification?: { state: string };
  uninstall?: { state: string };
};

export function isFjordHubInstalled(
  job: FjordHubInstallation | null | undefined,
) {
  if (
    !job ||
    job.verification?.state === "removed" ||
    job.uninstall?.state === "removed"
  )
    return false;
  return job.state === "succeeded";
}
