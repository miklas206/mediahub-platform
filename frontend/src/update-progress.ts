import {
  redactOperationDetail,
  type OperationState,
} from "./operation-progress";

export function mergeUpdateConsole(
  previous: OperationState | undefined,
  next: OperationState,
): OperationState {
  const lines = [...(previous?.console || [])];
  const additions = next.console?.length ? next.console : [next.message];
  for (const raw of additions) {
    const line = redactOperationDetail(raw);
    if (!lines.includes(line)) lines.push(line);
  }
  return { ...next, console: lines.slice(-120) };
}

export function disconnectedUpdate(previous: OperationState): OperationState {
  return mergeUpdateConsole(previous, {
    ...previous,
    connectionLost: true,
    message:
      "Connection interrupted. Keeping the last update status while reconnecting…",
    console: [
      "Connection interrupted; waiting for MediaHub to respond. Last progress and steps are unchanged.",
    ],
  });
}
