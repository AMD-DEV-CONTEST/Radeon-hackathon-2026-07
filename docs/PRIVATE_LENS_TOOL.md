# Private 108-Technique Lens Tool

XiangLens can mount the existing 24-lesson, 108-technique avatar-symbolism distillation as an
optional server-side Tool. The material is proprietary and is intentionally absent from the
repository, public Milvus corpus, frontend bundle, fixtures, deck, and screenshots.

## Runtime Boundary

```text
User opt-in
  -> LangGraph run_private_lens node
  -> private file loaded in FastAPI process memory
  -> self-hosted Radeon VLM
  -> typed PrivateLensReading
  -> sensitive-claim filter
  -> short symbolic association + technique identifier
```

The public four-pack Milvus Lite corpus remains unchanged. It proves source-backed vector
retrieval. The private course is a separate Tool extension because it has different copyright,
permission, language, and safety requirements.

## Supported Source Files

- Markdown or plain text;
- JavaScript/TypeScript containing one exported template-literal knowledge string;
- maximum file size: 256,000 bytes.

The existing `avatarKnowledge.ts` distillation can therefore be mounted without conversion.

## Configuration

Keep the source outside the repository and set:

```env
XIANG_PRIVATE_LENS_ENABLED=true
XIANG_PRIVATE_LENS_PATH=/secure/private/avatarKnowledge.ts
XIANG_PRIVATE_LENS_NAME=Private 108-Technique Lens
```

Restart FastAPI and verify:

```bash
curl -fsS -H "X-App-API-Key: $XIANG_APP_API_KEY" \
  'http://127.0.0.1:8080/api/v1/system/status' \
  | jq '{private_lens_available, private_lens_name}'
```

The UI shows the private checkbox only when the backend reports the mount as available. It is
unchecked by default. Each analysis request must explicitly send:

```json
{
  "enable_private_lens": true
}
```

## Output Contract

The browser receives only:

- directly observed motifs;
- up to three short symbolic associations;
- technique identifiers such as `Technique #28`;
- uncertainties and a visible non-factual-use disclaimer.

It never receives the mounted path, source text, long quotations, full prompt, or course sections.
The code removes associations containing personality, health, medical, wealth, financial,
relationship, fertility, criminality, protected-attribute, fortune, future-event, or destiny
claims. The normal XiangLens policy gate remains active before the private tool node.

## Demonstration

Use a repository fixture. Show the unchecked private control, enable it, run the graph, and keep the
Trace panel visible. The judge should see `run private lens` complete between visual observation
and Milvus retrieval. In the report, show one technique identifier and the symbolic-context
disclaimer; do not open the private file or display course text.

## Rights and Secret Scan

Before committing or recording:

```bash
git ls-files | rg -i 'avatarKnowledge|108-technique|private.*course'
git status --short
```

Documentation and adapter code may match. The private source, derived chunks, screenshots of the
course, and model prompts containing its text must not be tracked.
