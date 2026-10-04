"""Plain-English explanation of a route's evidence.

The local LLM (Ollama) only rewrites facts the rules produced. Its answer is
checked before it is shown:
  * every number it writes must appear in the evidence, and
  * it may only cite rules that actually flagged, and must cite them.
If the check fails, or Ollama is not running, a deterministic template is used.
Either way the user sees which one wrote the text.
"""

import hashlib
import json
import re

import requests

from config import OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS, OLLAMA_URL, RULES
from db import session

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
CITATION_RE = re.compile(r"\[(R\d)\]")
RULE_MENTION_RE = re.compile(r"\b(R\d)\b")   # also catches bare "R1" without brackets
PROMPT_VERSION = "v3"

SYSTEM_PROMPT = """You explain trade-risk screening results to compliance staff at small manufacturers.

Rules you must follow:
- Use ONLY the facts in the JSON you are given. Do not add outside knowledge.
- Do not invent numbers. Only use numbers that appear in the facts, written the same way.
- After every sentence about a flag, cite its rule id in square brackets, e.g. [R3].
- You may ONLY cite the rule ids listed in "allowed_citations". If that list is empty, cite nothing.
- Only explain the route and its flags. Do NOT mention checks that were not run or why;
  that sentence is added automatically.
- If there are no flags, say that none of the checks raised a flag.
- Do not accuse anyone. This is a screening aid, not proof of wrongdoing.
- Write 3 to 5 plain sentences. No headings, no bullet points, no preamble."""


def build_facts(detail):
    route = detail["route"]
    assessment = detail["assessment"]
    return {
        "mineral": detail["mineral"]["label"],
        "year": route["year"],
        "exporter": route["exporter_name"],
        "importer": route["importer_name"],
        "value": route["value_label"],
        "weight": route["weight_label"],
        "value_reported_by": route["basis"],
        "overall": assessment["level"],
        "flags": [
            {
                "rule": f["rule"],
                "name": f["name"],
                "severity": f["severity"],
                "finding": f["title"],
                "evidence": {e["label"]: e["value"] for e in f["evidence"]},
            }
            for f in assessment["flags"]
        ],
        "allowed_citations": sorted({f["rule"] for f in assessment["flags"]}),
        # No rule ids here on purpose, so the model has nothing to cite by mistake.
        "checks_not_run": [
            {"name": c["name"], "reason": c["note"]}
            for c in assessment["checks"] if c["status"] == "skipped"
        ],
        "checks_run": assessment["checks_run"],
        "checks_total": assessment["checks_total"],
    }


# --------------------------------------------------
# Template (always available, fully deterministic)
# --------------------------------------------------

def facts_for_llm(facts):
    """The model only sees the route and its flags. Skipped checks are described
    by code, word for word, so the model cannot get their reasons wrong."""
    return {k: v for k, v in facts.items() if k not in ("checks_not_run", "checks_run", "checks_total")}


def skipped_sentence(facts):
    skipped = facts["checks_not_run"]
    if not skipped or facts["overall"] == "minor":
        return ""
    names = ", ".join(c["name"].lower() for c in skipped)
    return f"Not enough data to run: {names}."


def template_narrative(facts):
    sentences = [
        f"In {facts['year']}, {facts['exporter']} to {facts['importer']} carried {facts['value']} "
        f"of {facts['mineral'].lower()} ({facts['weight']}), based on the {facts['value_reported_by']}'s report."
    ]

    if facts["overall"] == "minor":
        sentences.append("The route is below the $100,000 size threshold, so the checks were not run.")
        sentences.append(
            "This is a screening result from country-level public trade data, not proof of wrongdoing."
        )
        return " ".join(sentences)

    if facts["flags"]:
        for flag in facts["flags"]:
            sentences.append(f"{flag['name']}: {flag['finding']} [{flag['rule']}].")
    elif facts["checks_run"]:
        sentences.append(
            f"None of the {facts['checks_run']} checks that could run raised a flag."
        )
    else:
        sentences.append("There is not yet enough data to run any of the checks on this route.")

    if skipped_sentence(facts):
        sentences.append(skipped_sentence(facts))

    sentences.append(
        "This is a screening result from country-level public trade data, not proof of wrongdoing."
    )
    return " ".join(sentences)


