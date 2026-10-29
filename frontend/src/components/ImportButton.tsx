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
  // Phone file pickers grey out files they cannot match by type (logs have no known type there), so offer all and check the name.
  const coarse = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  return (
    <>
      <button className={props.className ?? "btn"} onClick={() => input.current?.click()}>
        {props.children}
      </button>
      <input
        ref={input}
        type="file"
        accept={coarse ? undefined : ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const picked = [...(e.target.files ?? [])];
          const files = picked.filter(isLogFile);
          e.target.value = "";
          if (files.length) void importFiles(files);
          else if (picked.length)
            useStore.setState({ message: { kind: "warn", text: "Those are not log files the tool can read (CSV, Excel, Parquet, MDF, CAN)." } });
        }}
      />
    </>
  );
}
