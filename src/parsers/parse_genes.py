"""
CVD Gene Parser - NCBI Gene Info
Parses Homo_sapiens.gene_info.gz and filters to CVD-relevant genes
"""
import gzip
import pandas as pd
import os

# CVD seed gene symbols
CVD_SEED_GENES = {
    # Lipid metabolism / atherosclerosis
    "APOB","APOE","APOA1","APOA5","APOC3","LDLR","PCSK9","CETP","LPL","LIPC",
    "LCAT","ABCA1","ABCG5","ABCG8","NPC1L1","HMGCR","LDLRAP1","ANGPTL3",
    # Renin-angiotensin / hypertension
    "ACE","ACE2","AGT","AGTR1","AGTR2","REN","CYP11B2","ADD1","GNB3","NOS3",
    "EDN1","EDNRA","EDNRB","NPR1","NPPA","NPPB","GUCY1A1","GUCY1B1",
    # Cardiomyopathy / structural
    "MYH7","MYH6","MYBPC3","TNNT2","TNNI3","TPM1","ACTC1","MYL2","MYL3",
    "TTN","LMNA","SCN5A","PLN","RYR2","CASQ2","DSP","PKP2","DSG2","DSC2",
    "JUP","TMEM43","FLNC","VCL","NEXN","ACTN2",
    # Ion channels / arrhythmia
    "KCNQ1","KCNH2","KCNE1","KCNE2","KCNJ2","KCNJ11","SCN5A","SCN1B","SCN2B",
    "SCN3B","SCN4B","HCN4","CACNA1C","CACNB2","CACNA2D1","KCND3","KCNA5",
    "GJA5","GJA1","ANK2","SNTA1","CAV3","RANGRF",
    # Heart failure / signaling
    "ADRB1","ADRB2","GRK5","ADRA2C","GNAQ","GNA11","PDE5A","PDE3A",
    "CAMK2D","CALM1","CALM2","CALM3","CALR","ATP2A2",
    # Coagulation / thrombosis
    "F2","F5","F7","F8","F9","F10","F11","F13A1","VWF","PROS1","PROC",
    "THBD","TFPI","SERPINC1","SERPINE1","PLAT","PLAU","PLG",
    "ITGA2B","ITGB3","GP1BA","GP1BB","GP9","P2RY12",
    # Inflammation / cytokines
    "TNF","IL6","IL1B","IL18","CRP","PTGS2","ALOX5","LTA","IL10","TGFB1",
    "IFNG","CCL2","CXCL8","ICAM1","VCAM1","SELE","SELP","MMP9",
    "MMP3","MMP13","TIMP1","TIMP2",
    # Congenital heart disease
    "NKX2-5","GATA4","TBX5","TBX20","HAND1","HAND2","MEF2C","NOTCH1",
    "NOTCH2","JAG1","ELN","FBN1","FBN2","MYH11","SMAD3","TGFBR1","TGFBR2",
    "ACVRL1","ENG","BMPR2","KCNK3","CAV1",
    # Aortic / vascular
    "COL3A1","ACTA2","SKI","EFEMP2","FLNA","SLC2A10",
    # Stroke / cerebrovascular
    "NOTCH3","COL4A1","COL4A2","HTRA1","TREX1","CECR1","ADA2",
    # Metabolic / diabetes-CVD overlap
    "INS","INSR","IRS1","IRS2","PIK3CA","AKT1","FOXO1","PPARG","PPARA",
    "ADIPOQ","LEP","LEPR","RETN","FTO","TCF7L2","ABCC8",
    # Angiogenesis / vascular
    "VEGFA","VEGFB","VEGFC","KDR","FLT1","ANGPT1","ANGPT2","TIE1","TEK",
    "PDGFRA","PDGFRB","FGFR1","IGF1","IGF1R",
    # Oxidative stress
    "HIF1A","EPAS1","VHL","SOD1","SOD2","CAT","GPX1","HMOX1","HMOX2",
    # Signaling pathways
    "SIRT1","SIRT3","PRKAA1","PRKAA2","MTOR","TSC1","TSC2",
    "TP53","BCL2","BAX","CASP3",
    "PTPN11","RAF1","HRAS","KRAS","BRAF","MAP2K1","MAPK1","MAPK3",
    # Noonan / RASopathy (CVD)
    "SOS1","SHOC2","CBL","SPRED1","NF1",
    # Transcription factors (CHD)
    "GATA5","GATA6","TBX1","TBX2","TBX3","TBX18","CITED2","FOXH1",
    "ISL1","SALL4","ZIC3","CRELD1",
    # Connective tissue / aortic
    "TNXB","COL1A1","COL1A2","COL5A1","COL5A2","PLOD1","ATP7A","ATP7B",
    # Additional lipid
    "ANGPTL4","ANGPTL8","APOC2","APOC4","CLU","PON1","PON2","PON3","MPO",
    # Adrenergic / autonomic
    "COMT","MAOA","MAOB","DBH","TH","DDC","PNMT",
    "CHRM2","ADRB3","ADRA1A","ADRA1B","ADRA2A","ADRA2B",
    # Prostaglandins
    "PTGIS","TBXA2R","PTGER3","PTGER4","LTA4H","LTC4S","ALOX5AP","PTGES",
    # Calcium handling
    "SLC8A1","TRPM4","TRPM7","RYR1","RYR3","ITPR1","ITPR2","ITPR3",
    # Gap junctions
    "GJB2","GJB6",
    # Nuclear envelope (DCM)
    "EMD","SYNE1","SYNE2","LMNB1",
    # Pulmonary arterial hypertension
    "SMAD9","GDF2","KCNA5","ABCC8",
    # Misc CVD
    "KCNIP2","DPP6","PITX2","PRRX1",
    "FGF23","KLOTHO","GPC1","GPC3",
    "PCSK6","FURIN","ADAM10","ADAM17",
    "SERCA2","CASQ1","CASQ2","CALM1",
    "MYBPC1","MYBPC2","MYL4","MYL6","MYL7",
    "TNNC1","TNNC2","TNNI1","TNNI2",
    "LMOD2","NEBL","OBSCN","XIRP2",
    "ALPK3","ANKRD1","CSRP3","LDB3","TCAP",
    "ABCC9","KCNJ8","HCN1","HCN2","HCN3",
    "CACNA1D","CACNA1G","CACNA1H","CACNA1I",
    "SCN10A","SCN11A","SCN8A","SCN9A",
    "KCNJ3","KCNJ5","KCNJ6","KCNJ9",
    "KCNK1","KCNK2","KCNK3","KCNK6","KCNK9",
    "RRAD","GJD3","AKAP9","YWHAE",
    "NPPA","NPPB","NPPC","NPR2","NPR3",
    "ET1","ECE1","ECE2",
    "PTPN11","PTPN22","PTPN6",
    "JAK2","STAT3","STAT1","NF-KB1","NFKB1","RELA",
    "SMAD2","SMAD4","SMAD6","SMAD7",
    "WNT3A","WNT5A","FZD4","LRP5","LRP6",
    "NOTCH4","DLL4","HEY1","HEY2","HEYL",
    "SOX17","SOX18","FOXC1","FOXC2","FOXF1",
    "KLF2","KLF4","KLF15","SP1","EGR1",
    "TWIST1","TWIST2","SNAI1","SNAI2","ZEB1","ZEB2",
    "MIR21","MIR1","MIR133A1","MIR208A","MIR499A",
    "KCNQ4","KCNQ5","KCNB1","KCNB2","KCNC1",
    "LRRK2","PINK1","PARK2","PARK7",
}

