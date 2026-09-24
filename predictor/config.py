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
# NVIDIA NIM (OpenAI-compatible). Prefer NVIDIA_API_KEY; NIM_API_KEY is an alias.
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
NIM_BASE_URL = (
    os.getenv("NIM_BASE_URL") or "https://integrate.api.nvidia.com/v1"
).rstrip("/")
# Stage A (approved 2026-09-23): verifier = Nemotron 3 Ultra (cross-provider vs Gemini).
# Super is fallback only when Ultra is unavailable on the key.
NIM_MODEL = os.getenv(
    "NIM_MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1"
)
NIM_MODEL_FALLBACK = os.getenv(
    "NIM_MODEL_FALLBACK", "nvidia/llama-3.3-nemotron-super-49b-v1"
)

# Stage A volume path: NVIDIA NIM → Gemini. Claude is OFF by default for this
# recommend-UI version (cross-provider = Gemini generate + NIM verify).
VERIFIER_COST_ORDER = ("nim", "gemini")

# Generator and verifier are different providers (anti-hallucination):
#   - generator: Gemini Flash 3.5 / 3.8 (falls back to 2.5 Flash if needed)
#   - verifier:  Nemotron 3 Ultra on NIM
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gemini-3.5-flash")
# Prefer Flash 3.x; llm.complete() walks this list on Gemini 404/not-found.
GENERATOR_MODEL_FALLBACKS = tuple(
    m.strip()
    for m in os.getenv(
        "GENERATOR_MODEL_FALLBACKS",
        "gemini-3.8-flash,gemini-3.5-flash,gemini-2.5-flash,gemini-2.0-flash",
    ).split(",")
    if m.strip()
)

_raw_verifier = os.getenv("VERIFIER_MODEL", NIM_MODEL)
# Claude must never be the volume verifier on Stage A.
if _raw_verifier.lower().startswith("claude"):
    VERIFIER_MODEL = NIM_MODEL
else:
    VERIFIER_MODEL = _raw_verifier

# Claude escalate disabled unless explicitly opted in (A_CLAUDE_ESCALATE=1).
_claude_escalate = os.getenv("A_CLAUDE_ESCALATE", "0").strip().lower() in {
    "1", "true", "yes", "on",
}
if _claude_escalate:
    ESCALATE_MODEL = os.getenv("ESCALATE_MODEL", "claude-sonnet-4-6")
else:
    # Re-verify with Super / same NIM stack — never Claude for this version.
    ESCALATE_MODEL = os.getenv("ESCALATE_MODEL", NIM_MODEL_FALLBACK)

# Prefer blue adjudication service (:8011) when reachable; else local cascade.
ADJUDICATION_URL = (
    os.getenv("ADJUDICATION_URL") or "http://127.0.0.1:8011"
).rstrip("/")
ADJUDICATION_PREFERRED = os.getenv("ADJUDICATION_PREFERRED", "1").strip().lower() in {
    "1", "true", "yes", "on",
}
ADJUDICATION_TIMEOUT_S = float(os.getenv("ADJUDICATION_TIMEOUT_S", "8"))

# --- Evidence loop -----------------------------------------------------------
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "12"))   # 10-15 per the design
ARTICLES_PER_QUERY = int(os.getenv("ARTICLES_PER_QUERY", "5"))
MIN_SUPPORTING_ARTICLES = int(os.getenv("MIN_SUPPORTING_ARTICLES", "1"))
MIN_EVIDENCE_LEVEL = int(os.getenv("MIN_EVIDENCE_LEVEL", "2"))  # see EVIDENCE_RANK

# --- Async predict jobs (Task T18 / Finding #20) ------------------------------
# Wall-clock budget for a single job (default 9 min; under F's 600s handoff).
PREDICT_JOB_TIMEOUT_S = float(os.getenv("PREDICT_JOB_TIMEOUT_S", "540"))
PREDICT_MAX_CONCURRENT_JOBS = int(os.getenv("PREDICT_MAX_CONCURRENT_JOBS", "2"))
PREDICT_JOB_RETENTION_S = float(os.getenv("PREDICT_JOB_RETENTION_S", "3600"))

