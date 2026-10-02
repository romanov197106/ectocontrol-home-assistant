from pathlib import Path
import ast
import json

root = Path(__file__).resolve().parents[1]
component = root / "custom_components" / "ectocontrol_boiler"
for path in component.rglob("*.py"):
    source = path.read_text(encoding="utf8")
    ast.parse(source, filename=str(path))
    assert "126611" not in source and "417278" not in source, path
for path in root.rglob("*.json"):
    json.loads(path.read_text(encoding="utf8"))
manifest = json.loads((component / "manifest.json").read_text(encoding="utf8"))
assert manifest["domain"] == component.name
assert manifest["config_flow"] is True
assert not list(root.rglob("*.pyc"))
print("Package syntax, JSON and personal object ID checks passed")
