import { cpSync, existsSync } from "node:fs";

// SQL stays in separate files and is copied beside the compiled DB modules.
// A directory may not exist yet when an application has no tables or seeds.
for (const directory of ["tables", "seeds"]) {
  const source = new URL(`../src/db/${directory}/`, import.meta.url);
  if (!existsSync(source)) continue;
  cpSync(source, new URL(`../dist/db/${directory}/`, import.meta.url), { recursive: true });
}
