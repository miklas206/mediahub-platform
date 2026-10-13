// Keep persisted step IDs compatible with earlier drafts; step 6 was app installation.
export const normalizeSetupStep = (step: number) => step === 6 ? 7 : step;
export const adjacentSetupStep = (step: number, direction: -1 | 1) =>
  step === 5 && direction === 1 ? 7 : step === 7 && direction === -1 ? 5 : step + direction;
