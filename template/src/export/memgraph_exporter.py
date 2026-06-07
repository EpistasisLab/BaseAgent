"""
Memgraph-compatible CSV exporter for the KG pipeline.

Extracts typed nodes and relationships from the populated OWL ontology
and writes per-type CSV files suitable for Memgraph's LOAD CSV.

Output files:
    nodes_{NodeType}.csv   — One file per node type with id, properties, :LABEL
    edges_{RelType}.csv    — One file per relationship type with :START_ID, :END_ID, :TYPE
    import.cypher          — Cypher LOAD CSV script for importing all CSVs into Memgraph
"""

import csv
import logging
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from rdflib import Graph, Namespace, RDF, RDFS, OWL
from rdflib.term import Literal

logger = logging.getLogger(__name__)

_MEMGRAPH_IMPORT_PREFIX = "/import-data"


class MemgraphExporter:
    """
    Export a populated OWL ontology to Memgraph-compatible CSV files.

    Reads the RDF/XML file, classifies individuals by their OWL class,
    extracts data properties, and writes typed CSV files.

    Args:
        rdf_files: List of populated RDF file paths.
        output_dir: Directory to write CSV files.
    """

    def __init__(self, rdf_files: List[str], output_dir: str,
                 rel_source_map: Optional[Dict[str, str]] = None):
        self.rdf_files = rdf_files
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._id_to_type: dict[str, str] = {}
        self.rel_source_map = rel_source_map or {}
        self.graph = Graph()

        for rdf_file in rdf_files:
            logger.info(f"Loading RDF: {rdf_file}")
            self.graph.parse(rdf_file, format="xml")
        logger.info(f"Loaded {len(self.graph)} triples")

    def export(self) -> dict:
        """
        Export nodes and edges to typed CSV files, then write an import.cypher script.

        Returns:
            {
                "nodes_count": int,
                "edges_count": int,
                "output_files": [str],
                "cypher_script": str,  # path to import.cypher
            }
        """
        output_files = []
        total_nodes = 0
        total_edges = 0
        node_columns: dict[str, list[str]] = {}
        rel_types: list[str] = []
        edge_prop_columns: dict[str, list[str]] = {}

        # Detect the ontology namespace from the RDF
        ontology_ns = self._detect_namespace()

        # --- Export nodes ---
        nodes_by_type = self._extract_nodes(ontology_ns)
        for node_type, nodes in nodes_by_type.items():
            filename = f"nodes_{node_type}.csv"
            filepath = self.output_dir / filename
            node_columns[node_type] = self._write_node_csv(filepath, nodes, node_type)
            total_nodes += len(nodes)
            output_files.append(str(filepath))
            logger.info(f"  Exported {len(nodes)} {node_type} nodes -> {filename}")

        # --- Export edges ---
        edges_by_type, rel_endpoint_types = self._extract_edges(ontology_ns)
        for rel_type, edges in edges_by_type.items():
            filename = f"edges_{rel_type}.csv"
            filepath = self.output_dir / filename
            sidecar = self.output_dir / f"edge_props_{rel_type}.csv"

            source_label = self.rel_source_map.get(rel_type)

            if sidecar.exists():
                # Use sidecar written by populator — it has edge properties
                shutil.copy2(str(sidecar), str(filepath))
                with open(filepath, newline="") as f:
                    rows = list(csv.DictReader(f))
                if source_label and rows:
                    for row in rows:
                        row["source"] = source_label
                    all_cols = list(rows[0].keys())
                    with open(filepath, "w", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=all_cols)
                        writer.writeheader()
                        writer.writerows(rows)
                all_cols = list(rows[0].keys()) if rows else []
                extra = [c for c in all_cols if c not in {"start_id", "end_id"}]
                edge_prop_columns[rel_type] = extra
                n_edges = len(rows)
                logger.info(f"  Exported {n_edges} {rel_type} edges (with props: {extra}) -> {filename}")
                total_edges += n_edges
            else:
                self._write_edge_csv(filepath, edges, rel_type)
                extra = ["source"] if source_label else []
                edge_prop_columns[rel_type] = extra
                total_edges += len(edges)
                logger.info(f"  Exported {len(edges)} {rel_type} edges -> {filename}")

            output_files.append(str(filepath))
            rel_types.append(rel_type)

        # --- Write Cypher import script ---
        cypher_path = self._write_cypher_script(node_columns, rel_types, rel_endpoint_types, edge_prop_columns)
        output_files.append(str(cypher_path))
        logger.info(f"  Wrote Cypher import script -> {cypher_path.name}")

        logger.info(f"Total: {total_nodes} nodes, {total_edges} edges, "
                     f"{len(output_files)} files")

        return {
            "nodes_count": total_nodes,
            "edges_count": total_edges,
            "output_files": output_files,
            "cypher_script": str(cypher_path),
        }

    def _detect_namespace(self) -> Optional[Namespace]:
        """Detect the ontology namespace from the loaded graph."""
        # Look for the ontology IRI
        for s, p, o in self.graph.triples((None, RDF.type, OWL.Ontology)):
            ns = str(s)
            if not ns.endswith("#"):
                ns += "#"
            logger.info(f"Detected ontology namespace: {ns}")
            return Namespace(ns)

        # Fallback: look for the most common namespace among individuals
        ns_counts = defaultdict(int)
        for s, p, o in self.graph.triples((None, RDF.type, OWL.NamedIndividual)):
            uri = str(s)
            if "#" in uri:
                ns_counts[uri.rsplit("#", 1)[0] + "#"] += 1

        if ns_counts:
            ns = max(ns_counts, key=ns_counts.get)
            logger.info(f"Inferred ontology namespace: {ns}")
            return Namespace(ns)

        logger.warning("Could not detect ontology namespace")
        return None

    def _extract_nodes(self, ontology_ns: Optional[Namespace]) -> Dict[str, list]:
        """
        Extract nodes grouped by their OWL class type.

        Returns:
            Dict mapping class name -> list of node dicts.
        """
        nodes_by_type = defaultdict(list)

        # Find all named individuals and their types
        for individual in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            ind_uri = str(individual)

            # Get the OWL class(es) for this individual
            node_types = []
            for _, _, obj in self.graph.triples((individual, RDF.type, None)):
                obj_str = str(obj)
                if obj_str == str(OWL.NamedIndividual):
                    continue
                # Extract class name from URI
                if "#" in obj_str:
                    class_name = obj_str.rsplit("#", 1)[1]
                elif "/" in obj_str:
                    class_name = obj_str.rsplit("/", 1)[1]
                else:
                    class_name = obj_str
                node_types.append(class_name)

            if not node_types:
                continue

            # Extract local name as node ID
            if "#" in ind_uri:
                node_id = ind_uri.rsplit("#", 1)[1]
            elif "/" in ind_uri:
                node_id = ind_uri.rsplit("/", 1)[1]
            else:
                node_id = ind_uri

            # Extract data properties
            properties = {"id": node_id}
            for pred, obj in self.graph.predicate_objects(individual):
                pred_str = str(pred)
                # Skip RDF/OWL built-in predicates
                if any(pred_str.startswith(ns) for ns in [str(RDF), str(RDFS), str(OWL)]):
                    continue
                # Only data properties (literal values), not object property assertions
                if isinstance(obj, Literal):
                    prop_name = pred_str.rsplit("#", 1)[1] if "#" in pred_str else pred_str
                    properties[prop_name] = str(obj)

            # Add to each type
            for nt in node_types:
                nodes_by_type[nt].append(properties)

        self._id_to_type = {
            node["id"]: node_type
            for node_type, nodes in nodes_by_type.items()
            for node in nodes
        }
        return dict(nodes_by_type)

    def _extract_edges(self, ontology_ns: Optional[Namespace]) -> tuple[Dict[str, list], dict[str, tuple[str, str]]]:
        """
        Extract edges (object property assertions) grouped by relationship type.

        Streams the source RDF/XML files with lxml iterparse instead of
        iterating the in-memory rdflib graph.  This avoids data loss caused
        by rdflib silently dropping triples when memory is constrained (e.g.
        right after the ista populate step on large ontologies).

        Returns:
            Tuple of:
              - Dict mapping relationship name -> list of edge dicts
              - Dict mapping relationship name -> (start_node_type, end_node_type)
        """
        from lxml import etree

        OWL_NS = "http://www.w3.org/2002/07/owl#"
        RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        NAMED_INDIVIDUAL_TAG = f"{{{OWL_NS}}}NamedIndividual"
        RDF_ABOUT = f"{{{RDF_NS}}}about"
        RDF_RESOURCE = f"{{{RDF_NS}}}resource"

        SKIP_NAMESPACES = frozenset([
            RDF_NS,
            "http://www.w3.org/2000/01/rdf-schema#",
            OWL_NS,
            "http://www.w3.org/2001/XMLSchema#",
            "http://www.w3.org/XML/1998/namespace",
        ])

        node_ids = set(self._id_to_type.keys())

        def _local_name(uri: str) -> str:
            if "#" in uri:
                return uri.rsplit("#", 1)[1]
            if "/" in uri:
                return uri.rsplit("/", 1)[1]
            return uri

        edges_by_type: dict[str, list] = defaultdict(list)
        seen: set[tuple[str, str, str]] = set()

        for rdf_file in self.rdf_files:
            context = etree.iterparse(rdf_file, events=("end",),
                                      tag=NAMED_INDIVIDUAL_TAG)
            for _, elem in context:
                about = elem.get(RDF_ABOUT)
                if about is None:
                    elem.clear()
                    continue
                subject_id = _local_name(about)
                if subject_id not in node_ids:
                    elem.clear()
                    continue

                for child in elem:
                    resource = child.get(RDF_RESOURCE)
                    if resource is None:
                        continue
                    tag = child.tag
                    if tag[0] == "{":
                        ns, local = tag[1:].split("}", 1)
                        if ns in SKIP_NAMESPACES:
                            continue
                    else:
                        local = tag

                    object_id = _local_name(resource)
                    if object_id not in node_ids:
                        continue

                    triple = (subject_id, local, object_id)
                    if triple in seen:
                        continue
                    seen.add(triple)

                    edges_by_type[local].append({
                        "start_id": subject_id,
                        "end_id": object_id,
                    })

                elem.clear()

        rel_endpoint_types: dict[str, list[tuple[str, str]]] = {}
        for rel_type, edges in edges_by_type.items():
            start_types: set[str] = set()
            end_types: set[str] = set()
            for edge in edges:
                st = self._id_to_type.get(edge["start_id"])
                et = self._id_to_type.get(edge["end_id"])
                if st:
                    start_types.add(st)
                if et:
                    end_types.add(et)
            if len(start_types) <= 1 and len(end_types) <= 1:
                rel_endpoint_types[rel_type] = [
                    (start_types.pop() if start_types else "",
                     end_types.pop() if end_types else "")
                ]
            else:
                pairs: set[tuple[str, str]] = set()
                for edge in edges:
                    st = self._id_to_type.get(edge["start_id"], "")
                    et = self._id_to_type.get(edge["end_id"], "")
                    pairs.add((st, et))
                rel_endpoint_types[rel_type] = sorted(pairs)

        return dict(edges_by_type), rel_endpoint_types

    def _write_node_csv(self, filepath: Path, nodes: list, node_type: str) -> list[str]:
        """
        Write a node CSV file.

        Returns:
            Property column names for this node type.
            Used by ``_write_cypher_script`` to build CREATE statements.
        """
        if not nodes:
            return []

        # Collect all property keys across all nodes of this type
        all_keys = set()
        for node in nodes:
            all_keys.update(node.keys())

        all_keys.discard("id")
        columns = ["id"] + sorted(all_keys)

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for node in nodes:
                writer.writerow(node)

        return columns

    def _write_edge_csv(self, filepath: Path, edges: list, rel_type: str):
        """Write an edge CSV file, injecting source label if available."""
        if not edges:
            return

        source_label = self.rel_source_map.get(rel_type)
        columns = ["start_id", "end_id"]
        if source_label:
            columns.append("source")

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for edge in edges:
                row = dict(edge)
                if source_label:
                    row["source"] = source_label
                writer.writerow(row)

    def _write_cypher_script(
        self,
        node_columns: dict[str, list[str]],
        rel_types: list[str],
        rel_endpoint_types: dict[str, list[tuple[str, str]]],
        edge_prop_columns: dict[str, list[str]],
    ) -> Path:
        """
        Write a Cypher LOAD CSV import script for all exported CSV files.

        MATCH clauses use node labels inferred from the id→type map so that
        Memgraph can use label+property indexes and avoid full scans, which
        prevents transaction timeouts on large edge files.

        For edge types with mixed endpoint labels (e.g. end nodes are both
        SideEffect and Disease), emits one LOAD CSV block per label pair.
        Each block uses a labeled MATCH so only matching rows produce edges;
        rows that don't match a given label are silently skipped.

        Returns:
            Path to the written ``import.cypher`` file.
        """
        filepath = self.output_dir / "import.cypher"
        lines = [
            "// Knowledge graph import script — generated by MemgraphExporter",
            f"// docker run -it -p 7687:7687 -p 3000:3000 -v /abs/path/to/data/output:{_MEMGRAPH_IMPORT_PREFIX} memgraph/memgraph-platform",
            "// obtain the docker container ID for the memgraph instance",
            "// docker ps",
            "// import the knowledge graph to memgraph. This prevents timeouts or silent import errors.",
            "// docker exec -i <container_id> mgconsole < /abs/path/to/data/output/import.cypher",
            "// Note: LOAD CSV parses all values as strings. Use ToInteger()/ToFloat() for numeric comparisons.",
            "",
        ]

        # Indexes — both label and label-property index per node type
        if node_columns:
            lines.append("// Indexes")
            for node_type in sorted(node_columns):
                lines.append(f"CREATE INDEX ON :{node_type};")
                lines.append(f"CREATE INDEX ON :{node_type}(id);")
            lines.append("")

        # Node LOAD CSV blocks
        for node_type, columns in node_columns.items():
            prop_map = ", ".join(f"{c}: row.{c}" for c in columns)
            lines += [
                f"// Nodes: {node_type}",
                f'LOAD CSV FROM "{_MEMGRAPH_IMPORT_PREFIX}/nodes_{node_type}.csv"'
                " WITH HEADER AS row",
                f"CREATE (:{node_type} {{{prop_map}}});",
                "",
            ]

        # Edge LOAD CSV blocks — use labeled MATCH to hit label+property indexes
        for rel_type in rel_types:
            endpoint_pairs = rel_endpoint_types.get(rel_type, [("", "")])
            extra_cols = edge_prop_columns.get(rel_type, [])
            if extra_cols:
                prop_map = ", ".join(f"{c}: row.{c}" for c in extra_cols)
                create = f"CREATE (a)-[:{rel_type} {{{prop_map}}}]->(b);"
            else:
                create = f"CREATE (a)-[:{rel_type}]->(b);"

            for i, (start_label, end_label) in enumerate(endpoint_pairs):
                start_match = f"MATCH (a:{start_label} {{id: row.start_id}})" if start_label else "MATCH (a {id: row.start_id})"
                end_match = f"MATCH (b:{end_label} {{id: row.end_id}})" if end_label else "MATCH (b {id: row.end_id})"
                suffix = f" ({start_label or '?'}->{end_label or '?'})" if len(endpoint_pairs) > 1 else ""
                lines += [
                    f"// Edges: {rel_type}{suffix}",
                    f'LOAD CSV FROM "{_MEMGRAPH_IMPORT_PREFIX}/edges_{rel_type}.csv"'
                    " WITH HEADER AS row",
                    start_match,
                    end_match,
                    create,
                    "",
                ]

        with open(filepath, "w") as f:
            f.write("\n".join(lines))

        return filepath
