"""
Agent tool: add or remove OWL classes, object properties, and datatype
properties in an RDF ontology, keeping project.yaml in sync.

Import and call these functions directly — each returns a dict with:
  name, description, results: {rdf, yaml, action}

Or run as a CLI script:
  python3 scripts/edit_ontology.py <add|remove> <class|object_property|datatype_property> <name> --rdf <path> [options]

Options:
  --rdf <path>          Path to ontology.rdf (required)
  --yaml <path>         Path to project.yaml (optional; updates node_types/edge_types)
  --parent <name>       Parent class for add class
  --domain <name>       Domain class for add object_property
  --range <name>        Range class for add object_property
  --subproperty-of <n>  Parent property for add datatype_property
  --range-type <type>   XSD type for add datatype_property (default: xsd:string)
  --inactive            Add as commented-out inactive entry in project.yaml
  --dry-run             Print what would change without writing files
  -h, --help            Show this help message and exit

Examples:
  python3 scripts/edit_ontology.py add class MyNode --rdf data/ontology/ontology.rdf --yaml config/project.yaml --parent GeneticEntity
  python3 scripts/edit_ontology.py add object_property myEdge --rdf data/ontology/ontology.rdf --domain Gene --range Disease --inactive
  python3 scripts/edit_ontology.py remove class MyNode --rdf data/ontology/ontology.rdf --yaml config/project.yaml --dry-run

Exit codes: 0 success, 1 error.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _ontology_utils import _extract_names, _get_base_iri, _read_rdf


_XSD = "http://www.w3.org/2001/XMLSchema#"
_SEPARATOR = "\n    \n\n\n"  # whitespace between declaration blocks in the RDF


# ---------------------------------------------------------------------------
# RDF helpers
# ---------------------------------------------------------------------------

def _iri(name: str, base_iri: str) -> str:
    return f"{base_iri}#{name}"


def _make_rdf_block(owl_type: str, name: str, base_iri: str, children: list[str]) -> str:
    """Build a declaration block (without leading separator)."""
    iri = _iri(name, base_iri)
    if children:
        body = "\n".join(f"        {c}" for c in children)
        return f'    <!-- {iri} -->\n\n    <{owl_type} rdf:about="{iri}">\n{body}\n    </{owl_type}>'
    else:
        return f'    <!-- {iri} -->\n\n    <{owl_type} rdf:about="{iri}"/>'


def _insert_rdf_block(rdf_text: str, owl_type: str, name: str, block: str, base_iri: str) -> str:
    existing = _extract_names(rdf_text, owl_type)
    if name in existing:
        raise ValueError(f"{owl_type} '{name}' already exists in the ontology.")

    successor = next((n for n in existing if n > name), None)

    if successor:
        marker = f"{_SEPARATOR}    <!-- {_iri(successor, base_iri)} -->"
        new_section = f"{_SEPARATOR}{block}{_SEPARATOR}    <!-- {_iri(successor, base_iri)} -->"
        return rdf_text.replace(marker, new_section, 1)
    elif existing:
        last_iri = re.escape(_iri(existing[-1], base_iri))
        pattern = re.compile(
            rf"(    <!-- {last_iri} -->.*?(?:</{re.escape(owl_type)}>|/>))",
            re.DOTALL,
        )
        m = pattern.search(rdf_text)
        if not m:
            raise ValueError(f"Could not locate block for '{existing[-1]}' in the RDF.")
        end = m.end()
        return rdf_text[:end] + _SEPARATOR + block + rdf_text[end:]
    else:
        raise ValueError(f"No existing {owl_type} declarations found; cannot determine insertion point.")


def _remove_rdf_block(rdf_text: str, owl_type: str, name: str, base_iri: str) -> str:
    existing = _extract_names(rdf_text, owl_type)
    if name not in existing:
        raise ValueError(f"{owl_type} '{name}' not found in the ontology.")

    escaped_iri = re.escape(_iri(name, base_iri))
    escaped_type = re.escape(owl_type)
    # Two alternatives: full block (children + closing tag) or self-closing opening tag.
    # The original |/> alternation was too broad — it matched child element />
    # before the block's own closing tag, leaving trailing children as stray content.
    pattern = re.compile(
        rf"{re.escape(_SEPARATOR)}    <!-- {escaped_iri} -->"
        rf"(?:.*?</{escaped_type}>|\n\n    <{escaped_type}[^>]*/>)",
        re.DOTALL,
    )
    result, n = pattern.subn("", rdf_text, count=1)
    if n == 0:
        raise ValueError(f"Could not find and remove block for '{name}'.")
    return result


# ---------------------------------------------------------------------------
# project.yaml helpers
# ---------------------------------------------------------------------------

def _yaml_add_entry(yaml_text: str, section: str, name: str, active: bool) -> str:
    """Insert name alphabetically into the active or inactive group of a yaml list."""
    lines = yaml_text.splitlines(keepends=True)
    in_section = False
    active_entries: list[tuple[int, str]] = []
    inactive_entries: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{section}:"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                active_entries.append((i, stripped[2:].split("#")[0].strip()))
            elif stripped.startswith("# - "):
                inactive_entries.append((i, stripped[4:].split("#")[0].strip()))
            elif stripped and not stripped.startswith("#") and ":" in stripped:
                break

    all_names = [e[1] for e in active_entries + inactive_entries]
    if name in all_names:
        raise ValueError(f"'{name}' already exists in {section} of project.yaml.")

    entries = active_entries if active else inactive_entries
    prefix = "    - " if active else "    # - "
    successor = next((idx for idx, n in entries if n > name), None)

    if successor is not None:
        lines.insert(successor, f"{prefix}{name}\n")
    elif entries:
        lines.insert(entries[-1][0] + 1, f"{prefix}{name}\n")
    else:
        in_section = False
        insert_at = len(lines)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{section}:"):
                in_section = True
                continue
            if in_section and stripped and not stripped.startswith("#") and ":" in stripped:
                insert_at = i
                break
        lines.insert(insert_at, f"{prefix}{name}\n")

    return "".join(lines)


def _yaml_remove_entry(yaml_text: str, section: str, name: str) -> str:
    lines = yaml_text.splitlines(keepends=True)
    in_section = False
    remove_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{section}:"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- ") or stripped.startswith("# - "):
                entry = stripped.lstrip("# ").lstrip("- ").split("#")[0].strip()
                if entry == name:
                    remove_idx = i
                    break
            elif stripped and not stripped.startswith("#") and ":" in stripped:
                break

    if remove_idx is None:
        raise ValueError(f"'{name}' not found in {section} of project.yaml.")

    del lines[remove_idx]
    return "".join(lines)


# ---------------------------------------------------------------------------
# Public agent functions
# ---------------------------------------------------------------------------

def add_class(
    ontology_path: str | Path,
    name: str,
    parent: str | None = None,
    project_yaml_path: str | Path | None = None,
    active: bool = True,
    dry_run: bool = False,
) -> dict:
    """Add an owl:Class to the ontology and optionally to project.yaml node_types."""
    rdf_path = Path(ontology_path)
    rdf_text = _read_rdf(rdf_path)
    base_iri = _get_base_iri(rdf_text)

    children = []
    if parent:
        children.append(f'<rdfs:subClassOf rdf:resource="{_iri(parent, base_iri)}"/>')

    new_rdf = _insert_rdf_block(rdf_text, "owl:Class", name, _make_rdf_block("owl:Class", name, base_iri, children), base_iri)
    new_yaml = None
    yaml_updated = None

    if project_yaml_path:
        yaml_path = Path(project_yaml_path)
        new_yaml = _yaml_add_entry(yaml_path.read_text(), "node_types", name, active)
        yaml_updated = str(yaml_path)

    if not dry_run:
        rdf_path.write_text(new_rdf)
        if new_yaml is not None:
            Path(project_yaml_path).write_text(new_yaml)

    return {
        "name": "add_class",
        "description": f"{'[dry-run] ' if dry_run else ''}Added owl:Class '{name}'" + (f" (subClassOf {parent})" if parent else "") + ".",
        "results": {"rdf": str(rdf_path), "yaml": yaml_updated, "action": "add", "dry_run": dry_run},
    }


def remove_class(
    ontology_path: str | Path,
    name: str,
    project_yaml_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Remove an owl:Class from the ontology and optionally from project.yaml node_types."""
    rdf_path = Path(ontology_path)
    rdf_text = _read_rdf(rdf_path)
    base_iri = _get_base_iri(rdf_text)

    new_rdf = _remove_rdf_block(rdf_text, "owl:Class", name, base_iri)
    new_yaml = None
    yaml_updated = None

    if project_yaml_path:
        yaml_path = Path(project_yaml_path)
        new_yaml = _yaml_remove_entry(yaml_path.read_text(), "node_types", name)
        yaml_updated = str(yaml_path)

    if not dry_run:
        rdf_path.write_text(new_rdf)
        if new_yaml is not None:
            Path(project_yaml_path).write_text(new_yaml)

    return {
        "name": "remove_class",
        "description": f"{'[dry-run] ' if dry_run else ''}Removed owl:Class '{name}'.",
        "results": {"rdf": str(rdf_path), "yaml": yaml_updated, "action": "remove", "dry_run": dry_run},
    }


