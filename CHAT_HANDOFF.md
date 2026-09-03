# Handwritten Extractor — Full Chat Handoff

Use this file on the other machine. It is the complete plan from the original chat: task, PDF findings, architecture, Google Cloud setup, and next steps.

**Date:** 2026-09-03  
**Project folder:** `Handwrite_Extractor`  
**Sample PDF:** `Perez Guzman Sofia.pdf` (~14 MB, 78 pages)  
**Stack decision:** Python + FastAPI + **Google Cloud Document AI (Form Parser)** + **Vertex AI Gemini** for messy pages  

---

## How to continue on the new machine

1. Copy this repo (at least this file + the sample PDF).
2. Open a new Cursor chat and attach `CHAT_HANDOFF.md`.
3. Say: continue from this handoff; next step is scaffold FastAPI and wire Google Form Parser.
4. In GCP, create the **Form Parser** processor (steps below) and keep Project ID, Region, Processor ID ready.

Do not commit secrets, `.env`, or service-account JSON.

---

## 1. Original task

The system must take a legal/medical PDF packet (example: Perez Guzman Sofia) and extract **every detail**, including:

- printed text
- handwritten field values (names, dates, phones, notes)
- handwritten tick / X / checkmark boxes
- circled printed options (example: circling “PRE-EMPLOYMENT”)
- freehand margin notes (sometimes diagonal or vertical)
- signatures as **PRESENT / ABSENT only** (do not “read” a scribble as a name)

Save the result to **clean `.txt`** (and structured `.json`).  
**Summarization comes later.** Do not build summarization in v1.

Tech: **Python + FastAPI**.

---

## 2. What is in the sample PDF

Inspected with PyMuPDF. Not a fillable AcroForm. **Zero PDF form widgets.** Every checkbox/circle must be seen by OCR/vision.

| Pages | Content | How text exists |
|---|---|---|
| ~1–17 | Matrix/Sumxio cover, overview, indexes (body parts, ICD, procedures, visits) | Digital PDF text. Easy. PyMuPDF. |
| ~18–21 | Legal paperwork (subpoena, declarations, records request) | Mostly digital text. Easy. |
| ~22–78 | Concentra / Quest **source medical records** | Almost no extractable text. Scanned images. This is the real job. |

On source pages:

- Printed labels + handwritten values on the same form
- Tick / X / checkmark boxes
- Circled printed options
- Freehand notes, sometimes angled or vertical
- Signatures
- Driver-license photocopies
- Barcodes, “SCANNED” stamps, tables, text sitting on underlines
- Drug testing CCF forms, patient intake, authorizations, HIPAA releases, non-injury flowsheets

**Tesseract / basic OCR is the wrong primary engine.** It reads printed labels and fails on handwriting, ticks, circles, and label→value mapping.

---

## 3. TrOCR — decided NO as the page engine

Microsoft TrOCR is a **line transcriber**. You crop one text line; it outputs text. It does **not**:

- understand page layout
- map “Patient Name” → handwritten value
- detect checkboxes or circled words
- handle tables, signatures-as-marks, diagonal/vertical notes

It can be a later **local fallback** for cropped handwritten lines if we must stay offline. It is **not** the system.

---

## 4. Final architecture (locked)

Hybrid, page-aware pipeline. Two engines. Digital pages never go to OCR. Vision LLM only on a capped messy subset.

```text
PDF upload
 └─ FastAPI job (worker, not inside the HTTP request)
     ├─ 1. Split + classify pages          (PyMuPDF, local)
     ├─ 2. Digital pages → PyMuPDF         (fast path)
     ├─ 3. Scan pages → Google Form Parser (main OCR)
     ├─ 4. Messy pages → Gemini vision     (accuracy path, capped)
     ├─ 5. Merge + normalize               (Gemini Flash / text-only)
     └─ 6. Write extracted.json + extracted.txt
```

### Page routing

- `chars > 80` and not a full-page scan → **digital**
- else → **scanned** → Form Parser
- scanned + (handwriting **or** checkboxes **or** form-like **or** low confidence) → **vision rescue**, under a hard cap

### Engines (Google Cloud)

| Job | Product | What to create |
|---|---|---|
| OCR, tables, checkboxes, handwriting, key-value fields | **Document AI** | Processor type **Form Parser** (`FORM_PARSER_PROCESSOR`) |
| Messy pages (circles, margin notes, “Other: 5 PANEL”) | **Vertex AI Gemini** | e.g. Gemini 2.5 Flash / Pro vision |
| Cleanup into our schema | Gemini text | same Vertex project |

Do **not** use Azure. User has GCP.

Do **not** use:

