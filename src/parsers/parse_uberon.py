#!/usr/bin/env python3
"""
Parse Uberon OBO — extract CVD-relevant anatomical terms.
Outputs:
  ./data/processed/uberon/uberon_terms.tsv
"""

import csv, os, re

OUT_DIR = "./data/processed/uberon"
os.makedirs(OUT_DIR, exist_ok=True)

OBO_PATH = "./data/processed/uberon/uberon.obo"

# CVD-relevant keywords for filtering
CVD_KEYWORDS = [
    'heart', 'cardiac', 'cardio', 'myocardium', 'myocardial',
    'ventricle', 'ventricular', 'atrium', 'atrial',
    'aorta', 'aortic', 'coronary', 'pericardium', 'pericardial',
    'valve', 'valvular', 'endocardium', 'epicardium',
    'artery', 'arterial', 'arteries', 'aortic',
    'vein', 'venous', 'vascular',
    'blood vessel', 'vasculature',
    'pulmonary', 'mitral', 'tricuspid', 'semilunar',
    'sinoatrial', 'atrioventricular', 'septum', 'septal',
    'capillary', 'endothelium', 'endothelial',
    'carotid', 'femoral artery', 'renal artery',
    'inferior vena cava', 'superior vena cava',
    'circulatory', 'circulation',
    'left ventricle', 'right ventricle',
    'left atrium', 'right atrium',
    'interventricular', 'interatrial',
    'chordae tendineae', 'papillary muscle',
    'great vessel', 'pulmonary trunk',
    'ductus arteriosus', 'foramen ovale',
    'bundle of his', 'purkinje', 'conduction',
    'thoracic aorta', 'abdominal aorta',
    'iliac artery', 'subclavian', 'brachiocephalic',
    'mesenteric artery', 'hepatic artery',
    'lymph', 'lymphatic',
    'adipose', 'liver', 'kidney', 'lung', 'skeletal muscle',
    'smooth muscle', 'striated muscle',
    'platelet', 'erythrocyte', 'leukocyte', 'blood',
    'bone marrow', 'spleen', 'thymus',
    'plasma', 'serum',
]

def is_cvd_relevant(name, synonyms, definition=''):
    text = (name + ' ' + ' '.join(synonyms) + ' ' + definition).lower()
    for kw in CVD_KEYWORDS:
        if kw in text:
            return True
    return False

print("Parsing uberon.obo ...")
terms = []
cur = {}
in_term = False

with open(OBO_PATH, encoding='utf-8') as fh:
    for line in fh:
        line = line.rstrip('\n')
        if line == '[Term]':
            if in_term and cur.get('id','').startswith('UBERON:'):
                if not cur.get('obsolete', False):
                    terms.append(cur)
            cur = {'synonyms': [], 'definition': ''}
            in_term = True
        elif line == '[Typedef]':
            if in_term and cur.get('id','').startswith('UBERON:'):
                if not cur.get('obsolete', False):
                    terms.append(cur)
            cur = {}
            in_term = False
        elif in_term:
            if line.startswith('id: '):
                cur['id'] = line[4:]
            elif line.startswith('name: '):
                cur['name'] = line[6:]
            elif line.startswith('def: '):
                # Extract text between first pair of quotes
                m = re.match(r'def: "([^"]*)"', line)
                if m:
                    cur['definition'] = m.group(1)
            elif line.startswith('synonym: '):
                m = re.match(r'synonym: "([^"]*)"', line)
                if m:
                    cur['synonyms'].append(m.group(1))
            elif line.startswith('is_obsolete: true'):
                cur['obsolete'] = True

# Last term
if in_term and cur.get('id','').startswith('UBERON:'):
    if not cur.get('obsolete', False):
        terms.append(cur)

print(f"  Total Uberon terms parsed: {len(terms)}")

# Filter to CVD-relevant terms
cvd_terms = [t for t in terms
             if is_cvd_relevant(t.get('name',''), t.get('synonyms',[]), t.get('definition',''))]
print(f"  CVD-relevant terms:        {len(cvd_terms)}")

# Write TSV
OUT_PATH = f"{OUT_DIR}/uberon_terms.tsv"
with open(OUT_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['xrefUberon','name','definition'])
    for t in cvd_terms:
        w.writerow([t['id'], t.get('name',''), t.get('definition','')])
print(f"\nWritten {len(cvd_terms)} CVD body-part terms -> {OUT_PATH}")

# Show sample
print("\nSample terms:")
for t in cvd_terms[:10]:
    print(f"  {t['id']}: {t.get('name','')}")