# --------------------------------------------------
# Validation of LLM output
# --------------------------------------------------

def _numbers(text):
    values = set()
    for match in NUMBER_RE.findall(text):
        try:
            values.add(float(match.replace(",", "")))
        except ValueError:
            pass
    return values


def validate_llm_text(text, facts):
    """Return (ok, reason)."""
    if not text or len(text) < 40:
        return False, "Answer was empty or too short."
    if len(text) > 1500:
        return False, "Answer was too long."

    cited = set(CITATION_RE.findall(text))
    mentioned = set(RULE_MENTION_RE.findall(text))
    flagged = {f["rule"] for f in facts["flags"]}

    unknown = (cited | mentioned) - flagged
    if unknown:
        return False, f"Cited rules that did not flag: {', '.join(sorted(unknown))}."
    if flagged and not cited:
        return False, "Did not cite the rules behind its claims."

    allowed = _numbers(json.dumps(facts, ensure_ascii=False))
    text_without_citations = RULE_MENTION_RE.sub("", CITATION_RE.sub("", text))

    for number in _numbers(text_without_citations):
        if number <= 10 and number == int(number):
            continue  # small counts such as "two checks" or "3 years"
        if not any(abs(number - a) <= max(0.005 * abs(a), 0.01) for a in allowed):
            shown = f"{number:,.2f}".rstrip("0").rstrip(".")
            return False, f"Used a number not found in the evidence ({shown})."

    return True, "Checked against the evidence."


# --------------------------------------------------
# Ollama
# --------------------------------------------------

def _ask_ollama(facts, feedback=None):
    prompt = (
        "Facts (JSON):\n"
        + json.dumps(facts_for_llm(facts), ensure_ascii=False, indent=2)
        + "\n\nWrite the explanation now."
    )
    if feedback:
        prompt += (
            f"\n\nYour previous answer was rejected because: {feedback} "
            "Write it again and follow every rule exactly."
        )
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def ollama_available():
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).ok
    except requests.RequestException:
        return False


def explain(detail, use_llm=True):
    facts = build_facts(detail)
    # The version tag makes answers cached by older versions of this file be ignored.
    cache_key = hashlib.sha256(
        (PROMPT_VERSION + OLLAMA_MODEL + json.dumps(facts, sort_keys=True)).encode("utf-8")
    ).hexdigest()

    if use_llm:
        with session() as conn:
            cached = conn.execute(
                "SELECT text, generator FROM narrative_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if cached:
            return {
                "text": cached["text"],
                "generator": cached["generator"],
                "model": OLLAMA_MODEL,
                "note": "Written locally by Ollama and checked against the evidence.",
            }

        try:
            # Two attempts: if the first answer breaks a rule, tell the model why and ask again.
            llm_facts = facts_for_llm(facts)
            text = _ask_ollama(facts)
            ok, reason = validate_llm_text(text, llm_facts)
            if not ok:
                text = _ask_ollama(facts, feedback=reason)
                ok, reason = validate_llm_text(text, llm_facts)
            if ok:
                text = f"{text} {skipped_sentence(facts)}".strip()
                with session() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO narrative_cache (cache_key, text, generator) VALUES (?, ?, ?)",
                        (cache_key, text, "ollama"),
                    )
                return {
                    "text": text,
                    "generator": "ollama",
                    "model": OLLAMA_MODEL,
                    "note": "Written locally by Ollama and checked against the evidence.",
                }
            note = f"Ollama's answer was rejected: {reason} Showing the template instead."
        except requests.RequestException:
            note = "Ollama is not running, so a template wrote this from the same evidence."
    else:
        note = "Template explanation."

    return {
        "text": template_narrative(facts),
        "generator": "template",
        "model": None,
        "note": note,
    }


def rule_glossary():
    return [{"rule": key, **value} for key, value in RULES.items()]