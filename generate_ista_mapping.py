"""Convert CardioKB ontology_mappings.yaml to ista-native YAML format.

ista's C++ YAML parser requires list items to be indented under their parent key.
We generate the YAML manually to ensure correct indentation.
"""
import json
import yaml
from pathlib import Path


def write_yaml_value(f, value, indent=0):
    """Write a YAML value with proper indentation for ista compatibility."""
    prefix = "  " * indent
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                f.write(f"{prefix}{k}:\n")
                write_yaml_value(f, v, indent + 1)
            elif isinstance(v, bool):
                f.write(f"{prefix}{k}: {'true' if v else 'false'}\n")
            elif v is None:
                f.write(f"{prefix}{k}: null\n")
            else:
                val = json.dumps(str(v)) if isinstance(v, str) and any(c in str(v) for c in ':#{}[]') else str(v)
                f.write(f"{prefix}{k}: {val}\n")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    if first:
                        if isinstance(v, (dict, list)):
                            f.write(f"{prefix}- {k}:\n")
                            write_yaml_value(f, v, indent + 2)
                        else:
                            f.write(f"{prefix}- {k}: {v}\n")
                        first = False
                    else:
                        if isinstance(v, (dict, list)):
                            f.write(f"{prefix}  {k}:\n")
                            write_yaml_value(f, v, indent + 2)
                        else:
                            f.write(f"{prefix}  {k}: {v}\n")
            else:
                f.write(f"{prefix}- {value}\n")


config_dir = Path("config")
mappings_raw = yaml.safe_load((config_dir / "ontology_mappings.yaml").read_text())
mappings = mappings_raw.get("mappings", mappings_raw)
mappings = {k: v for k, v in mappings.items() if v is not None}

# Load enabled sources from databases.yaml
dbs_raw = yaml.safe_load((config_dir / "databases.yaml").read_text()).get("databases", {})
enabled_sources = {k for k, v in dbs_raw.items() if isinstance(v, dict) and v.get("enabled", False)}

base_iri = "http://example.org/ontologies/kg.owl#"
data_dir = "../template/data/processed"

sources = {}
node_mappings = []
relationship_mappings = []

for key, cfg in mappings.items():
    if cfg.get("skip", False):
        continue

    source_name = key.split(".")[0]

    # Skip sources not in databases.yaml enabled list
    if source_name not in enabled_sources:
        continue

    filename = cfg.get("source_filename", key.split(".")[-1] + ".tsv")
    source_key = key.replace(".", "_")
    source_path = f"{data_dir}/{source_name}/{filename}"

    # Skip if source file doesn't exist
    resolved = config_dir / source_path
    if not resolved.exists():
        print(f"  SKIP {key}: file not found at {resolved}")
        continue

    sources[source_key] = {"type": "tsv", "path": source_path}

    data_type = cfg.get("data_type")

    if data_type == "node":
        props = []
        for col, prop in cfg.get("property_map", {}).items():
            props.append({"column": col, "property": prop})

        nm = {
            "name": key,
            "source": source_key,
            "mode": "create",
            "target_class": cfg["owl_class"],
            "iri_column": cfg.get("id_column", "id"),
        }
        if props:
            nm["properties"] = props
        node_mappings.append(nm)

    elif data_type == "relationship":
        rm = {
            "name": key,
            "source": source_key,
            "relationship": cfg["owl_relationship"],
            "subject": {
                "class_name": cfg["source_node_type"],
                "column": cfg["source_id_column"],
                "match_property": cfg.get("source_match_property", "geneSymbol"),
            },
            "object": {
                "class_name": cfg["target_node_type"],
                "column": cfg["target_id_column"],
                "match_property": cfg.get("target_match_property", "commonName"),
            },
        }
        relationship_mappings.append(rm)

output_path = Path("config/ista_mapping.yaml")
with open(output_path, "w") as f:
    f.write(f'version: "1.0"\n')
    f.write(f'project_name: "CardioKB"\n')
    f.write(f'base_iri: "{base_iri}"\n')
    f.write(f'ontology_path: "../template/data/ontology/ontology.rdf"\n')
    f.write(f'populated_ontology_path: "../template/data/output/ontology_populated.rdf"\n')
    f.write(f'\n')
    f.write(f'sources:\n')
    write_yaml_value(f, sources, indent=1)
    f.write(f'\nnode_mappings:\n')
    write_yaml_value(f, node_mappings, indent=1)
    f.write(f'\nrelationship_mappings:\n')
    write_yaml_value(f, relationship_mappings, indent=1)

print(f"Generated {output_path}")
print(f"  Sources: {len(sources)}")
print(f"  Node mappings: {len(node_mappings)}")
print(f"  Relationship mappings: {len(relationship_mappings)}")