- Tesseract / EasyOCR as primary
- TrOCR as page reader
- Document OCR / Enterprise Document OCR as the main processor (text-only)
- Layout Parser as the main processor (RAG chunking, not ticks/fields)
- Custom extractor in v1 (needs labeling)

### Output format (canonical)

`extracted.json` is the source of truth. `.txt` is generated from it.

```json
{
  "job_id": "...",
  "source_file": "Perez Guzman Sofia.pdf",
  "page_count": 78,
  "pages": [
    {
      "page": 24,
      "route": "form_parser+vision",
      "document_type": "Authorization for Examination or Treatment",
      "header": { "patient_name": "...", "mrn": "...", "visit_date": "..." },
      "fields": [
        { "label": "Patient Name", "value": "SOFIA PEREZ", "source": "handwritten" }
      ],
      "marks": [
        { "label": "Rapid drug screen", "state": "marked", "mark_type": "x" },
        { "label": "Injury", "state": "unmarked" }
      ],
      "circled_options": ["PRE-EMPLOYMENT"],
      "notes": ["5 PANEL"],
      "signatures": [{ "role": "authorized_by", "state": "present" }],
      "printed_text": "..."
    }
  ]
}
```

Matching `.txt` page block:

```text
===== PAGE 24 =====
type: Authorization for Examination or Treatment
route: form_parser+vision

[HEADER]
...

[FIELDS]
Patient Name [handwritten]: SOFIA PEREZ

[MARKS]
Rapid drug screen: MARKED (X)
Injury: UNMARKED

[CIRCLED]
PRE-EMPLOYMENT

[NOTES]
5 PANEL

[SIGNATURES]
authorized_by: PRESENT
```

Rules:

- Keep label and value separate
- Marks are `MARKED` / `UNMARKED`
- Circles are their own list
- Notes stay notes
- Signatures are never transcribed as a name
- ID photos: extract printed ID fields only; do not dump the photo
- Never invent empty fields; use `null` / omit
- If Form Parser and vision disagree on a mark, **prefer vision** and flag `needs_review`

---

## 5. Scalability (78, 300, and 1,000 pages)

The 78-page “render every page and send lots of vision calls” idea does **not** scale.

### What breaks at 300–1000 pages

- Rendering 1,000 pages at 220 DPI in memory
- FastAPI `BackgroundTasks` (dies on restart, no queue)
- Vision on ~30% of pages (too slow and expensive)
- No checkpoints (fail at page 700 → redo everything)

### Production runtime

```text
Upload PDF
  → create job
  → enqueue worker
      → split into chunks (Form Parser max 100 pages per batch file)
      → Form Parser per chunk
      → save per-page JSON to disk
      → Gemini vision ONLY on a capped messy subset
      → merge → extracted.json + .txt
```

**Chunk size:** 50–100 pages (Google Form Parser **batch limit is 100 pages per file**).

**Workers:** Redis + Celery or Arq for real use. In-process background tasks only for local 78-page demos.

**Checkpoint:** `data/jobs/{id}/pages/0001.json` so a crash resumes.

**Vision hard cap:**

```text
vision_pages = min(40, 8% of scanned pages)
```

Priority for those 40: checkboxes, handwriting, form-like pages (CCF, authorization, flowsheet), low confidence. Skip typed dumps, blanks, covers.

**Do not pre-render 1,000 images.** Send PDF chunks to Document AI. Render a PNG only for vision-rescue pages, then delete it.

**Expected time:**

| Pages | Typical extract time |
|---|---|
| 78 | ~30–60s |
| 300 | ~3–8 min |
| 1,000 | ~10–25 min |

API returns `job_id` immediately. Client polls status.

Google Form Parser limits (must design around these):

- Online/sync: **15 pages** (30 with imageless mode)
- Batch (Cloud Storage): **100 pages per file**
- Online file size: 40 MB
- Batch file size: 1 GB

So 300 and 1,000 page PDFs **must** be split. That is mandatory on Google, unlike Azure Layout (2,000 pages / 500 MB).

---

## 6. FastAPI contract

```text
POST /v1/extract                 upload PDF → { job_id }
GET  /v1/extract/{job_id}        queued | running | done
                                 pages_done, pages_total, current_chunk
GET  /v1/extract/{job_id}/json
GET  /v1/extract/{job_id}/txt
```

Suggested layout:

```text
app/
  main.py
  api/extract.py
  pipeline/
    classify.py
    digital.py
    chunk.py
    form_parser.py      # Google Document AI
    vision_rescue.py    # Vertex Gemini
    normalize.py
    writer.py
  schemas/page.py
data/jobs/
```

V1 skip:

- Summarization
- Custom per-form templates
- TrOCR
- Fine-tuning
- Reading signatures as text

Build order:

