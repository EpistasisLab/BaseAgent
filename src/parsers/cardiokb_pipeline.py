#!/usr/bin/env python3
"""
CardioKB - Cardiovascular Disease Knowledge Graph
Complete build pipeline summary

Data Sources Loaded:
1.  Disease Ontology (DOID) - 764 Disease nodes, 687 diseaseIsSubtypeOf edges
2.  NCBI Gene - 64,231 Gene nodes, 64,231 geneInSpecies edges
3.  Gene Ontology - 38,559 BP/MF/CC nodes, 295,494 gene-GO edges
4.  Uberon - 14,970 BodyPart nodes
5.  HPO - 19,388 Phenotype nodes, 266,981 geneAssociatesWithPhenotype edges
6.  MeSH (NLM SPARQL) - 15,947 Symptom nodes
7.  DrugBank - 19,853 Drug nodes (open vocabulary)
8.  ClinVar - 221,645 Variant nodes, 654,426 variant edges
9.  Reactome - 2,836 Pathway nodes, 274,232 gene-pathway edges
10. OpenTargets - 291,069 geneAssociatesWithDisease edges
11. STRING - 229,000 geneInteractsWithGene edges (score >= 700)
12. CTD - 672,624 chemical-gene expression edges
13. SIDER - 4,251 SideEffect nodes, 140,677 compoundCausesSideEffect edges
14. DrugCentral - 2,359 PharmacologicClass nodes, 41,824 drug edges
15. BindingDB - 849,957 chemicalBindsGene edges
16. ClinicalTrials.gov - 2,677 ClinicalTrial nodes, 1,947 trial edges
17. DoRothEA (OmniPath) - 367 TF nodes, 15,082 TF-gene edges
18. HGNC Gene Families - 3,287 GeneFamily nodes, 68,042 gene-family edges
19. Bgee - 2,589,541 body part expression edges
20. Jensen TISSUES - 54,389 geneExpressedInBodyPart edges
21. ClinPGx/CPIC - 29 DrugLabel nodes, 1,683 pharmacogenomics edges
22. DrugAge - 1,326 AgeingProperty nodes, 1,832 associatedWithAging edges
23. AnAge - 4,645 Species nodes
24. PubTator - 17,261 diseaseAssociatesWithDisease edges
25. MEDLINE/Hetionet - 625 disease-symptom/anatomy edges
26. LINCS L1000 - 4,245,485 compound/gene regulation edges

TOTAL: 1,036,899 nodes | 10,800,305 edges
"""

# Connection details
MEMGRAPH_URI = "bolt://localhost:7688"
MEMGRAPH_AUTH = None

# CVD Terms for filtering
CVD_TERMS = [
    "heart failure", "coronary artery disease", "myocardial infarction",
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis", "hypertension",
    "stroke", "atherosclerosis", "cardiac arrest", "ventricular tachycardia",
    "pulmonary hypertension", "heart valve disease", "endocarditis", "pericarditis",
    "aortic aneurysm", "peripheral artery disease", "deep vein thrombosis",
    "pulmonary embolism", "congenital heart disease", "arrhythmia", "angina pectoris",
    "cardiovascular", "cardiac", "heart", "vascular", "arterial",
]
