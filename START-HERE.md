# Start here

This kit is not a finished app. It's the hard 20% — the schema, the security
model, the AI prompts and guardrails, and a working vertical slice — plus a
prompt pack that walks an AI coding agent through building the rest.

## What's in the box

```
START-HERE.md          this guide
PROMPT-PACK.md         30+ sequenced prompts, phase by phase
db/schema.sql          full Postgres schema, ready to run
docker-compose.yml     Postgres + MinIO + Mailpit for local dev
.env.example           every setting the backend reads
backend/
  app/config.py        settings
  app/db.py            engine and session
  app/models.py        SQLAlchemy models mirroring the schema
  app/security.py      auth + the object-level authorization guard
  app/main.py          FastAPI app, security headers, routers
  app/routers/         auth, documents, deadlines, registry, assistant
  app/ai/prompts.py    the runtime prompts, with the guardrails baked in
  app/ai/schemas.py    per-category extraction schemas
  app/ai/pipeline.py   OCR -> classify -> extract -> confidence -> review
  app/ai/assistant.py  grounded retrieval and answering
  app/services/        private object storage, reminder dispatch
frontend/
  lib/api.ts           typed API client
  app/documents/VerifyPanel.tsx   the human-verification screen
tests/                 the cross-family access tests that must never be deleted
ai/benchmark_template.csv        starting point for your 100-document benchmark
.github/workflows/ci.yml         tests + bandit + pip-audit
```

## Running it locally (about 20 minutes)

**1. Prerequisites.** Python 3.12, Node 20, Docker, and Tesseract:

```bash
# macOS
brew install tesseract libmagic
# Ubuntu
sudo apt-get install -y tesseract-ocr tesseract-ocr-hin libmagic1
```

**2. Infrastructure.**

```bash
cp .env.example .env
# edit .env: set SECRET_KEY (openssl rand -hex 32) and ANTHROPIC_API_KEY
docker compose up -d
```

Postgres runs `db/schema.sql` on first boot. MinIO console: http://localhost:9001
(minioadmin / minioadmin). Mailpit catches all outbound email: http://localhost:8025

**3. Backend.**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env .env
uvicorn app.main:app --reload
```

Interactive API docs at http://localhost:8000/docs

**4. Frontend.**

```bash
cd frontend
npm install
npx next dev
```

You'll need to scaffold the Next.js app shell — `npx create-next-app@latest` into a
temp folder and copy over `app/layout.tsx`, `globals.css`, `tailwind.config.ts`,
`tsconfig.json`, keeping the `lib/` and `app/documents/` files from this kit.

**5. Prove it works.**

```bash
# register, then upload a document
curl -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","full_name":"You","password":"correct-horse-battery"}'

# use the returned access_token and family_id
curl -X POST localhost:8000/api/v1/families/$FAMILY_ID/documents \
  -H "Authorization: Bearer $TOKEN" -F file=@some-policy.pdf

# poll until status is needs_review, then read the extracted fields
curl localhost:8000/api/v1/families/$FAMILY_ID/documents/$DOC_ID \
  -H "Authorization: Bearer $TOKEN"
```

If fields come back with confidence scores, page numbers and snippets, the whole
pipeline is alive.

**6. Run the tests.**

```bash
cd backend && pytest ../tests -q
```

The cross-family access tests are the ones that matter. Keep them green.

## How to use the prompt pack

Work phase by phase. Don't skip ahead — Phase 2 assumes Phase 1's queue exists,
Phase 5 assumes Phase 2's chunks exist.

**With Claude Code (recommended).** Put the P0 context block in a `CLAUDE.md` at
the repo root, then:

```bash
cd life-admin-os && claude
> Read CLAUDE.md, db/schema.sql and backend/app/security.py. Then do P1.1 from PROMPT-PACK.md.
```

Let it finish one prompt, run the stated check, commit, then start the next. One
prompt per commit keeps the diffs reviewable and makes it easy to back out.

**With a chat window.** Paste the P0 block, then the relevant existing files,
then the prompt. Copy the output into the repo yourself. Slower, but you see
every line that lands.

**After every prompt,** run the "Review a change before merging" utility prompt
against the diff. It catches the two mistakes agents make most often on this
codebase: a query that forgot `family_id`, and an AI-derived value written
somewhere other than `extracted_fields`.

## Build order, mapped to your blueprint

| Weeks | Blueprint phase | Prompts | You have already |
|---|---|---|---|
| 9–12 | Foundation | P1.1–P1.3 | schema, auth, storage, authz guard |
| 13–17 | Document intelligence | P2.1–P2.4 | OCR, classify, extract, verify API |
| 18–20 | Deadline engine | P3.1–P3.2 | detection, scheduling, dispatch |
| 21–27 | Assets, property, family | P4.1–P4.3 | registry endpoints, graph endpoint |
| 28–31 | AI assistant | P5.1–P5.3 | grounded answering with citations |
| 32–35 | QA and security | P6.1–P6.3 | access tests, CI, security headers |
| 36–39 | Pilot | P7.1–P7.2 | — |

## Four decisions worth making before you write more code

**Which OCR.** Tesseract is free and handles clean English well. It struggles
with 1978 typewritten land records in Devanagari — exactly your hardest and most
differentiating case. Budget for Google Document AI or Azure Document
Intelligence as a fallback tier, and route to it when Tesseract's confidence is
low. Test on real degraded documents before you commit.

**Where the data lives.** If you're serious about the India-first positioning and
DPDP, pick a region inside India (AWS ap-south-1, or an Indian provider) and say
so on your privacy page. It's a real trust differentiator for a product asking
families to hand over land records.

**What you tell the model.** Document contents go to a third-party API. Your
consent notice must say this plainly, and P6.3 gives users a way to withdraw.
Check your API provider's data-retention terms and cite them in the notice.

**Confidence thresholds.** The 0.95 / 0.70 bands in `pipeline.py` are guesses.
Run P2.3's benchmark on 100 real documents and set them from the data — the point
of the benchmark is to replace assumptions with measurements, per section 22.

## The three failure modes to watch

**Silent cross-family leakage.** The single worst outcome for this product. Every
new endpoint goes through `owned_or_404`. Every new endpoint gets a row in the
access-control matrix from P6.1. No exceptions, including for "internal" routes.

**A confident wrong extraction becoming trusted data.** The verification step is
not a formality you can optimise away when users complain it's tedious. If you
ever add auto-accept, gate it behind measured per-field accuracy above 99%, and
keep the provenance trail so a wrong value can be traced back.

**Scope creep into legal territory.** The moment the assistant says "you own
this" or "this will be inherited by", the product's risk profile changes
completely. P5.2's class (c) tests exist to catch that in CI, not in production.
