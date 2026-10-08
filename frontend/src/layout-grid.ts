export type GridPosition = { column: number; row: number };
export type GridCard = GridPosition & {
  id: string;
  columns: number;
  rows: number;
};

export function gridPosition(
  x: number,
  y: number,
  width: number,
  columns: number,
): GridPosition {
  return {
    column: Math.max(
      1,
      Math.min(13 - columns, 1 + Math.round(x / ((width + 16) / 12))),
    ),
    row: Math.max(1, Math.min(2000, 1 + Math.round(y / 24))),
  };
}

export function placeGridCard(
  cards: GridCard[],
  id: string,
  position: GridPosition,
): GridCard[] {
  const selected = cards.find((card) => card.id === id);
  if (!selected) return cards;
  const placed: GridCard[] = [
    {
      ...selected,
      column: Math.max(1, Math.min(13 - selected.columns, position.column)),
      row: Math.max(1, position.row),
    },
  ];
  // The dragged card owns its chosen cells. Push intersecting cards down,
  // preserving their columns and dimensions instead of allowing overlap.
  for (const card of cards
    .filter((card) => card.id !== id)
    .sort((a, b) => a.row - b.row || a.column - b.column)) {
    let next = { ...card };
    let collision: GridCard | undefined;
    while (
      (collision = placed.find(
        (other) =>
          next.column < other.column + other.columns &&
          other.column < next.column + next.columns &&
          next.row < other.row + other.rows &&
          other.row < next.row + next.rows,
      ))
    ) {
      next = { ...next, row: collision.row + collision.rows };
    }
    placed.push(next);
  }
  return placed.sort((a, b) => a.row - b.row || a.column - b.column);
}