# Volume path is always live (no fixture/mock predict cache). Optional:
# skip curated KG so every query runs generator propose + PubMed verify.
# PubMed PMID disk cache remains OK for rate limits — it does not skip LLMs.
FORCE_AI_PROPOSE = os.getenv("A_FORCE_AI_PROPOSE", "0").strip().lower() in {
    "1", "true", "yes", "on",
}

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
# Shared with Stage B / adjudication (Task T16). Absolute path recommended.
PUBMED_CACHE_DIR = os.getenv("HERBENZO_PUBMED_CACHE_DIR") or None
_ttl_raw = os.getenv("HERBENZO_PUBMED_CACHE_TTL_S")
PUBMED_CACHE_TTL_S = int(_ttl_raw) if _ttl_raw not in (None, "") else None

# --- Safety ------------------------------------------------------------------
DISCLAIMER = (
    "Decision-support / hypothesis-generation tool for researchers. "
    "Not a diagnosis, prescription, or substitute for a licensed practitioner."
)

# --- A → C FormulationInput demo defaults (B Modernizer skipped) ------------
# Hand/env defaults for the thin adapter; not a full registry / CoA path.
FORMULATION_TARGET_MARKET = os.getenv("FORMULATION_TARGET_MARKET", "US")
# Indication / MeSH string for Stage C (may differ from regulatory lens).
FORMULATION_PRODUCT_CATEGORY = os.getenv(
    "FORMULATION_PRODUCT_CATEGORY", "dietary_supplement"
)
# Shared E regulatory lens (Task T8). Empty → resolve from PRODUCT_CATEGORY aliases.
FORMULATION_REGULATORY_CATEGORY = os.getenv(
    "FORMULATION_REGULATORY_CATEGORY", ""
).strip() or None
FORMULATION_DOSAGE_FORM = os.getenv("FORMULATION_DOSAGE_FORM", "")  # empty → derive
_serving = os.getenv("FORMULATION_SERVING_SIZE_G")
FORMULATION_SERVING_SIZE_G = float(_serving) if _serving else None

# A → B FormulationSpec: allow CoA/demo quantity_mg table when stated dose absent.
# Set FORMULATION_SPEC_ALLOW_DEMO_DOSES=0 to refuse unless stated dose is present.
FORMULATION_SPEC_ALLOW_DEMO_DOSES = os.getenv(
    "FORMULATION_SPEC_ALLOW_DEMO_DOSES", "1"
).strip().lower() in {"1", "true", "yes", "on"}


def _provider(model: str) -> str:
    name = (model or "").lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith("nim/") or name.startswith("meta/") or name.startswith("nvidia/"):
        return "nvidia"
    return "google"


def generator_provider() -> str:
    return _provider(GENERATOR_MODEL)


def verifier_provider() -> str:
    """Cheap-path verifier vendor (never reports Claude as the default volume path)."""
    return _provider(VERIFIER_MODEL)


def escalate_provider() -> str:
    return _provider(ESCALATE_MODEL)


def is_cross_model() -> bool:
    """True when the cheap verifier uses a different model than the generator."""
    return GENERATOR_MODEL != VERIFIER_MODEL


def is_cross_provider() -> bool:
    """True when generator and cheap verifier are from different vendors."""
    return generator_provider() != verifier_provider()


def nim_usable() -> bool:
    return bool(NVIDIA_API_KEY)


def gemini_usable() -> bool:
    return bool(GEMINI_API_KEY)


def claude_usable() -> bool:
    return bool(ANTHROPIC_API_KEY)


def verifier_usable() -> bool:
    """Whether any cheap verifier (NIM or Gemini) can run without Claude."""
    if verifier_provider() == "anthropic":
        # Misconfigured volume path — still report Claude key, but prefer cheap.
        return bool(ANTHROPIC_API_KEY) or nim_usable() or gemini_usable()
    if verifier_provider() == "nvidia":
        return nim_usable()
    return gemini_usable() or nim_usable()


def llm_available() -> bool:
    return bool(GEMINI_API_KEY or ANTHROPIC_API_KEY or NVIDIA_API_KEY)


def cheap_verifier_providers() -> list[str]:
    """Available cheap providers in cost order (NIM → Gemini). Claude excluded."""
    available: list[str] = []
    if nim_usable():
        available.append("nim")
    if gemini_usable():
        available.append("gemini")
    return available


def default_verifier_is_claude() -> bool:
    """Cost-guardrail invariant: default VERIFIER_MODEL must not be Claude."""
    return verifier_provider() == "anthropic"