def parse_gene_info(gene_info_path, seed_genes):
    print(f"Parsing {gene_info_path}...")
    df = pd.read_csv(gene_info_path, sep="\t", compression="gzip", dtype=str, low_memory=False)
    df.columns = [c.lstrip("#") for c in df.columns]
    
    print(f"  Total rows: {len(df)}")
    
    # Filter human genes
    df = df[df["tax_id"] == "9606"].copy()
    print(f"  Human genes: {len(df)}")
    
    # Build geneName
    df["geneName"] = df["Full_name_from_nomenclature_authority"].where(
        df["Full_name_from_nomenclature_authority"] != "-",
        df["description"]
    )
    
    # Clean synonyms
    df["synonyms"] = df["Synonyms"].where(df["Synonyms"] != "-", "")
    
    # Clean chromosome
    df["chromosome"] = df["chromosome"].where(df["chromosome"] != "-", "")
    
    # Filter to seed CVD genes
    seed_upper = {s.upper() for s in seed_genes}
    cvd_mask = df["Symbol"].str.upper().isin(seed_upper)
    df_cvd = df[cvd_mask].copy()
    print(f"  CVD seed gene matches: {len(df_cvd)}")
    
    # Add from existing cvd_genes.tsv
    existing_cvd = pd.read_csv("./data/processed/ncbi_gene/cvd_genes.tsv", sep="\t")
    existing_symbols = set(existing_cvd["geneSymbol"].str.upper())
    
    extra_mask = df["Symbol"].str.upper().isin(existing_symbols - seed_upper)
    df_extra = df[extra_mask].copy()
    print(f"  Additional from existing cvd_genes.tsv: {len(df_extra)}")
    
    df_combined = pd.concat([df_cvd, df_extra], ignore_index=True).drop_duplicates("Symbol")
    print(f"  Combined unique CVD genes: {len(df_combined)}")
    
    return df_combined

def build_gene_tsv(df):
    result = pd.DataFrame({
        "ncbiGeneId":  df["GeneID"],
        "geneSymbol":  df["Symbol"],
        "geneName":    df["geneName"],
        "chromosome":  df["chromosome"],
        "geneType":    df["type_of_gene"],
        "synonyms":    df["synonyms"].fillna(""),
        "source":      "NCBI Gene",
        "organism":    "Homo sapiens",
        "taxonId":     "9606",
    })
    return result

if __name__ == "__main__":
    gene_info_path = "./data/processed/ncbi_gene/Homo_sapiens.gene_info.gz"
    df_raw = parse_gene_info(gene_info_path, CVD_SEED_GENES)
    df_final = build_gene_tsv(df_raw)
    
    out_path = "./data/processed/ncbi_gene/cvd_genes_final.tsv"
    df_final.to_csv(out_path, sep="\t", index=False)
    print(f"\nSaved {len(df_final)} gene records to {out_path}")
    print(df_final.head(5).to_string())
    print("\nGene type distribution:")
    print(df_final["geneType"].value_counts().head(10))
