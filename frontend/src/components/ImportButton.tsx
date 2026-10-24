import { useRef } from "react";
import { useStore } from "../store";

/** File types the tool can read, as one list for the file picker and the drop area. */
export const LOG_EXTENSIONS = ["csv", "txt", "tsv", "lrd", "parquet", "xlsx", "mf4", "mdf", "asc", "blf", "trc"];
export const ACCEPT = LOG_EXTENSIONS.map((e) => `.${e}`).join(",");
export const isLogFile = (f: File) => LOG_EXTENSIONS.includes(f.name.split(".").pop()?.toLowerCase() ?? "");

/** A button that opens the file picker and imports what is chosen. */
export function ImportButton(props: { className?: string; children: React.ReactNode }) {
  const importFiles = useStore((s) => s.importFiles);
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button className={props.className ?? "btn"} onClick={() => input.current?.click()}>
        {props.children}
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const files = [...(e.target.files ?? [])];
          e.target.value = "";
          if (files.length) void importFiles(files);
        }}
      />
    </>
  );
}
