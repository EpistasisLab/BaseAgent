"""Extend the AlzKB ontology with CardioKB-specific classes and properties."""
import owlready2
from pathlib import Path

onto_path = Path("template/data/ontology/ontology.rdf")
onto = owlready2.get_ontology(f"file://{onto_path.resolve()}").load()

print(f"Loaded ontology with {len(list(onto.classes()))} classes")

# --- Missing OWL Classes ---
missing_classes = [
    "ClinicalTrial", "DrugLabel", "Phenotype", "GeneFamily",
    "PharmacologicClass", "SideEffect",
]
with onto:
    for cls_name in missing_classes:
        if not getattr(onto, cls_name, None):
            new_cls = type(cls_name, (owlready2.Thing,), {"namespace": onto})
            print(f"  Added class: {cls_name}")
        else:
            print(f"  Class exists: {cls_name}")

# --- Missing Data Properties ---
missing_data_props = [
    "trialId", "phase", "status", "labelId", "url", "version",
    "geneOntologyId", "xrefHPO", "synonyms", "classId", "classCode",
    "familyId", "familyName", "variantId", "variantType",
    "clinicalSignificance", "reviewStatus", "genomeAssembly",
    "positionStart", "positionStop", "referenceAllele", "alternateAllele",
    "dbSnpId", "xrefDrugCentral", "xrefChembl", "xrefPubChemCID",
    "xrefStitch", "morScore", "confidence", "phenotype", "classification",
    "expressionScore", "pmid", "evidenceCode", "combinedScore", "score",
    "interactionType", "phenotypeName", "sourceOntology", "geneName",
]
with onto:
    for prop_name in missing_data_props:
        if not getattr(onto, prop_name, None):
            new_prop = type(prop_name, (owlready2.DataProperty,), {"namespace": onto})
            print(f"  Added data property: {prop_name}")
        else:
            print(f"  Data property exists: {prop_name}")

# --- Missing Object Properties (relationships) ---
missing_obj_props = [
    "drugBindsGene", "STUDIES_CONDITION", "TESTS_INTERVENTION",
    "AFFECTS_RESPONSE_TO", "AFFECTS_RESPONSE_TO_CLASS", "VARIANT_IN",
    "geneAssociatesWithPhenotype", "geneInFamily", "familyContainsGene",
    "hasVariant", "variantInGene", "associatedWithVariant",
    "variantAssociatedWithDisease", "compoundCausesSideEffect",
    "compoundUpregulatesGene", "compoundDownregulatesGene",
    "pharmacologicClassIncludesCompound", "compoundInPharmacologicClass",
    "diseasePresentsSymptom", "diseaseResemblesDisease", "diseaseIsSubtypeOf",
    "drugLabelAnnotatesGene", "drugLabelDescribesDrug",
    "drugPalliatesDisease", "geneExpressedInBodyPart",
]
with onto:
    for prop_name in missing_obj_props:
        if not getattr(onto, prop_name, None):
            new_prop = type(prop_name, (owlready2.ObjectProperty,), {"namespace": onto})
            print(f"  Added object property: {prop_name}")
        else:
            print(f"  Object property exists: {prop_name}")

onto.save(file=str(onto_path), format="rdfxml")
classes = list(onto.classes())
print(f"\nDone. Total classes: {len(classes)}")
