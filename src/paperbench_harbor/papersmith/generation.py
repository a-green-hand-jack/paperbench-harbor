"""CLI generation hints for constraints already enforced by the core validators.

JSON-schema presentation only: no data coercion, validation relaxation, checkpoint
migration, or mutation of existing receipts. New requests record the expanded schema.
"""

import json
from pathlib import Path

from .integrity import contained, load_state
from .oracle import Oracle, Table
from .schema import Material, Materials, Review, Support


def configure_generation_schema(workspace=None):
    def sources():
        if workspace is None or not (workspace / "run.json").is_file():
            return [], {}
        from .product import ORDER

        state = load_state(workspace, ORDER)
        candidates = [
            c
            for c in state["candidates"]
            if not c.get("excluded") and c["stages"].get("deliver", {}).get("status") != "passed"
        ]
        active = next(
            (c for c in candidates if c["stages"].get("materials", {}).get("status") == "running"),
            None,
        )
        if active is None:
            return [], {}
        root = contained(workspace, Path(active["stages"]["proposal"]["path"]) / "sources")
        return json.loads((root / "manifest.json").read_text()), json.loads(
            (root / "source-support.json").read_text()
        )

    def material(schema):
        schema["oneOf"] = [
            {
                "required": ["content"],
                "properties": {
                    "content": {"type": "string", "minLength": 1},
                    "copy_source": {"type": "null"},
                },
            },
            {
                "required": ["copy_source"],
                "properties": {
                    "content": {"type": "string", "maxLength": 0},
                    "copy_source": {"type": "string", "minLength": 1},
                },
            },
        ]
        schema["properties"]["content"]["description"] = (
            "Generated text content. For a copied asset, omit this field or use an empty string; "
            "do not put its description or caption here."
        )
        schema["properties"]["copy_source"]["description"] = (
            "Source asset ID to copy byte-for-byte, mutually exclusive with nonempty content."
        )
        manifest, _ = sources()
        if manifest:
            schema["oneOf"][1]["properties"]["copy_source"]["enum"] = [
                r["id"] for r in manifest if r["role"] in {"figure", "data"}
            ]

    def support(schema):
        schema["properties"].pop("quote", None)
        schema["required"] = ["source", "evidence_id"]
        schema["properties"]["source"]["description"] = (
            "Exact internal manifest id, NOT an author/year citation, filename or catalog ID."
        )
        schema["properties"]["evidence_id"] = {
            "type": "string",
            "description": "Choose the S catalog ID that belongs to the named source; no invented quotations.",
        }
        manifest, catalog = sources()
        if manifest:
            choices = []
            for record in manifest:
                sid = record["id"]
                ids = [
                    eid
                    for eid, anchor in catalog.items()
                    if Path(anchor["path"]).name.startswith((sid + ".", sid + "-"))
                ]
                if ids:
                    choices.append(
                        {"properties": {"source": {"const": sid}, "evidence_id": {"enum": ids}}}
                    )
            schema["oneOf"] = choices

    def materials(schema):
        schema["properties"]["items"]["description"] = (
            "Inventory every relevant source item, not just broad dimension summaries. Include all kinds: "
            "figure, table, supplement, method, claim, hypothesis, interpretation, limitation, context, reference. "
            "If a kind is absent, record evidenced non-applicability. Included/substituted table IDs must exactly "
            "match tables IDs; generated CSV/JSON paths are tables/ID.csv and tables/ID.json."
        )
        schema["properties"]["tables"]["description"] = (
            "Exact source table cells, each with its own support; column and units arrays and every row "
            "have the same width. Preserve displayed precision, missing-value markers, caption and notes. "
            "Original image must name a copied public figure when legally available; document actual availability."
        )
        schema["properties"]["submission_sections"]["items"].update(
            type="string", minLength=3, pattern=r"^[A-Za-z0-9][A-Za-z0-9 .,:'()/?!-]*$"
        )
        schema["properties"]["submission_sections"]["description"] = (
            "Required plain ASCII headings. Use 'and', not '&'; use an ASCII hyphen, "
            "not an en/em dash. No LaTeX commands, braces, math or reserved characters. "
            "Each requirement.section must name one of these headings."
        )

    def review(schema):
        schema["description"] = (
            "Return exactly decision, reasoning, checked, findings. Do not rename these fields "
            "to verdict, summary, checks, dimensions or checked_dimensions. checked is an object "
            "keyed by every required review dimension; each value contains exactly assessment "
            "and evidence_ids. Each finding contains exactly classification, evidence, repair; "
            "not severity, dimension, description, evidence_ids or suggested_fix. "
            "Use actual catalog IDs and substantive evidence, never placeholders. "
            "accept requires findings=[]; repair/reject requires concrete findings."
        )

    def oracle(schema):
        if workspace is None or not (workspace / "run.json").is_file():
            return
        from .product import ORDER

        state = load_state(workspace, ORDER)
        active = next(
            (
                c for c in state["candidates"]
                if c["stages"].get("convert", {}).get("status") == "running"
            ),
            None,
        )
        if active is None:
            return
        path = contained(workspace, Path(active["stages"]["materials"]["path"]) / "response.json")
        materials = Materials.model_validate_json(path.read_text())
        figures = [f.path for f in materials.files if f.role == "figure"]
        tables = [t.id for t in materials.tables]
        table_schema = {"items": {"properties": {"source_table": {"enum": tables}}}} if tables else {"maxItems": 0}
        figure_schema = (
            {
                "items": {"properties": {"public_path": {"enum": figures}}},
                "description": "Use exact audited public material paths, without environment/materials or any absolute prefix.",
            }
            if figures else {"maxItems": 0}
        )
        sections = schema["properties"]["sections"]
        sections["minItems"] = sections["maxItems"] = len(materials.submission_sections)
        sections["prefixItems"] = [
            {
                "allOf": [
                    sections["items"],
                    {"properties": {"heading": {"const": heading}, "figures": figure_schema, "tables": table_schema}},
                ]
            }
            for heading in materials.submission_sections
        ]
        sections["description"] = (
            "Use exactly these headings, in order, including any Abstract or References heading "
            "even though separate abstract/bibliography fields also exist: "
            + json.dumps(materials.submission_sections)
        )
        coverage = schema["properties"]["requirement_coverage"]
        coverage["minItems"] = coverage["maxItems"] = len(materials.requirements)

    def table(schema):
        schema["properties"]["rows"]["description"] = (
            "Rectangular data rows only. Every row MUST have exactly len(columns) string cells. "
            "Do not add row labels outside the declared columns, ragged rows, or spanning cells. "
            "Copy exact columns and cell strings from the public table named by source_table, including "
            "its actual missing-value markers and precision. Include every required public table; "
            "the controller renders its public units and notes without inventing or changing them."
        )

    Material.model_config["json_schema_extra"] = material
    Materials.model_config["json_schema_extra"] = materials
    Support.model_config["json_schema_extra"] = support
    Review.model_config["json_schema_extra"] = review
    Oracle.model_config["json_schema_extra"] = oracle
    Table.model_config["json_schema_extra"] = table
