import { expect, it } from "vitest";
import { droppedMediaFiles } from "./media-drop";

const fileEntry = (name: string): FileSystemEntry =>
  ({
    name,
    isFile: true,
    isDirectory: false,
    file: (resolve: (file: File) => void) => resolve(new File(["test"], name)),
  }) as unknown as FileSystemEntry;

const directory = (
  name: string,
  batches: FileSystemEntry[][],
): FileSystemEntry =>
  ({
    name,
    isFile: false,
    isDirectory: true,
    createReader: () => {
      let index = 0;
      return {
        readEntries: (resolve: (entries: FileSystemEntry[]) => void) =>
          resolve(batches[index++] || []),
      };
    },
  }) as unknown as FileSystemEntry;

const transfer = (entries: FileSystemEntry[]): DataTransfer =>
  ({
    items: entries.map((entry) => ({
      kind: "file",
      webkitGetAsEntry: () => entry,
      getAsFile: () => null,
    })),
    files: [],
  }) as unknown as DataTransfer;

it("keeps mixed files and nested folders, reading all directory batches", async () => {
  const files = await droppedMediaFiles(
    transfer([
      fileEntry("loose.txt"),
      directory("Movie", [
        Array.from({ length: 100 }, (_, i) => fileEntry(`${i}.mkv`)),
        [
          fileEntry("last.mkv"),
          directory("Subtitles", [[fileEntry("da.srt")]]),
        ],
      ]),
    ]),
    new AbortController().signal,
  );
  expect(files).toHaveLength(103);
  expect(files[0].relativePath).toBe("loose.txt");
  expect(files[101].relativePath).toBe("Movie/last.mkv");
  expect(files[102].relativePath).toBe("Movie/Subtitles/da.srt");
});

it("supports ordinary file drops without entry APIs", async () => {
  const file = new File(["test"], "loose.txt");
  const data = {
    items: [{ kind: "file", getAsFile: () => file }],
    files: [file],
  } as unknown as DataTransfer;
  expect(await droppedMediaFiles(data, new AbortController().signal)).toEqual([
    { file, relativePath: "loose.txt" },
  ]);
});

it("propagates folder read errors instead of uploading a partial selection", async () => {
  const entry = {
    name: "private",
    isDirectory: true,
    isFile: false,
    createReader: () => ({
      readEntries: (_resolve: unknown, reject: (error: Error) => void) =>
        reject(new Error("Access denied")),
    }),
  } as unknown as FileSystemEntry;
  await expect(
    droppedMediaFiles(
      transfer([fileEntry("first.txt"), entry]),
      new AbortController().signal,
    ),
  ).rejects.toThrow("Access denied");
});

it("honours cancellation and rejects oversized selections before uploading", async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(
    droppedMediaFiles(transfer([fileEntry("test.txt")]), controller.signal),
  ).rejects.toThrow();
  await expect(
    droppedMediaFiles(
      transfer([
        directory("large", [
          Array.from({ length: 10001 }, () => fileEntry("test.txt")),
        ]),
      ]),
      new AbortController().signal,
    ),
  ).rejects.toThrow("10,000");
});
