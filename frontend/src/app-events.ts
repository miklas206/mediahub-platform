export function batchAppHealthRefresh(refresh: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    changed() {
      if (timer !== undefined) return;
      // The stream reports each app separately, including its initial snapshot.
      timer = setTimeout(() => {
        timer = undefined;
        refresh();
      }, 100);
    },
    dispose() {
      clearTimeout(timer);
      timer = undefined;
    },
  };
}
