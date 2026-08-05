import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

function evidenceParagraph(paragraphs, evidence) {
  return paragraphs.find((paragraph) => paragraph.text.includes(evidence) || evidence.includes(paragraph.text)) || paragraphs.find((paragraph) => evidence.split(/\s+/).filter((word) => word.length > 5).some((word) => paragraph.text.includes(word)));
}

function clauses(text) {
  return String(text).split(/(?<=,)|\b(?=while|if|before|after|because|although|whether|that|which|who)\b/i).map((part) => part.trim()).filter(Boolean);
}

const paragraphs = [{ id: "A", text: "Public transport must become reliable before residents change routines." }, { id: "B", text: "Convenience is often more important than price." }];
assert.equal(evidenceParagraph(paragraphs, "Convenience is often more important than price.").id, "B");
assert.deepEqual(clauses("Supporters agree, while critics object because costs rise."), ["Supporters agree,", "while critics object", "because costs rise."]);
const synonyms = JSON.parse(await readFile(new URL("../data/synonyms.json", import.meta.url), "utf8"));
const reading = JSON.parse(await readFile(new URL("../data/reading.json", import.meta.url), "utf8"));
const samplePassage = reading.passages.find((passage) => passage.id === reading.activePassageId);
assert.ok(synonyms.groups.length >= 80, "reading synonym library should be imported");
const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
const app = await readFile(new URL("../app.js", import.meta.url), "utf8");
assert.match(html, /data-reading-mode="article"/);
assert.match(html, /data-reading-mode="questions"/);
assert.match(html, /data-reading-mode="review"/);
assert.match(html, /data-reading-review/);
assert.match(app, /function renderReadingMode\(\)/);
assert.match(app, /function readingAttemptStats\(passage\)/);
assert.match(app, /查看定位（计为提示）/);
assert.match(app, /本地尚未录入可核验定位句/);
assert.match(app, /独立完成/);
assert.match(app, /state\.readingMode = openedFromCatalog \? "article" : "questions"/);
assert.match(app, /if \(openedFromCatalog\) state\.examMode = false/);
assert.match(app, /if \(state\.activePracticeId !== previousPracticeId\) resetReadingTransientContext\(\)/);
assert.match(app, /function resetReadingTransientContext\(\)/);
assert.match(app, /state\.readingFocusParagraphId = null/);
assert.match(app, /state\.readingFocusQuestionId = null/);
// Original sample passages only; commercial content stays in the learner's
// personal library and is never bundled.
assert.ok(reading.passages.length >= 3, "sample reading passages should exist");
assert.ok(samplePassage, "active passage must exist");
assert.ok(samplePassage.questions.length >= 3, "active passage should have questions");
assert.ok(reading.passages.every((passage) => passage.questions.every((question) => passage.paragraphs.some((paragraph) => paragraph.text.includes(question.evidence)))), "every question evidence must appear verbatim in its passage");
assert.match(app, /function readingAnswerCorrect\(question, value, passage = activePassage\(\), answers = state\.readingAnswers\)/);
assert.ok(samplePassage.questions.some((question) => question.options?.some((option) => typeof option === "string")), "fixture should exercise string-option normalization");
assert.match(app, /function normalizeReadingOptions\(reading\)/);
assert.match(app, /state\.reading = normalizeReadingOptions\(state\.reading\)/);
assert.match(app, /function aliasAnswerCorrect/);
assert.match(app, /className = "reading-text-answer"/);
assert.ok(reading.passages.flatMap((passage) => passage.questions).every((question) => !/\d+\s*[–-]\s*\d+\s+\d+\s*[–-]\s*\d+/.test(question.answer || "")), "score-band text leaked into a reading answer");

console.log("Reading evidence and clause check passed.");
