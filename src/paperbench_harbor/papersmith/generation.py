"""CLI generation hints for constraints already enforced by the core validators.

JSON-schema presentation only: no data coercion, validation relaxation, checkpoint
migration, or mutation of existing receipts. New requests record the expanded schema.
"""

import json
from pathlib import Path

from .integrity import contained, load_state
from .schema import Material, Materials, Support


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
        schema["properties"]["submission_sections"]["items"].update(
            type="string", minLength=3, pattern=r"^[A-Za-z0-9][A-Za-z0-9 .,:'()/?!-]*$"
        )
        schema["properties"]["submission_sections"]["description"] = (
            "Required plain ASCII headings. Use 'and', not '&'; use an ASCII hyphen, "
            "not an en/em dash. No LaTeX commands, braces, math or reserved characters. "
            "Each requirement.section must name one of these headings."
        )

    Material.model_config["json_schema_extra"] = material
    Materials.model_config["json_schema_extra"] = materials
    Support.model_config["json_schema_extra"] = support
