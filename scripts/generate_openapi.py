import json
from collections import OrderedDict
from pathlib import Path

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin

from app.schemas import VersionSchema
from app.weasyprint_controller import app

spec = APISpec(
    title="WeasyPrint Service API",
    version="1.0.0",
    openapi_version="3.0.3",
    plugins=[FlaskPlugin(), MarshmallowPlugin()],
)

spec.components.schema("VersionSchema", schema=VersionSchema)

with app.test_request_context():
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if rule.rule.startswith("/api/docs"):  # exclude Swagger UI
            continue
        if rule.rule == "/static/openapi.json":  # exclude the endpoint that serves the OpenAPI spec
            continue

        view_fn = app.view_functions[rule.endpoint]
        spec.path(view=view_fn)

raw_spec = spec.to_dict()

ordered_spec = OrderedDict()
for key in ["openapi", "info", "servers", "paths", "components"]:
    if key in raw_spec:
        ordered_spec[key] = raw_spec[key]
for key in raw_spec:
    if key not in ordered_spec:
        ordered_spec[key] = raw_spec[key]

formatted = json.dumps(ordered_spec, indent=2, ensure_ascii=False, separators=(",", ": "), sort_keys=False) + "\n"

output_path = Path("app/static/openapi.json")
output_path.parent.mkdir(parents=True, exist_ok=True)

with output_path.open("w", encoding="utf-8") as f:
    f.write(formatted)
