<div align="center">

<img src="frontend/public/assets/formatly-mark.png" width="88" height="88" alt="Formatly logo">

# Formatly

A formatting checker for graduation theses and internship reports.

[Python 3.11+](#quick-start) · [Vue 3](frontend/README.md) · [TypeScript](frontend/ARCHITECTURE.md) · [MIT License](LICENSE)

[中文](README.md) · [English](README_en.md)

**[Quick start](#quick-start) · [Capabilities](#capabilities) · [Documentation](#documentation)**

</div>

Formatly is a formatting checker for graduation theses and internship reports, with checks for page size, margins, body fonts, font sizes, and line spacing. You can upload your school's templates and formatting instructions to guide the checks. After checking, use the report to locate problems, compare the required and actual formatting, and revise your document.

---

## Features

- **Check against school requirements** — Upload templates and instructions, review the extracted requirements, and save your own profile.
- **Manage rule profiles** — Edit common formatting fields, import or export JSON, and try a saved profile on an anonymous sample. School requirement drafts can be saved, restored, or discarded.
- **Find common formatting problems** — Check page settings, body and heading fonts and sizes, indentation, paragraph spacing, exact or automatic line spacing, columns, and required headings according to the selected rules and file format.
- **Use common file formats** — Upload DOCX, PDF, TXT, MD, or JSON. Text-only files support text and field checks; they do not provide page layout or font information.
- **Read scanned PDFs** — Extract PDF text and page information, with optional local Tesseract OCR for scanned pages. Recognized text needs review.
- **Read the check report** — See problem locations, required and actual formatting, and items needing manual review. Download JSON, Markdown, or standalone HTML reports.
- **Repair selected DOCX problems** — Select supported formatting problems, generate a corrected copy, and run a new check. Download the document and change record from the new task.
- **Compare revisions and check batches** — Link a revised document to the original check and compare matching observations. Batch files retain separate results and allow individual retries.
- **Check internship documents** — Check basic internship certificate requirements and compare names, student IDs, organizations, and dates across a related thesis, internship report, and certificate.
- **Light and dark themes** — Use the top-right switch to save a local theme preference. Reports use a light palette for printing.

---

## Quick start

**Requirements:** Python 3.11+ · Windows / macOS / Linux · a browser. Node.js 22+ is required for frontend development or building missing frontend resources. OCR and Word/WPS rendering are optional capabilities with separate local dependencies.

### 1. Install the Python dependencies

Run these commands from the repository root:

```powershell
# Windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
# Linux / macOS
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Alternatively, use `uv venv` and `uv pip install -r requirements.txt`. The same file skips `pywin32` on macOS and Linux because that package is marked `sys_platform == "win32"`. Word/WPS export still runs only on Windows. If `frontend/dist` is missing or the frontend source has changed, complete the [frontend build](#development-and-checks) before starting the workbench. Formatly runs from the project directory and is not installed as a Python library.

### 2. Start the workbench

```powershell
# Windows
.\.venv\Scripts\python.exe app.py
```

```bash
# Linux / macOS
./.venv/bin/python app.py
```

Windows users can double-click `启动工作台.cmd`. On macOS and Linux, run `sh 启动工作台.sh` from the project root. PyCharm can run the root `app.py` directly using the project interpreter. The service defaults to **`0.0.0.0:8765`**, opens a browser after its health check succeeds, and prints local and LAN addresses.

On this machine, open `http://127.0.0.1:8765`. Other devices on the same LAN use `http://<server-ip>:8765` from the startup log. Use `--local-only` for access from this machine only, `--no-browser` to skip opening a tab, or `--port 8766` to select another port. Press Ctrl+C to stop.

The following examples use `python` for the project environment; activate `.venv` or substitute its full interpreter path. From the project root, `python -m formatly serve` uses the same server.

### 3. Run a check

The workbench currently uses Chinese labels.

1. Choose an entry: open **新建检测** (New check). **预置方案** (Preset) selects a profile, then accepts the draft and starts the check. **学校模板** (School template) uploads the school file, then opens review; after saving, return to the preset branch to check a draft. Saved profiles can be reused directly.
2. Check the material type and selected profile. For school requirements that need a local scope, match the actual draft's styles or sections using its text samples. Explicitly unmatched requirements remain manual. School materials are not required when using a preset or a saved profile.
3. Read the result: each problem shows its location, the required formatting, and the actual formatting. Check any manual-review or unchecked items and download the report.
4. For DOCX, choose **查看可修复项** (Preview repairs), select the problems to fix, then choose **生成副本并复检** (Create copy and recheck). Edit other problems yourself and upload the revision with **检测修改稿**. **重试本次检测** reruns the saved document and rules.

For a first CLI example, run `python -m formatly check --input examples/document.json --profile generic --json`.

The generic profile provides basic checks. School differences belong in user-confirmed profile data. Match template requirements to the actual draft; different values can apply to explicitly separate styles or sections, while overlapping conflicts must be resolved. The school workflow also configures supported heading, caption, reference and section page-number checks. Incomplete extraction and unsupported requirements never count as a formatting pass.

---

## Capabilities

| Format | Evidence and checks | Scope |
|:-------|:--------------------|:------|
| DOCX | Package structure, page size and margins, configured body and heading fonts/sizes, indentation, paragraph spacing, exact or automatic line spacing, gutter, header/footer distances, columns, headings, and labeled fields | Actual pagination, complex layout, unresolved font properties, and signatures need further review |
| PDF | Page dimensions, extractable text, headings and fields; native font and size checks within an explicitly configured body region | Word styles, line spacing, and margins are unavailable; OCR does not establish original fonts |
| TXT | Text structure, standalone headings, and labeled fields | No physical page or font properties |
| Markdown | Text, headings, and labeled fields | No rendered pagination, margins, or typography checks |
| JSON | Strings and JSON Pointer locations, or structured titles, paragraphs, and fields | Only properties actually represented by the document are available |

PDF uses native text first. Scanned and mixed pages use Tesseract when the program and selected language packs are installed. `FORMATLY_TESSERACT` selects the executable; `FORMATLY_OCR_LANGS` selects installed languages, for example `chi_sim+eng`. The default prefers installed `chi_sim`, then `eng`. OCR is not downloaded automatically, and uncertain recognition remains subject to review.

PDF body font checks require `settings.body.pdf_region_mm`, such as `{"top":30,"bottom":25,"left":25,"right":25}`. Values are millimeters from each page edge; only native characters fully inside that region are compared. This region does not establish the document's margins.

Document JSON supports ordinary JSON and the `formatly.document.v1` schema with `title`, `paragraphs`, and `fields`. See the [example](examples/document.json) and [schema](examples/document.schema.json). Duplicate keys, unknown versions, invalid structures, and non-finite numbers are rejected. Rule profile JSON has a separate purpose and is imported with `profiles import`.

---

## Core workflow

Choose a preset or saved profile to check a draft directly, or upload school templates and instructions to create a user-confirmed profile first. Both entries use the same checking, reporting, repair, and recheck service. The steps below describe creating a profile from school materials.

1. On **新建检测** (New check), choose **学校模板** (School template) and drop the school file. The current document type is used, and a successful upload opens the review directly. More templates or instructions can be added to the same group; reopen saved groups from **学校要求** (School requirements).
2. Check the extracted requirements against the originals, including fonts, sizes, and other values. Choose the correct value where sources disagree. Requirements that need manual review or cannot be checked remain listed; excluding a requirement needs a reason.
3. Confirm the requirements to create checking profiles. In step 3, choose **使用此方案检测** (Check with this profile) to open a new check with the profile and document type selected, then upload the original. Saved profiles remain available under **学校要求 → 已保存方案**; selections passed to a new check survive refresh.
4. Review the report. For supported DOCX problems, preview and select repairs to generate a new copy and run a full check. Download the corrected document and change record from the new task. Edit remaining problems yourself and use **检测修改稿** to check the revision.
5. To compare a related thesis, internship report, and certificate, create a group in **检测记录 → 材料分组核验** (Check history → Material groups) and link each document's check to it. Comparisons use the latest check for each required document type. Missing documents, ambiguous fields, and failed checks remain marked for review.

The built-in [academic formatting plugin](docs/native-plugin.md) checks paragraph, heading, and section properties without an external engine. Copy the `academic` profile and configure the required values, or confirm requirements from school sources. Unresolved properties require review; edit new native properties in Word/WPS and recheck.

Selected repairs support precisely located page dimensions, four page margins, body fonts, font sizes, and automatic line spacing. Original files and reports are preserved; an old paired PDF is not reused. Protected, signed, or tracked-change documents, complex layout, complex-script font sizes, missing content, and unresolved locations require manual editing. Historical reports without precise locations need a new check. Applied edits do not replace the new check's actual result.

| Profile | Use | Dependencies |
|:--------|:----|:-------------|
| `generic` | Basic checks for all five formats; default A4 checks where page evidence exists | Core dependencies; optional OCR for scans |
| `certificate` | Basic internship certificate pages, required fields, and manual signature/stamp review | Material type `certificate`; core dependencies |
| School-generated profiles | Confirmed requirements for `thesis`, `intern`, or `certificate` | Plugins and dependencies declared by that profile |
| `school-specific` | DOCX checks after the optional external engine is connected; omitted from the scheme list | Configured school engine, its Python environment, source files, and fixed vendor resources |

Use `generic` or a school-generated profile for any school and author. `school-specific` contains user-confirmed school rules, and its engine supports DOCX only. See [school engine configuration](#the-school-engine-is-unavailable).

---

## Reports and boundaries

Each task preserves an input copy, request, rule snapshot, runtime information, and artifacts in its data directory. Checks run on the copies and compare hashes before and after execution; the CLI also verifies the supplied original files. Drafts are not automatically edited.

| State | Meaning |
|:------|:--------|
| Task `queued` / `running` | Waiting / processing |
| Task `completed` | Processing finished; document errors may still exist |
| Task `failed` / `interrupted` | Execution failed / stopped |
| Result `needs_changes` | Formatting deviations were found |
| Result `review_required` | No identified errors, but review remains necessary |
| Result `passed` | No issues found within the checks actually covered |
| Result `incomplete` | The detection chain did not finish completely |

Reports include input format and extraction details, rule snapshots and hashes, school sources, checks, and engine evidence. Rule states are `passed`, `failed`, `manual`, `not_checked`, `unsupported`, `error`, and `not_applicable`. An empty issue list or a valid document package alone cannot establish a formatting pass. Document deviations (`document_counts`) and execution problems (`execution_errors`) are recorded separately.

JSON supports programmatic use; Markdown and HTML support reading. Standalone HTML embeds Vue, CSS, result data, the transparent brand icon, and license notices. Its report content, filters, and search work without adjacent files or a network connection.

Files are limited to **40MiB** each. Extracted text is limited to **1MiB**; JSON has a **2MiB** raw-file limit and a **1MiB** decoded-text limit. A PDF may contain up to **300 processed pages**, with OCR limited to **20 pages**. Partial extraction retains an incomplete or review state. Save `.doc` files as DOCX before checking.

Only DOCX drafts can have an additional paired PDF or use optional [local Word/WPS export](docs/office-rendering.md). Matching extractable text does not certify page order, figures, version identity, or full visual correspondence. Field consistency does not authenticate signatures, stamps, or the underlying material. Formatly does not produce plagiarism scores, AI-content scores, or school approval certificates.

---

## CLI

Replace example paths and IDs with your own. Use a new or empty directory for `--output`:

```powershell
python -m formatly check --input 'thesis.docx' --profile generic --kind thesis --output 'results/check-001'
python -m formatly check --input 'thesis.pdf' --profile generic --json
python -m formatly check --input examples/document.json --profile generic --json
python -m formatly profiles list
python -m formatly profiles preflight generic --kind thesis --format pdf
python -m formatly plugins list
python -m formatly doctor
python -m formatly jobs list --query 'thesis' --status completed --limit 50 --offset 0
```

Exit codes: `0` means execution finished without identified formatting errors, possibly with warnings or manual review; `1` means execution finished with formatting errors; `2` means invalid input, configuration problems, or incomplete execution. Read the report as well as the exit code.

<details>
<summary>School requirements, material collections, task history, and rendering</summary>

```powershell
python -m formatly schools create --name 'Graduation materials'
python -m formatly schools add-source 'SCHOOL_ID' --source 'template.docx' --kind thesis --role template
python -m formatly schools add-source 'SCHOOL_ID' --source 'instructions.pdf' --kind thesis --role instructions
python -m formatly schools show 'SCHOOL_ID'
# Review the candidates and prepare a requirements JSON file before confirming.
python -m formatly schools confirm 'SCHOOL_ID' --requirements 'confirmed-requirements.json' --expected-version 3
python -m formatly profiles preflight 'PROFILE_ID' --kind thesis --format pdf

python -m formatly collections create --name 'Graduation set' --required-kind thesis --required-kind intern --required-kind certificate
python -m formatly check --input 'certificate.docx' --kind certificate --profile certificate --collection 'COLLECTION_ID'
python -m formatly collections show 'COLLECTION_ID'

python -m formatly --data-dir 'formatly-data' jobs list
python -m formatly --data-dir 'formatly-data' jobs show 'TASK_ID'
python -m formatly --data-dir 'formatly-data' jobs retry 'TASK_ID'
# Ordinary DOCX export needs Windows, a local Word/WPS app, and pywin32 from requirements.txt.
python -m formatly check --input 'thesis.docx' --profile generic --kind thesis --render-word
# External school profiles retain their engine's export interface.
python -m formatly check --input 'thesis.docx' --profile school-specific --kind thesis --render-word
```

`schools add-source` also accepts `--transcription 'verified-text.txt'` for a reviewed PDF text override. Original automatic extraction and source files remain available. `jobs list` returns task summaries with `total`, `stats`, `offset`, and `limit`; use `jobs show` for full checks and evidence. Retrying uses the saved input and rules; checking an edited draft requires a new upload or `check`.

</details>

---

## Development and checks

Node.js 22+ is needed for frontend development and builds. The built workbench runs with Python and local static resources; it does not need Node.js, a CDN, or a model service. Build the workbench and report template before running Python tests that generate HTML reports:

```powershell
cd frontend
npm ci
npm test
npm run typecheck
npm run build
cd ..
python -m pip install -r requirements.txt
ruff check .
pyright
python -m unittest discover -s tests -q
python -m compileall -q formatly examples/example-plugin scripts app.py start_dev.py
python scripts/submission_check.py
python start_dev.py
```

`requirements.txt` installs the runtime libraries together with Ruff, Pyright, ReportLab, python-docx, Docling Parse, and psutil. The `pywin32` line is marked `sys_platform == "win32"`, so macOS and Linux skip it. `ruff check .` checks Python syntax, undefined or unused names, loop closure bindings, and selected common errors. `pyright` checks the backend, scripts, tests, plugin examples, and root launchers using Python 3.11 typing rules and the project `.venv`. Generated files, runtime data, and caches are excluded from source checks. `python scripts/submission_check.py` confirms that the virtual environment, build output, caches, runtime data, and local IDE settings stay ignored, and scans files that would be committed for private keys, tokens, and broken documentation links. Word/WPS, Tesseract, and language packs stay local and are not installed by the dependency file.

`start_dev.py` uses the project `.venv` when present, checks its environment, starts the same Python backend and Vite, and waits for the health API, frontend, and proxy before opening a browser. Defaults are **8765** for the backend and **5173** for Vite. Use `--local-only`, `--no-browser`, `--backend-port`, `--frontend-port`, `--data-dir`, or `--verbose-logs` as needed. Stop with Ctrl+C or `python start_dev.py stop`; it reclaims its own processes and does not terminate unrelated port owners. Run `app.py` and `start_dev.py` separately when using the same backend port.

Server settings use `FORMATLY_HOST`, `FORMATLY_PORT`, and `FORMATLY_OPEN_BROWSER`; CLI arguments take precedence. Separate Vite startup supports `FORMATLY_DEV_HOST`, `FORMATLY_DEV_PORT`, and `FORMATLY_API_TARGET` (default `http://127.0.0.1:8765`). The development launcher keeps these settings aligned. Both servers enforce their permitted addresses and request origins. The workbench starts from the project directory and reads `frontend/dist`.

---

## Layout

```text
app.py                   Built workbench entry
start_dev.py             Python + Vite development launcher
formatly/                Python backend only
  application/           Shared task service, pipeline, reports, and repairs
  documents/              Document extraction and isolated PDF worker
  persistence/            Rules, school sources, jobs, and material sets
  interfaces/             CLI, HTTP, startup, and network adapters
  plugins/ / adapters/   Detection plugins and school engine adapters
frontend/
  src/                   Vue views, shared components, API, and composables
  public/                Transparent brand icon and dependency notices
  scripts/               Standalone report shell and build script
  dist/                  Build output, excluded by .gitignore
docs/                    Formats, built-in rules, structure, export, and external engines
examples/                Profiles, document JSON/schema, and plugin example
tests/                   Python checks for the shared business chain
scripts/                 Evaluation, samples, checks, and the submission check
```

---

## Documentation

| Document | Contents |
|:---------|:---------|
| [中文 README](README.md) | Chinese installation and product guide |
| [Frontend contract](frontend/ARCHITECTURE.md) | Components, state, and interactions |
| [External engine setup](docs/external-engines.md) | Compatible engine package, local configuration, verification, use, and removal |
| [Document formats](docs/document-formats.md) | Extraction, PDF/OCR, JSON, and input boundaries |
| [Academic formatting](docs/native-plugin.md) / [Structure checks](docs/academic-structure.md) | Paragraph, heading, caption, reference, and page-number limits |
| [Local export](docs/office-rendering.md) | Read-only Word/WPS export on Windows |
| [Examples](examples/README.md) | Profiles, structured documents, and an executable plugin |
| [LICENSE](LICENSE) | MIT terms |

The detailed technical documents currently use Chinese.

---

## FAQ

**The frontend or report template is missing.** Run `npm ci` and `npm run build` in `frontend/`, then start the Python service. Both `index.html` and `report-template.html` are needed. Normal startup with complete build resources does not require Node.js.

**A scanned PDF has no usable text.** Check **环境诊断** (Environment diagnostics) or `python -m formatly doctor`. Install local Tesseract and the appropriate language packs, or provide reviewed source text for school PDF requirements. OCR uncertainty and extraction limits remain visible in the report.

**There are zero errors. Has the school accepted the document?** Check rule coverage, manual items, unsupported requirements, extraction completeness, and execution errors. A completed task is not a certificate of full compliance. Real school templates, drafts, and expert annotations are required to assess accuracy.

<a id="the-school-engine-is-unavailable"></a>
**The school engine is unavailable.** Open **Settings → Runtime environment → External school engine** for setup instructions and staged checks. On the host running Formatly, prepare a complete compatible engine and run `python -m formatly engines configure --root 'engine directory'` (optionally `--python`). Configuration is saved only after verification; restart the backend with the same data directory. Use `engines check` to recheck and `engines clear` to remove saved configuration. Environment variables override saved settings. See the [setup guide](docs/external-engines.md). Presets and profiles generated by uploading and confirming school requirements work independently of this optional engine.

**Where are my documents and results?** Set `--data-dir` or `FORMATLY_DATA_DIR`. Defaults are `%LOCALAPPDATA%\Formatly` on Windows, `~/Library/Application Support/Formatly` on macOS, and `$XDG_DATA_HOME/formatly` or `~/.local/share/formatly` on Linux. Back up the complete directory for tasks, profiles, school sources, and reports. `.verification/tmp` and `.formatly/dev` are temporary test and development files.

**A phone or another computer cannot open the page.** Use the server's LAN address from the startup log, check that devices can reach one another and that the port is allowed by the host firewall, and ensure `--local-only` is not selected. `127.0.0.1` on another device refers to that device. The workbench currently shares one data directory and has no user accounts or per-user isolation.

---

## License

Formatly is distributed under the [MIT License](LICENSE), **Copyright (c) 2026 Formatly**. The license covers the project code, frontend, examples, and documentation.

Dependencies retain their own licenses. [Frontend dependency notices](frontend/public/THIRD_PARTY_NOTICES.txt) accompany the static resources and standalone HTML reports; Python dependencies keep their license files in their respective distributions.
