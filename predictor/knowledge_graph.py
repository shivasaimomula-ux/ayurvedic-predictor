"""Seed knowledge graph for candidate generation.

The model does NOT free-associate herbs (that is where hallucination enters).
It traverses this structured graph:

    condition -> mechanism/target -> phytochemical -> herb -> classical formula
              -> formulation type -> delivery system

Each candidate carries a list of *claims* that the evidence loop must then
verify against PubMed. This seed is small and illustrative; in production it is
populated from the Ayurvedic Pharmacopoeia of India + PubChem target links.
"""
from __future__ import annotations

from typing import List, Dict

# Each condition key has synonyms (for matching) and a list of candidate
# formulations. A claim = (subject, predicate) the verifier must substantiate.
SEED: Dict[str, Dict] = {
    "respiratory": {
        "synonyms": [
            "cough", "cold", "bronchitis", "respiratory", "throat", "phlegm", "kasa",
            "pneumonia", "flu", "influenza", "shortness of breath", "dyspnea",
            "wheeze", "congestion", "sinus",
        ],
        "ayurvedic_frame": "Kapha-Vata aggravation in Pranavaha srotas (respiratory channels)",
        "candidates": [
            {
                "formula": "Sitopaladi Churna",
                "type": "classical_polyherbal",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, taken with honey for mucosal contact",
                "herbs": ["Pippali (Piper longum)", "Ela (Elettaria cardamomum)",
                          "Tvak (Cinnamomum zeylanicum)", "Vamsharochana (Bambusa arundinacea)"],
                "phytochemicals": ["piperine", "cinnamaldehyde", "1,8-cineole"],
                "claims": [
                    "Piper longum (piperine) has anti-inflammatory activity relevant to respiratory tract",
                    "Cinnamomum zeylanicum supports respiratory comfort / has bronchodilatory or anti-inflammatory effect",
                ],
            },
        ],
    },
    "hyperacidity": {
        "synonyms": ["acidity", "hyperacidity", "heartburn", "gerd", "reflux", "amlapitta", "gastritis"],
        "ayurvedic_frame": "Pitta aggravation in Amashaya (gastric region)",
        "candidates": [
            {
                "formula": "Avipattikar Churna",
                "type": "classical_polyherbal",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, with water before meals",
                "herbs": ["Amalaki (Emblica officinalis)", "Haritaki (Terminalia chebula)",
                          "Shunthi (Zingiber officinale)", "Pippali (Piper longum)"],
                "phytochemicals": ["gallic acid", "chebulinic acid", "6-gingerol"],
                "claims": [
                    "Emblica officinalis reduces gastric acidity / has gastroprotective effect",
                    "Zingiber officinale has gastroprotective or anti-ulcer activity",
                ],
            },
        ],
    },
    "constipation": {
        "synonyms": ["constipation", "laxative", "bowel", "vibandha", "stool"],
        "ayurvedic_frame": "Vata aggravation in Purishavaha srotas (colon)",
        "candidates": [
            {
                "formula": "Triphala Churna",
                "type": "classical_polyherbal",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, at night with warm water",
                "herbs": ["Amalaki (Emblica officinalis)", "Haritaki (Terminalia chebula)",
                          "Bibhitaki (Terminalia bellirica)"],
                "phytochemicals": ["gallic acid", "chebulagic acid"],
                "claims": [
                    "Triphala (Terminalia chebula) has laxative / gut-motility promoting effect",
                ],
            },
        ],
    },
    "indigestion": {
        "synonyms": ["indigestion", "dyspepsia", "bloating", "flatulence", "agnimandya", "ajirna", "appetite"],
        "ayurvedic_frame": "Mandagni (low digestive fire)",
        "candidates": [
            {
                "formula": "Hingvastak Churna",
                "type": "classical_polyherbal",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, with the first bite of food / ghee",
                "herbs": ["Shunthi (Zingiber officinale)", "Maricha (Piper nigrum)",
                          "Pippali (Piper longum)", "Hingu (Ferula asafoetida)"],
                "phytochemicals": ["6-gingerol", "piperine"],
                "claims": [
                    "Zingiber officinale promotes gastric emptying / digestive motility",
                    "Ferula asafoetida has carminative / antispasmodic activity",
                ],
            },
        ],
    },
    "stress_anxiety": {
        "synonyms": ["stress", "anxiety", "insomnia", "sleep", "tension", "fatigue",
                     "manasika", "restless", "burnout", "cortisol"],
        "ayurvedic_frame": "Vata aggravation affecting Manas (mind)",
        "candidates": [
            {
                "formula": "Ashwagandha Churna",
                "type": "classical_single_herb",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, with warm milk at night",
                "herbs": ["Ashwagandha (Withania somnifera)"],
                "phytochemicals": ["withaferin A", "withanolides"],
                "claims": [
                    "Withania somnifera reduces stress and serum cortisol",
                    "Withania somnifera improves sleep quality",
                ],
            },
        ],
    },
    "joint_pain": {
        "synonyms": ["joint", "joints", "arthritis", "osteoarthritis", "knee pain",
                     "sandhivata", "stiffness", "inflammation pain"],
        "ayurvedic_frame": "Vata accumulation in Sandhi (joints)",
        "candidates": [
            {
                "formula": "Shallaki–Haridra combination",
                "type": "classical_polyherbal",
                "formulation": "Churna / tablet",
                "delivery": "Oral, after food",
                "herbs": ["Shallaki (Boswellia serrata)", "Haridra (Curcuma longa)"],
                "phytochemicals": ["boswellic acids (AKBA)", "curcumin"],
                "claims": [
                    "Boswellia serrata reduces osteoarthritis pain and improves joint function",
                    "Curcuma longa reduces pain and inflammation in osteoarthritis",
                ],
            },
        ],
    },
    "blood_sugar": {
        "synonyms": ["diabetes", "blood sugar", "glucose", "glycemic", "prameha",
                     "diabetic", "hyperglycemia", "insulin"],
        "ayurvedic_frame": "Kapha–Pitta imbalance (Prameha)",
        "candidates": [
            {
                "formula": "Nishamalaki Churna",
                "type": "classical_polyherbal",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, before meals with water",
                "herbs": ["Haridra (Curcuma longa)", "Amalaki (Emblica officinalis)",
                          "Meshashringi (Gymnema sylvestre)"],
                "phytochemicals": ["curcumin", "gymnemic acids"],
                "claims": [
                    "Gymnema sylvestre lowers blood glucose / has antidiabetic effect",
                    "Curcuma longa improves glycemic control",
                ],
            },
        ],
    },
    "immunity": {
        "synonyms": ["immunity", "immune", "debility", "weakness", "recurrent infection",
                     "vyadhikshamatva", "low immunity", "convalescence"],
        "ayurvedic_frame": "Depletion of Ojas (vital reserve)",
        "candidates": [
            {
                "formula": "Guduchi Churna",
                "type": "classical_single_herb",
                "formulation": "Churna / Satva",
                "delivery": "Oral, with warm water",
                "herbs": ["Guduchi (Tinospora cordifolia)"],
                "phytochemicals": ["tinosporaside", "polysaccharides"],
                "claims": [
                    "Tinospora cordifolia has immunomodulatory activity",
                ],
            },
        ],
    },
    "cognition": {
        "synonyms": ["memory", "cognition", "cognitive", "focus", "concentration",
                     "medhya", "brain", "learning", "mental clarity"],
        "ayurvedic_frame": "Imbalance affecting Medha / Buddhi (intellect)",
        "candidates": [
            {
                "formula": "Brahmi Churna",
                "type": "classical_single_herb",
                "formulation": "Churna (fine powder)",
                "delivery": "Oral, with ghee or warm milk",
                "herbs": ["Brahmi (Bacopa monnieri)"],
                "phytochemicals": ["bacosides"],
                "claims": [
                    "Bacopa monnieri improves cognitive performance and memory",
                ],
            },
        ],
    },
    "liver": {
        "synonyms": ["liver", "hepatic", "jaundice", "kamala", "fatty liver", "yakrit",
                     "hepatoprotective", "hepatitis"],
        "ayurvedic_frame": "Pitta aggravation in Yakrit (liver)",
        "candidates": [
            {
                "formula": "Bhumyamalaki Churna",
                "type": "classical_single_herb",
                "formulation": "Churna / Swarasa",
                "delivery": "Oral, on an empty stomach",
                "herbs": ["Bhumyamalaki (Phyllanthus niruri)"],
                "phytochemicals": ["phyllanthin", "hypophyllanthin"],
                "claims": [
                    "Phyllanthus niruri has hepatoprotective activity",
                ],
            },
        ],
    },
}


def _norm(text: str) -> str:
    return "".join(c if c.isalnum() else " " for c in text.lower())


def match_condition(query: str) -> str | None:
    """Map a free-text symptom/problem to a seeded condition key, or None."""
    q = _norm(query)
    best, best_hits = None, 0
    for key, node in SEED.items():
        hits = sum(1 for syn in node["synonyms"] if syn in q)
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def generate_candidates(query: str) -> Dict:
    """Return matched condition node + candidate formulations (or empty)."""
    key = match_condition(query)
    if key is None:
        return {"condition_key": None, "ayurvedic_frame": None, "candidates": []}
    node = SEED[key]
    return {
        "condition_key": key,
        "ayurvedic_frame": node["ayurvedic_frame"],
        "candidates": node["candidates"],
    }
