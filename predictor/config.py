"""Central configuration for the Ayurvedic predictive model.

All values are overridable via environment variables / .env so nothing is
hard-coded into the pipeline.
"""
import os
import dotenv

dotenv.load_dotenv()

# --- LLM providers -----------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Generator and verifier are deliberately separable so they run on DIFFERENT
# models (reduces correlated hallucination — a model that invents a claim tends
# to also "verify" it). Defaults:
#   - generator: gemini-2.5-flash (fast)
#   - verifier:  Claude if an ANTHROPIC_API_KEY is present (true cross-provider),
#                otherwise gemini-2.5-pro (a stronger, different Gemini model).
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gemini-2.5-flash")
_DEFAULT_VERIFIER = "claude-sonnet-4-6" if ANTHROPIC_API_KEY else "gemini-2.5-pro"
VERIFIER_MODEL = os.getenv("VERIFIER_MODEL", _DEFAULT_VERIFIER)

# --- Evidence loop -----------------------------------------------------------
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "12"))   # 10-15 per the design
ARTICLES_PER_QUERY = int(os.getenv("ARTICLES_PER_QUERY", "5"))
MIN_SUPPORTING_ARTICLES = int(os.getenv("MIN_SUPPORTING_ARTICLES", "1"))
MIN_EVIDENCE_LEVEL = int(os.getenv("MIN_EVIDENCE_LEVEL", "2"))  # see EVIDENCE_RANK

# Higher = stronger evidence. Used to grade and to decide sufficiency.
EVIDENCE_RANK = {
    "rct": 5,
    "clinical_trial": 5,
    "meta_analysis": 5,
    "cohort": 4,
    "case_control": 4,
    "case_report": 3,
    "review": 3,
    "animal": 2,
    "in_vitro": 2,
    "in_silico": 1,
    "unknown": 1,
}

# --- NCBI / PubMed ------------------------------------------------------------
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "research@herbenzo.example")
NCBI_API_KEY = os.getenv("NCBI_API_KEY")  # optional; raises rate limit to 10 rps
NCBI_TOOL = "ayurvedic-predictive-model"

# --- Safety ------------------------------------------------------------------
DISCLAIMER = (
    "Decision-support / hypothesis-generation tool for researchers. "
    "Not a diagnosis, prescription, or substitute for a licensed practitioner."
)


def _provider(model: str) -> str:
    return "anthropic" if model.startswith("claude") else "google"


def generator_provider() -> str:
    return _provider(GENERATOR_MODEL)


def verifier_provider() -> str:
    return _provider(VERIFIER_MODEL)


def is_cross_model() -> bool:
    """True when the verifier uses a different model than the generator."""
    return GENERATOR_MODEL != VERIFIER_MODEL


def is_cross_provider() -> bool:
    """True when generator and verifier are from different vendors (strongest)."""
    return generator_provider() != verifier_provider()


def verifier_usable() -> bool:
    """Whether the configured verifier model has a usable API key."""
    if verifier_provider() == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    return bool(GEMINI_API_KEY)


def llm_available() -> bool:
    return bool(GEMINI_API_KEY or ANTHROPIC_API_KEY)
