import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const read=(path:string)=>readFileSync(new URL(path,import.meta.url),"utf8");

test("Campaign Summary is attached without draggable UI",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.doesNotMatch(studio,/DraggableCampaignSummary|summary-drag-handle|Drag campaign summary|Reset position/);
  assert.doesNotMatch(studio,/draggable=|role="button"[^>]*campaign-summary/);
});

test("obsolete summary position is removed without clearing other session data",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.match(studio,/obsoleteCampaignSummaryPositionKey="brandpilotCampaignSummaryPosition"/);
  assert.match(studio,/sessionStorage\.removeItem\(obsoleteCampaignSummaryPositionKey\)/);
  assert.doesNotMatch(studio,/sessionStorage\.clear\(/);
});

test("Campaign Summary remains first in normal right-rail order",()=>{
  const studio=read("../app/studio/page.tsx");
  const rail=studio.slice(studio.indexOf('<aside className="studio-sidebar"'));
  const summary=rail.indexOf('className="dashboard-card campaign-summary"');
  const connection=rail.indexOf("<RadeonConnectionPanel");
  const progress=rail.indexOf('<h2>Progress</h2>');
  const system=rail.indexOf("<SystemStatusPanel");
  const review=rail.indexOf('<h2>Human stays in control</h2>');
  assert.ok(summary>=0&&summary<connection&&connection<progress&&progress<system&&system<review);
});

test("right rail is a static flex stack with responsive single-column layout",()=>{
  const css=read("../app/globals.css");
  const summaryRule=css.match(/\.campaign-summary\{([^}]*)\}/)?.[1]??"";
  assert.match(css,/\.studio-layout\{display:grid;grid-template-columns:minmax\(0,1fr\) minmax\(300px,360px\)/);
  assert.match(css,/\.studio-sidebar-stack\{display:flex;[^}]*flex-direction:column;gap:1rem\}/);
  assert.match(summaryRule,/position:static/);
  assert.match(summaryRule,/width:100%/);
  assert.match(summaryRule,/height:auto/);
  assert.doesNotMatch(summaryRule,/transform|fixed|absolute|sticky/);
  assert.match(css,/@media\(max-width:1100px\)\{[\s\S]*?\.studio-layout\{grid-template-columns:1fr\}/);
});

test("Campaign Summary values still read live Studio state",()=>{
  const studio=read("../app/studio/page.tsx");
  assert.match(studio,/draftHydrated\?form\.product_name\|\|"Not named"/);
  assert.match(studio,/draftHydrated\?form\.creative_styles\[0\]\|\|"Not selected"/);
  assert.match(studio,/draftHydrated\?form\.output_formats\.length/);
  assert.match(studio,/file\?"Ready":assetRestoreState==="loading"\?"Restoring…":assetRestoreState==="reselect"\?"Reselect required":"Required"/);
});
