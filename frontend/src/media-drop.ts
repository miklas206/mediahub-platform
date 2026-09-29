export type MediaUploadFile = { file: File; relativePath: string };

// Capture entries while the drop event's data store is still accessible.
export async function droppedMediaFiles(
  transfer: DataTransfer,
  signal: AbortSignal,
): Promise<MediaUploadFile[]> {
  const roots = Array.from(transfer.items)
    .filter((item) => item.kind === "file")
    .map((item) => ({
      entry: item.webkitGetAsEntry?.(),
      file: item.getAsFile(),
    }));
  const fallback = Array.from(transfer.files);
  const result: MediaUploadFile[] = [];
  let visited = 0;
  const append = (file: File, relativePath: string) => {
    signal.throwIfAborted();
    if (result.length >= 10000)
      throw new Error("Choose at most 10,000 files per upload.");
    result.push({ file, relativePath });
  };
  const walk = async (entry: FileSystemEntry, parent = ""): Promise<void> => {
    signal.throwIfAborted();
    if (++visited > 20000)
      throw new Error("Choose fewer files and folders per upload.");
    if (
      !entry.name ||
      [".", ".."].includes(entry.name) ||
      /[/\\]/.test(entry.name)
    )
      throw new Error("The browser supplied an invalid folder path.");
    const path = parent + entry.name;
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject),
      );
      append(file, path);
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // Chromium returns batches (often 100 entries); read until exhausted.
      while (true) {
        signal.throwIfAborted();
        const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
          reader.readEntries(resolve, reject),
        );
        if (!batch.length) break;
        for (const child of batch) await walk(child, path + "/");
      }
    } else {
      throw new Error("This item cannot be uploaded.");
    }
  };
  if (roots.length) {
    for (const { entry, file } of roots) {
      if (entry) await walk(entry);
      else if (file) append(file, file.name);
      else throw new Error("This browser could not read the dropped item.");
    }
  } else {
    for (const file of fallback) append(file, file.name);
  }
  return result;
}