def add_object_property(
    ontology_path: str | Path,
    name: str,
    domain: str | None = None,
    range_: str | None = None,
    project_yaml_path: str | Path | None = None,
    active: bool = True,
    dry_run: bool = False,
) -> dict:
    """Add an owl:ObjectProperty to the ontology and optionally to project.yaml edge_types."""
    rdf_path = Path(ontology_path)
    rdf_text = _read_rdf(rdf_path)
    base_iri = _get_base_iri(rdf_text)

    children = []
    if domain:
        children.append(f'<rdfs:domain rdf:resource="{_iri(domain, base_iri)}"/>')
    if range_:
        children.append(f'<rdfs:range rdf:resource="{_iri(range_, base_iri)}"/>')

    new_rdf = _insert_rdf_block(rdf_text, "owl:ObjectProperty", name, _make_rdf_block("owl:ObjectProperty", name, base_iri, children), base_iri)
    new_yaml = None
    yaml_updated = None

    if project_yaml_path:
        yaml_path = Path(project_yaml_path)
        new_yaml = _yaml_add_entry(yaml_path.read_text(), "edge_types", name, active)
        yaml_updated = str(yaml_path)

    if not dry_run:
        rdf_path.write_text(new_rdf)
        if new_yaml is not None:
            Path(project_yaml_path).write_text(new_yaml)

    return {
        "name": "add_object_property",
        "description": f"{'[dry-run] ' if dry_run else ''}Added owl:ObjectProperty '{name}'.",
        "results": {"rdf": str(rdf_path), "yaml": yaml_updated, "action": "add", "dry_run": dry_run},
    }


