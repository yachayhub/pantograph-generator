# pantograph-generator — STEP-to-G-code generator for a Messer plasma pantograph

## What this is
A Streamlit app ("Pantograph Cutting File Generator") that parses flat-plate STEP
(ISO 10303-21) files and generates Messer plasma pantograph cutting G-code (CAM
workflow for CNC plasma cutting). Used for the user's own CNC/CAM work. Public
GitHub repo. Status: v2.0, actively developed (CAM assets/reference files added
recently).

## Stack
- Python, Streamlit
- `matplotlib`, `plotly` (2D contour + toolpath preview)
- `numpy`
- No version pins in `requirements.txt`

## Commands
- Run locally: `pip install -r requirements.txt && streamlit run app.py`
- Tests: none found
- Deploy: none configured

## Layout
- `app.py` — Streamlit UI: STEP upload, contour/toolpath plotting (matplotlib +
  plotly), G-code preview/download
- `step_parser.py` — lightweight custom STEP parser: extracts 2D lines/arcs from
  the bottom face (Z=0) of a flat plate (`Point2D`, `LineSeg`, `ArcSeg`, `Contour`)
- `gcode_generator.py` — converts parsed contours to Messer-format incremental
  (G91) G-code with G261/G260 pierce blocks and lead-in moves
- `Plate-2966845.step` — sample/reference STEP input
- `Psot_procesador_alejo.cps` — Mach/Messer post-processor reference file
- `1001.txt` — sample generated G-code output (Messer format)
- `requirements.txt`

## Conventions
- Code comments and docstrings are in English; some ancillary filenames are in
  Spanish/mixed ("Psot_procesador_alejo.cps", "croquis" in commit messages).
- G-code output format is specific to Messer plasma pantograph machines
  (`G21/G70/G91/G92` header, `G261/G260` pierce blocks) — do not generalize the
  generator's output format without checking against `Psot_procesador_alejo.cps`
  and a real machine.
- `step_parser.py` only handles flat plates cut from the bottom face (Z=0); it is
  not a general STEP/CAD parser.

## Integrations & env
- No external APIs, databases, or cloud services — fully local file-in/file-out tool.
- No env vars or secrets.

## Delivery
- Local checks before push: `pytest`
- Required CI checks: gitleaks, test. Each must have run and passed; a check that did not run counts as failed. GitHub Free enforces nothing here, so never use `gh pr merge --auto`.
- Merging applies migrations: no
- Deploy verification: TODO: describe how to confirm a deploy succeeded.
- Recovery / rollback: TODO: describe how to recover or roll back a bad deploy/migration.

## Do not
- Do not treat `step_parser.py` as a general-purpose STEP parser — it is scoped to
  flat-plate 2D profile extraction only.
- Do not change the G-code header/pierce-block format without verifying against
  the Messer post-processor reference (`Psot_procesador_alejo.cps`).
- Do not deploy from an agent without asking.

## Related
- No sibling repos identified; self-contained CAM tool.
