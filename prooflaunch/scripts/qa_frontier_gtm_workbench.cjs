const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const root = path.resolve(__dirname, "..");
  const output = path.join(root, "web", "qa");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const observations = [];
  const interactions = [];
  try {
    for (const viewport of [
      { id: "desktop", width: 1440, height: 1000 },
      { id: "mobile", width: 390, height: 844 },
    ]) {
      const page = await browser.newPage({ viewport });
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(`${viewport.id}:console:${message.text()}`);
      });
      page.on("pageerror", (error) => errors.push(`${viewport.id}:page:${error.message}`));
      await page.goto("http://127.0.0.1:4173/control/frontier-gtm", { waitUntil: "networkidle" });
      const panel = page.locator('[data-route="/control/frontier-gtm"]');
      if (!(await panel.isVisible())) errors.push(`${viewport.id}:frontier panel hidden`);
      const form = page.locator("#frontier-gtm-form");
      const controls = await form.locator("input,select,textarea,button").count();
      if (controls < 14) errors.push(`${viewport.id}:frontier form controls incomplete:${controls}`);
      const title = await page.locator("#frontier-gtm-heading").textContent();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      if (overflow) errors.push(`${viewport.id}:horizontal overflow`);
      observations.push({ viewport, title, controls, horizontal_overflow: overflow });
      await page.screenshot({
        path: path.join(output, `frontier-gtm-workbench-${viewport.id}.png`),
        fullPage: true,
      });
      await page.close();
    }
    const interactionPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await interactionPage.route("**/v1/frontier-gtm/runs", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          content_sha256: "c".repeat(64),
          release_review_status: "ready_for_named_human_release_review",
          activated_role_count: 17,
          activated_skill_card_count: 170,
          named_product_stress_count: 130,
          strategy: {
            non_consensus_bet: "Decision proof before production volume",
            market_diagnosis: "Synthetic browser QA fixture only.",
            primary_distribution_surface: "linkedin",
            secondary_distribution_surface: "youtube",
            primary_search_surface: "google_search",
            primary_geo_surface: "perplexity_answers",
          },
          jury: { selected_territory_id: "territory-a" },
          concepts: { territories: [
            { territory_id: "territory-a", campaign_name: "The Refusal Interview", first_line: "One claim must survive.", primary_platform: "linkedin", portable_decision_tool: "claim card" },
            { territory_id: "territory-b", campaign_name: "The Missing Decision", first_line: "Find the absent handoff.", primary_platform: "youtube", portable_decision_tool: "handoff map" },
            { territory_id: "territory-c", campaign_name: "Prove Me Wrong", first_line: "Bring one counterexample.", primary_platform: "reddit", portable_decision_tool: "falsifier" },
          ] },
          final_production: { channel_portfolio: {
            primary_distribution: { surface_id: "linkedin", native_asset: "Operator decision post", qualified_metric: "qualified reviews", release_state: "draft_for_human_review" },
            secondary_distribution: { surface_id: "youtube", native_asset: "Chaptered rejection film", qualified_metric: "qualified retention", release_state: "draft_for_human_review" },
            search: { surface_id: "google_search", native_asset: "Decision worksheet", qualified_metric: "task completion", release_state: "draft_for_human_review" },
            geo: { surface_id: "perplexity_answers", native_asset: "Source-clear answer unit", qualified_metric: "citation accuracy", release_state: "draft_for_human_review" },
          } },
          final_audit: {
            status: "pass", blocking_defects: [], claim_violations: [], platform_mismatches: [], generic_language: [],
            cross_modal_breaks: [], zero_budget_breaks: [], skill_gate_failures: [], surface_gate_failures: [], evidence_gate_failures: [],
          },
        }),
      });
    });
    await interactionPage.goto("http://127.0.0.1:4173/control/frontier-gtm", { waitUntil: "networkidle" });
    await interactionPage.evaluate(() => sessionStorage.setItem("prooflaunch-tenant-token-v1", "qa-tenant-token-000000000000000000"));
    await interactionPage.reload({ waitUntil: "networkidle" });
    await interactionPage.locator("#frontier-gtm-form button[type='submit']").click();
    await interactionPage.locator("#frontier-gtm-result").waitFor({ state: "visible" });
    const territoryCards = await interactionPage.locator("#frontier-concept-summary article").count();
    const channelCards = await interactionPage.locator("#frontier-channel-summary article").count();
    const resultBadge = await interactionPage.locator("#frontier-gtm-status").textContent();
    if (territoryCards !== 3) errors.push(`interaction:territory cards:${territoryCards}`);
    if (channelCards !== 4) errors.push(`interaction:channel cards:${channelCards}`);
    if (!String(resultBadge).includes("Ready for human review")) errors.push(`interaction:result badge:${resultBadge}`);
    interactions.push({ territory_cards: territoryCards, channel_cards: channelCards, result_badge: resultBadge, fixture_only: true });
    await interactionPage.screenshot({ path: path.join(output, "frontier-gtm-workbench-result-fixture.png"), fullPage: true });
    await interactionPage.close();
  } finally {
    await browser.close();
  }
  const report = {
    schema: "ProofLaunchFrontierGTMWorkbenchQAV1",
    status: errors.length ? "failed" : "passed",
    observations,
    interactions,
    errors,
  };
  fs.writeFileSync(path.join(output, "frontier-gtm-workbench-report.json"), JSON.stringify(report, null, 2) + "\n");
  process.stdout.write(JSON.stringify(report, null, 2) + "\n");
  if (errors.length) process.exitCode = 1;
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
