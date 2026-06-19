"""
Data parsers for the knowledge graph.

This module contains parsers for various data sources used to populate the knowledge graph.
Each parser is responsible for downloading, parsing, and formatting data from
a specific source.
"""

from .base_parser import BaseParser
from .ncbigene_parser import NCBIGeneParser
from .drugbank_parser import DrugBankParser
from .disgenet_parser import DisGeNETParser
from .aopdb_parser import AOPDBParser
from .dorothea_parser import DoRothEAParser
from .collecttri_parser import CollectTRIParser
from .disease_ontology_parser import DiseaseOntologyParser
from .gene_ontology_parser import GeneOntologyParser
from .uberon_parser import UberonParser
from .mesh_parser import MeSHParser
from .drugcentral_parser import DrugCentralParser
from .bindingdb_parser import BindingDBParser
from .bgee_parser import BgeeParser
from .ctd_chemical_parser import CTDChemicalParser
from .medline_parser import MEDLINEParser
from .evolutionary_rate_covariation import EvolutionaryRateCovariationParser
from .reactome_parser import ReactomeParser
from .string_parser import StringParser
from .sider_parser import SIDERParser
from .hpo_parser import HPOParser
from .mondo_parser import MONDOParser

__all__ = [
    'BaseParser',
    'NCBIGeneParser',
    'DrugBankParser',
    'DisGeNETParser',
    'AOPDBParser',
    'DoRothEAParser',
    'CollectTRIParser',
    'DiseaseOntologyParser',
    'GeneOntologyParser',
    'UberonParser',
    'MeSHParser',
    'DrugCentralParser',
    'BindingDBParser',
    'BgeeParser',
    'CTDChemicalParser',
    'MEDLINEParser',
    'EvolutionaryRateCovariationParser',
    'ReactomeParser',
    'StringParser',
    'SIDERParser',
    'HPOParser',
    'MONDOParser',
]