1. FastAPI upload, job folder, PyMuPDF split/classify, digital text for pages 1–21
2. Chunk scans + Form Parser → raw page JSON
3. Normalizer → clean `.json` / `.txt`
4. Gemini vision rescue on flagged pages (cap)
5. Tune on the Sofia PDF until ticks, handwritten dates, and margin notes are correct
6. Then summarization (later)

---

## 7. Google Cloud — where to find the “model”

On Google you do **not** download a model. You **create a Document AI processor** in the GCP project.

### Create Form Parser

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select the project.
2. Search **Document AI**.
3. Enable **Document AI API** if prompted.
4. Left menu → **Processor Gallery**  
   Link: [https://console.cloud.google.com/ai/document-ai/processor-gallery](https://console.cloud.google.com/ai/document-ai/processor-gallery)
5. Search **Form Parser** → **Create**.
6. Name e.g. `handwrite-form-parser`.
7. Region: `us` (or `eu` if data must stay in EU). **Region is locked after create.**
8. Copy:
   - Project ID
   - Region
   - Processor ID (looks like `a1b2c3d4e5f6g7h8`)

Test in the console: upload a Concentra form page and check Key-value pairs, Checkboxes, Text.

### Also enable later (vision)

Vertex AI API + a Gemini model (e.g. Gemini 2.5 Flash). That is **not** in the Document AI gallery.

### Auth for the app

Service account with Document AI User (and Vertex AI User later).  
JSON key or `gcloud auth application-default login` on the dev machine.  
Put IDs in `.env`, never in git.

```text
GCP_PROJECT_ID=...
GCP_LOCATION=us
DOCAI_PROCESSOR_ID=...
```

---

## 8. Azure / AWS (not used — for context only)

The chat originally planned Azure Document Intelligence model **`prebuilt-layout`**. User then chose Google.

| Cloud | Product | Call |
|---|---|---|
| Azure (not used) | Document Intelligence | `prebuilt-layout` + keyValuePairs |
| **Google (chosen)** | Document AI | **Form Parser** |
| AWS (not used) | Textract | `AnalyzeDocument` FORMS + TABLES + LAYOUT + SIGNATURES |

Pick one cloud. Do not run two.

---

## 9. Accuracy / medical-legal rules

- Log page route + engine, not raw PHI
- Flag low-confidence handwritten values
- Keep `source`: `digital | printed_ocr | handwritten | vision`
- HIPAA: BAA on GCP if this is production PHI
- Temporary page-image inspection files were deleted from the original machine after analysis

---

## 10. Sample PDF document types (no extra PII)

Use these as test pages when building:

- Digital Matrix summary / index pages
- WCAB / subpoena legal pages
- Patient chart cover
- ID photocopy + handwritten phone/time
- Forensic / Quest drug testing CCF (checkboxes, handwritten dates/phones, signatures)
- Concentra patient information form (ticks, signature)
- Authorization for Examination or Treatment (handwritten fields, X marks, “Other: 5 PANEL”)
- Treatment authorization (checkmark + **circled** PRE-EMPLOYMENT, margin notes)
- HIPAA release (signature + handwritten date)
- Non-injury flowsheet (handwritten times, initials, vertical name, barcode sticker, SCANNED stamp)

---

## 11. Next message to the new-machine agent

```text
Read CHAT_HANDOFF.md. We already decided:

- Python + FastAPI
- Google Document AI Form Parser for scans
- Vertex Gemini vision only on a capped messy subset
- Chunk PDFs at <=100 pages for Form Parser batch
- Output extracted.json + extracted.txt
- No summarization yet
- No TrOCR as the page engine

I have (or will have) GCP_PROJECT_ID, GCP_LOCATION, DOCAI_PROCESSOR_ID.

Scaffold the project and implement step 1: upload job + PyMuPDF split/classify + digital-page text extraction. Then wire Form Parser for scanned chunks.
```

---

## Chat timeline (short)

1. User: extract all details including handwriting, ticks, dates; Python + FastAPI; plan first; summarization later.
2. Agent: inspected 78-page PDF; hybrid Azure Layout + vision plan.
3. User: what about TrOCR?
4. Agent: TrOCR is line OCR only; reject as primary.
5. User: final efficient/accurate/fast plan.
6. Agent: locked hybrid plan, parallel Azure, vision subset.
7. User: will this scale to 200–300 and 1000 pages?
8. Agent: yes if chunked async workers, checkpoints, vision cap. In-process 78-page flow will not scale.
9. User: what is the Azure model? Alternatives on Google/AWS?
10. Agent: Azure `prebuilt-layout`; Google Form Parser; AWS Textract.
11. User: I have GCP; where do I find the model?
12. Agent: Document AI → Processor Gallery → create **Form Parser**; copy processor ID.
13. User: export this whole chat as markdown for a machine change.
14. This file.
