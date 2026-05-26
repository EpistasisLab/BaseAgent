"""
Ontology Populator using ista

This module provides a unified interface for populating an OWL ontology
using ista (Instance Store for Tabular Annotations).

ista converts tabular data (TSV/CSV files) and database records
into RDF format that populates the ontology.
"""

import csv as csv_mod
import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import owlready2

try:
    from ista import FlatFileDatabaseParser, MySQLDatabaseParser
except ImportError as e:
    logging.error(f"Failed to import ista: {e}")
    logging.error("Please install ista v0.1.1 @ https://github.com/RomanoLab/ista")
    raise

logger = logging.getLogger(__name__)


class OntologyPopulator:
    """
    Unified ontology populator using ista.

    Populates an OWL ontology from tabular data sources using ista's
    FlatFileDatabaseParser and MySQLDatabaseParser. Configuration is
    loaded from config/ontology_mappings.yaml.
    """

    def __init__(self, ontology_path: str, data_dir: str,
                 mysql_config: Optional[Dict[str, str]] = None,
                 ontology_mappings: Optional[Dict[str, Any]] = None):
        """
        Initialize the ontology populator.

        Args:
            ontology_path: Path to the base OWL ontology RDF file.
            data_dir: Directory containing processed data files (TSVs).
            mysql_config: MySQL connection config for database sources (optional).
            ontology_mappings: Ontology mapping configs dict. If None, loads
                               from config/ontology_mappings.yaml.
        """
        self.ontology_path = Path(ontology_path)
        self.data_dir = Path(data_dir)
        self.mysql_config = mysql_config
        self.ontology = None
        self._pending_edge_props: dict[str, dict] = {}
        if ontology_mappings is None:
            raise ValueError("ontology_mappings must be provided. Load it with load_config() from main.py.")
        self.ontology_mappings = ontology_mappings

        if not self.ontology_path.exists():
            raise FileNotFoundError(f"Ontology file not found: {self.ontology_path}")
        if not self.data_dir.exists():
            logger.warning(f"Data directory not found: {self.data_dir}. Creating it.")
            self.data_dir.mkdir(parents=True, exist_ok=True)

        self._load_ontology()

    def _load_ontology(self):
        """Load the ontology using owlready2."""
        try:
            ontology_uri = f"file://{self.ontology_path.absolute()}"
            logger.info(f"Loading ontology from: {ontology_uri}")
            self.ontology = owlready2.get_ontology(ontology_uri).load()
            logger.info(f"Successfully loaded ontology: {self.ontology.base_iri}")
        except Exception as e:
            logger.error(f"Failed to load ontology: {e}")
            raise

    # ------------------------------------------------------------------
    # Parser creation
    # ------------------------------------------------------------------

    def get_parser(self, source_name: str, parser_type: str = "flat") -> Union[FlatFileDatabaseParser, MySQLDatabaseParser]:
        """
        Create an ista parser for a data source.

        Args:
            source_name: Name of the data source (used as subdirectory).
            parser_type: "flat" for file-based, "mysql" for database.

        Returns:
            ista parser instance.
        """
        if parser_type == "flat":
            return FlatFileDatabaseParser(source_name, self.ontology, str(self.data_dir))
        elif parser_type == "mysql":
            if not self.mysql_config:
                raise ValueError("MySQL config required for parser type 'mysql'")
            return MySQLDatabaseParser(source_name, self.ontology, self.mysql_config)
        else:
            raise ValueError(f"Unknown parser type: {parser_type}")

    # ------------------------------------------------------------------
    # Node and relationship population
    # ------------------------------------------------------------------

    def populate_nodes(self, source_name: str, node_type: str,
                       source_filename: Optional[str] = None,
                       source_table: Optional[str] = None,
                       fmt: str = "tsv",
                       parse_config: Dict[str, Any] = None,
                       merge: bool = False, skip: bool = False,
                       parser_type: str = "flat") -> bool:
        """
        Populate nodes in the ontology from a data source.

        Args:
            source_name: Data source name.
            node_type: Ontology class name (e.g., "Gene", "Drug").
            source_filename: Filename for flat file sources.
            source_table: Table name for MySQL sources.
            fmt: File format ("tsv", "csv", etc.).
            parse_config: ista parse configuration dict.
            merge: Whether to merge with existing individuals.
            skip: Whether to skip this source.
            parser_type: "flat" or "mysql".

        Returns:
            True if successful, False otherwise.
        """
        if skip:
            logger.info(f"Skipping node population for {source_name}.{node_type}")
            return True

        try:
            parser = self.get_parser(source_name, parser_type)

            if parser_type == "flat":
                parser.parse_node_type(
                    node_type=node_type,
                    source_filename=source_filename,
                    fmt=fmt,
                    parse_config=parse_config,
                    merge=merge,
                    skip=skip,
                )
            else:
                if not source_table:
                    raise ValueError("source_table required for MySQL parser")
                parser.parse_node_type(
                    node_type=node_type,
                    source_table=source_table,
                    parse_config=parse_config,
                    merge=merge,
                    skip=skip,
                )

            logger.info(f"Successfully populated nodes: {source_name}.{node_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to populate nodes for {source_name}.{node_type}: {e}")
            return False

    def populate_relationships(self, source_name: str,
                               relationship_type,
                               source_filename: Optional[str] = None,
                               source_table: Optional[str] = None,
                               fmt: str = "tsv",
                               parse_config: Dict[str, Any] = None,
                               inverse_relationship_type=None,
                               merge: bool = False, skip: bool = False,
                               parser_type: str = "flat") -> bool:
        """
        Populate relationships in the ontology from a data source.

        Args:
            source_name: Data source name.
            relationship_type: Ontology object property (resolved).
            source_filename: Filename for flat file sources.
            source_table: Table name for MySQL sources.
            fmt: File format.
            parse_config: ista parse configuration dict.
            inverse_relationship_type: Inverse relationship (optional).
            merge: Whether to merge with existing relationships.
            skip: Whether to skip this source.
            parser_type: "flat" or "mysql".

        Returns:
            True if successful, False otherwise.
        """
        if skip:
            logger.info(f"Skipping relationship population for {source_name}.{relationship_type}")
            return True

        try:
            parser = self.get_parser(source_name, parser_type)

            if parser_type == "flat":
                parser.parse_relationship_type(
                    relationship_type=relationship_type,
                    source_filename=source_filename,
                    fmt=fmt,
                    parse_config=parse_config,
                    inverse_relationship_type=inverse_relationship_type,
                    merge=merge,
                    skip=skip,
                )
                if parse_config and source_filename:
                    rel_type_name = (relationship_type if isinstance(relationship_type, str)
                                     else relationship_type.name)
                    self._collect_edge_props(
                        rel_type_name=rel_type_name,
                        source_name=source_name,
                        source_filename=source_filename,
                        fmt=fmt,
                        parse_config=parse_config,
                    )
            else:
                if not source_table:
                    raise ValueError("source_table required for MySQL parser")
                parser.parse_relationship_type(
                    relationship_type=relationship_type,
                    source_table=source_table,
                    parse_config=parse_config,
                    inverse_relationship_type=inverse_relationship_type,
                    merge=merge,
                    skip=skip,
                )

            logger.info(f"Successfully populated relationships: {source_name}.{relationship_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to populate relationships for {source_name}.{relationship_type}: {e}")
            return False

    def _collect_edge_props(
        self,
        rel_type_name: str,
        source_name: str,
        source_filename: str,
        fmt: str,
        parse_config: Dict[str, Any],
    ):
        """
        Re-read the source file, resolve IDs via ontology search, and store
        edge property rows in memory. Written to disk by save_ontology().

        All columns except subject_column_name and object_column_name are
        captured as edge properties.
        """
        source_path = self.data_dir / source_name / source_filename
        if not source_path.exists():
            logger.warning(f"Source file not found for edge props: {source_path}")
            return

        sub_match_prop = parse_config["subject_match_property"].name
        obj_match_prop = parse_config["object_match_property"].name
        sub_col = parse_config["subject_column_name"]
        obj_col = parse_config["object_column_name"]
        delimiter = "\t" if fmt == "tsv" else ","

        rows = []
        with open(source_path, newline="") as f:
            reader = csv_mod.DictReader(f, delimiter=delimiter)
            edge_property_columns = [c for c in reader.fieldnames if c not in (sub_col, obj_col)]
            for row in reader:
                subjects = self.ontology.search(**{sub_match_prop: row[sub_col]})
                objects = self.ontology.search(**{obj_match_prop: row[obj_col]})
                if len(subjects) > 1 or len(objects) > 1:
                    logger.warning(
                        f"Ambiguous ID in {source_filename}: "
                        f"{row[sub_col]!r} matched {len(subjects)} subjects, "
                        f"{row[obj_col]!r} matched {len(objects)} objects — skipping row"
                    )
                    continue
                for sm in subjects:
                    for om in objects:
                        record = {"start_id": sm.name, "end_id": om.name}
                        for col in edge_property_columns:
                            record[col] = row.get(col, "")
                        rows.append(record)

        if rows:
            existing = self._pending_edge_props.setdefault(
                rel_type_name, {"rows": [], "columns": edge_property_columns}
            )
            existing["rows"].extend(rows)
            logger.info(f"  Collected {len(rows)} edge props for {rel_type_name}")

    # ------------------------------------------------------------------
    # Property resolution
    # ------------------------------------------------------------------

    def _resolve_property(self, name: str) -> Optional[type]:
        """
        Resolve a string property name to an ontology object.

        Args:
            name: Property name string (e.g., 'xrefMeSH', 'Gene', 'geneInPathway').

        Returns:
            The ontology object, or None if not found.
        """
        if name is None:
            return None
        prop = getattr(self.ontology, name, None)
        if prop is None:
            logger.warning(f"Property '{name}' not found in ontology")
        return prop

    def _resolve_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve string property names in a config to ontology objects.

        Args:
            config: Configuration dict with string property names.

        Returns:
            New config dict with resolved ontology references.
        """
        import copy
        resolved = copy.deepcopy(config)
        parse_config = resolved.get('parse_config', {})

        # Resolve data_property_map values
        if 'data_property_map' in parse_config:
            resolved_map = {}
            for col, prop_name in parse_config['data_property_map'].items():
                resolved_map[col] = self._resolve_property(prop_name)
            parse_config['data_property_map'] = resolved_map

        # Resolve merge_column property
        if 'merge_column' in parse_config:
            merge = parse_config['merge_column']
            if 'data_property' in merge:
                merge['data_property'] = self._resolve_property(merge['data_property'])

        # Resolve relationship parse_config properties
        for key in ['subject_node_type', 'object_node_type',
                    'subject_match_property', 'object_match_property']:
            if key in parse_config:
                parse_config[key] = self._resolve_property(parse_config[key])

        # Resolve top-level relationship type properties
        if 'relationship_type' in resolved:
            resolved['relationship_type'] = self._resolve_property(resolved['relationship_type'])
        if 'inverse_relationship_type' in resolved:
            resolved['inverse_relationship_type'] = self._resolve_property(resolved['inverse_relationship_type'])

        return resolved

    # ------------------------------------------------------------------
    # Config-driven population
    # ------------------------------------------------------------------

    def validate_config(self, config_key: str, config: Dict[str, Any]) -> List[str]:
        """
        Pre-flight validation of a config entry.

        Checks that referenced ontology types and properties exist, and that
        the source file is available.

        Args:
            config_key: The config key (e.g., "aopdb.drugs").
            config: The config dict for this key.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []
        parse_config = config.get("parse_config", {})

        # Check node_type or relationship_type exists in ontology
        if config.get("data_type") == "node":
            node_type = config.get("node_type")
            if node_type and self._resolve_property(node_type) is None:
                errors.append(f"{config_key}: node_type '{node_type}' not found in ontology")

        elif config.get("data_type") == "relationship":
            rel_type = config.get("relationship_type")
            if rel_type and self._resolve_property(rel_type) is None:
                errors.append(f"{config_key}: relationship_type '{rel_type}' not found in ontology")

            for role in ["subject", "object"]:
                nt = parse_config.get(f"{role}_node_type")
                if nt and self._resolve_property(nt) is None:
                    errors.append(f"{config_key}: {role}_node_type '{nt}' not found in ontology")
                mp = parse_config.get(f"{role}_match_property")
                if mp and self._resolve_property(mp) is None:
                    errors.append(f"{config_key}: {role}_match_property '{mp}' not found in ontology")

        # Check data_property_map values
        for col, prop_name in parse_config.get("data_property_map", {}).items():
            if self._resolve_property(prop_name) is None:
                errors.append(f"{config_key}: data_property '{prop_name}' (column '{col}') not found in ontology")

        # Check source file exists
        source_filename = config.get("source_filename")
        if source_filename:
            source_name = config_key.split(".")[0]
            source_path = self.data_dir / source_name / source_filename
            if not source_path.exists():
                errors.append(f"{config_key}: source file not found: {source_path}")

        return errors

    def get_config(self, config_key: str) -> Optional[Dict[str, Any]]:
        """
        Get a single resolved config by key from ontology mappings.

        Args:
            config_key: Key in format "{source_name}.{data_name}".

        Returns:
            Resolved config dict, or None if not found.
        """
        if config_key not in self.ontology_mappings:
            return None
        return self._resolve_config(self.ontology_mappings[config_key])

    def populate_from_config(self, config_key: str,
                             fmt: str = "tsv",
                             parser_type: str = "flat") -> Tuple[Optional[bool], Optional[str]]:
        """
        Populate ontology using a config key from ontology mappings.

        Args:
            config_key: Key in format "{source_name}.{data_name}".
            fmt: File format ("tsv", "csv", etc.).
            parser_type: Parser type ("flat" or "mysql").

        Returns:
            Tuple of (success, data_type):
            - (None, None) if no config found
            - (True/False, 'node'/'relationship') based on result
        """
        config = self.get_config(config_key)

        if config is None:
            logger.warning(f"No config found for {config_key}")
            return (None, None)

        data_type = config.get('data_type')
        source_name = config_key.split('.')[0]
        source_filename = config.get('source_filename')

        if not source_filename:
            logger.error(f"No source_filename in config for {config_key}")
            return (False, None)

        if data_type == 'node':
            success = self.populate_nodes(
                source_name=source_name,
                node_type=config.get('node_type'),
                source_filename=source_filename,
                fmt=fmt,
                parse_config=config.get('parse_config'),
                merge=config.get('merge', False),
                skip=config.get('skip', False),
                parser_type=parser_type,
            )
            return (success, 'node')
        elif data_type == 'relationship':
            success = self.populate_relationships(
                source_name=source_name,
                relationship_type=config.get('relationship_type'),
                source_filename=source_filename,
                fmt=fmt,
                parse_config=config.get('parse_config'),
                inverse_relationship_type=config.get('inverse_relationship_type'),
                merge=config.get('merge', False),
                skip=config.get('skip', False),
                parser_type=parser_type,
            )
            return (success, 'relationship')
        else:
            logger.error(f"Unknown data_type '{data_type}' for {config_key}")
            return (False, None)

    # ------------------------------------------------------------------
    # Persistence and statistics
    # ------------------------------------------------------------------

    def save_ontology(self, output_path: Optional[str] = None) -> str:
        """
        Save the populated ontology to an RDF file, then write any pending
        edge property sidecar CSVs to the same directory.

        Args:
            output_path: Path to save. If None, overwrites the original.

        Returns:
            Path to the saved ontology file.
        """
        if output_path is None:
            output_path = str(self.ontology_path)

        logger.info(f"Saving ontology to: {output_path}")
        self.ontology.save(file=output_path, format="rdfxml")
        logger.info(f"Successfully saved ontology to: {output_path}")

        output_dir = Path(output_path).parent
        for rel_type_name, data in self._pending_edge_props.items():
            sidecar_path = output_dir / f"edge_props_{rel_type_name}.csv"
            fieldnames = ["start_id", "end_id"] + data["columns"]
            with open(sidecar_path, "w", newline="") as f:
                writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data["rows"])
            logger.info(f"  Wrote edge props: {sidecar_path.name}")

        return output_path

    def get_ontology_stats(self) -> Dict[str, int]:
        """Get counts of classes, individuals, and properties."""
        return {
            "classes": len(list(self.ontology.classes())),
            "individuals": len(list(self.ontology.individuals())),
            "object_properties": len(list(self.ontology.object_properties())),
            "data_properties": len(list(self.ontology.data_properties())),
        }

    def print_stats(self):
        """Print ontology statistics."""
        stats = self.get_ontology_stats()
        logger.info("Ontology Statistics:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