def remove_object_property(
    ontology_path: str | Path,
    name: str,
    project_yaml_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Remove an owl:ObjectProperty from the ontology and optionally from project.yaml edge_types."""
    rdf_path = Path(ontology_path)
    rdf_text = _read_rdf(rdf_path)
    base_iri = _get_base_iri(rdf_text)

    new_rdf = _remove_rdf_block(rdf_text, "owl:ObjectProperty", name, base_iri)
    new_yaml = None
    yaml_updated = None

    if project_yaml_path:
        yaml_path = Path(project_yaml_path)
        new_yaml = _yaml_remove_entry(yaml_path.read_text(), "edge_types", name)
        yaml_updated = str(yaml_path)

    if not dry_run:
        rdf_path.write_text(new_rdf)
        if new_yaml is not None:
            Path(project_yaml_path).write_text(new_yaml)

    return {
        "name": "remove_object_property",
        "description": f"{'[dry-run] ' if dry_run else ''}Removed owl:ObjectProperty '{name}'.",
        "results": {"rdf": str(rdf_path), "yaml": yaml_updated, "action": "remove", "dry_run": dry_run},
    }


def add_datatype_property(
    ontology_path: str | Path,
    name: str,
    subproperty_of: str | None = None,
    range_type: str = "xsd:string",
    dry_run: bool = False,
) -> dict:
    """Add an owl:DatatypeProperty to the ontology. project.yaml is not modified."""
    rdf_path = Path(ontology_path)
    rdf_text = _read_rdf(rdf_path)
    base_iri = _get_base_iri(rdf_text)
    xsd_type = range_type.removeprefix("xsd:")

    children = []
    if subproperty_of:
        children.append(f'<rdfs:subPropertyOf rdf:resource="{_iri(subproperty_of, base_iri)}"/>')
    children.append(f'<rdfs:range rdf:resource="{_XSD}{xsd_type}"/>')

    new_rdf = _insert_rdf_block(rdf_text, "owl:DatatypeProperty", name, _make_rdf_block("owl:DatatypeProperty", name, base_iri, children), base_iri)

    if not dry_run:
        rdf_path.write_text(new_rdf)

    return {
        "name": "add_datatype_property",
        "description": f"{'[dry-run] ' if dry_run else ''}Added owl:DatatypeProperty '{name}' (range: {range_type}).",
        "results": {"rdf": str(rdf_path), "yaml": None, "action": "add", "dry_run": dry_run},
    }


def remove_datatype_property(
    ontology_path: str | Path,
    name: str,
    dry_run: bool = False,
) -> dict:
    """Remove an owl:DatatypeProperty from the ontology. project.yaml is not modified."""
    rdf_path = Path(ontology_path)
    rdf_text = _read_rdf(rdf_path)
    base_iri = _get_base_iri(rdf_text)

    new_rdf = _remove_rdf_block(rdf_text, "owl:DatatypeProperty", name, base_iri)

    if not dry_run:
        rdf_path.write_text(new_rdf)

    return {
        "name": "remove_datatype_property",
        "description": f"{'[dry-run] ' if dry_run else ''}Removed owl:DatatypeProperty '{name}'.",
        "results": {"rdf": str(rdf_path), "yaml": None, "action": "remove", "dry_run": dry_run},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Add or remove OWL declarations in an ontology RDF. Outputs JSON to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 edit_ontology.py add class MyNode --rdf data/ontology/ontology.rdf --yaml config/project.yaml --parent GeneticEntity\n"
            "  python3 edit_ontology.py add object_property myEdge --rdf data/ontology/ontology.rdf --domain Gene --range Disease --inactive\n"
            "  python3 edit_ontology.py remove class MyNode --rdf data/ontology/ontology.rdf --dry-run"
        ),
    )
    parser.add_argument("action", choices=["add", "remove"])
    parser.add_argument("type", choices=["class", "object_property", "datatype_property"])
    parser.add_argument("name", help="Local OWL name (case-sensitive)")
    parser.add_argument("--rdf", type=Path, required=True, help="Path to ontology.rdf")
    parser.add_argument("--yaml", type=Path, default=None, help="Path to project.yaml")
    parser.add_argument("--parent", default=None, help="Parent class (add class only)")
    parser.add_argument("--domain", default=None, help="Domain class (add object_property only)")
    parser.add_argument("--range", dest="range_", default=None, help="Range class (add object_property only)")
    parser.add_argument("--subproperty-of", default=None, help="Parent property (add datatype_property only)")
    parser.add_argument("--range-type", default="xsd:string", help="XSD range type (add datatype_property, default: xsd:string)")
    parser.add_argument("--inactive", action="store_true", help="Add as inactive (commented-out) entry in project.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing files")
    args = parser.parse_args()

    if not args.rdf.exists():
        print(f"Error: RDF file not found: {args.rdf}", file=sys.stderr)
        sys.exit(1)
    if args.yaml and not args.yaml.exists():
        print(f"Error: project.yaml not found: {args.yaml}", file=sys.stderr)
        sys.exit(1)

    active = not args.inactive

    try:
        if args.action == "add" and args.type == "class":
            result = add_class(args.rdf, args.name, parent=args.parent, project_yaml_path=args.yaml, active=active, dry_run=args.dry_run)
        elif args.action == "remove" and args.type == "class":
            result = remove_class(args.rdf, args.name, project_yaml_path=args.yaml, dry_run=args.dry_run)
        elif args.action == "add" and args.type == "object_property":
            result = add_object_property(args.rdf, args.name, domain=args.domain, range_=args.range_, project_yaml_path=args.yaml, active=active, dry_run=args.dry_run)
        elif args.action == "remove" and args.type == "object_property":
            result = remove_object_property(args.rdf, args.name, project_yaml_path=args.yaml, dry_run=args.dry_run)
        elif args.action == "add" and args.type == "datatype_property":
            result = add_datatype_property(args.rdf, args.name, subproperty_of=args.subproperty_of, range_type=args.range_type, dry_run=args.dry_run)
        elif args.action == "remove" and args.type == "datatype_property":
            result = remove_datatype_property(args.rdf, args.name, dry_run=args.dry_run)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
