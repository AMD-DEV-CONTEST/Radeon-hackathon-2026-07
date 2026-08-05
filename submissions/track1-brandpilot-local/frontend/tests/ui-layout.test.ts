import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {updateChoiceSelection} from "../lib/selection.ts";

const read=(path:string)=>readFileSync(new URL(path,import.meta.url),"utf8");

test("Studio starts with exactly one creative style",()=>{
  const draft=read("../lib/studio-draft.ts");
  assert.match(draft,/creative_styles:\["Luxury"\]/);
  assert.doesNotMatch(draft,/creative_styles:\["Luxury","Minimal Studio"/);
});

test("changing creative style deselects the previous style",()=>{
  assert.deepEqual(updateChoiceSelection(["Luxury"],"Lifestyle",true),["Lifestyle"]);
  const ui=read("../components/ui.tsx");
  assert.match(ui,/legend="Creative style"[\s\S]*single\/>/);
});

test("output formats remain intentional multi-select choices",()=>{
  assert.deepEqual(updateChoiceSelection(["Instagram Square"],"Story / Reel Cover",false),["Instagram Square","Story / Reel Cover"]);
  assert.deepEqual(updateChoiceSelection(["Instagram Square","Story / Reel Cover"],"Instagram Square",false),["Story / Reel Cover"]);
});

test("primary navigation exposes a normalized active state",()=>{
  const shell=read("../components/shell.tsx");
  assert.match(shell,/aria-current=\{active\?"page":undefined\}/);
  const css=read("../app/globals.css");
  assert.match(css,/\.navlinks a\[aria-current="page"\]/);
});

test("Architecture renders truthful non-empty project status",()=>{
  const architecture=read("../app/architecture/page.tsx");
  assert.match(architecture,/>Project status</);
  assert.match(architecture,/Local mock mode/);
  assert.match(architecture,/Blocked by official tunnel DNS/);
  assert.doesNotMatch(architecture,/Evidence map/);
});

test("reset workspace is a named keyboard-accessible button",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.match(studio,/<Button type="button" variant="ghost" className="reset-workspace-button" aria-label="Reset campaign workspace"/);
});

test("mode selector uses an accessible radio group with equal options",()=>{
  const ui=read("../components/ui.tsx");
  assert.match(ui,/<fieldset className="mode-control"><legend>Inference mode<\/legend>/);
  assert.match(ui,/type="radio" name="mode"/);
  const css=read("../app/globals.css");
  assert.match(css,/\.mode-control>div\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
});

test("format options render accessible aspect-ratio previews",()=>{
  const ui=read("../components/ui.tsx");
  assert.match(ui,/export function AspectRatioPreview/);
  assert.match(ui,/aria-label=\{`\$\{label\} aspect ratio preview`\}/);
  assert.match(ui,/role="img"/);
});
