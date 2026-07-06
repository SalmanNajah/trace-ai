import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_gemini_client = None
_gemini_available = None

def _get_gemini_client() -> Optional[Any]:
    global _gemini_client, _gemini_available
    if _gemini_available is not None:
        return _gemini_client
    
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key in ("your_gemini_api_key_here", "PASTE_YOUR_KEY_HERE"):
        _gemini_available = False
        return None
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
        _gemini_available = True
        return _gemini_client
    except Exception as exc:
        logger.warning("Gemini explainer unavailable: %s", exc)
        _gemini_available = False
        return None

def generate_batch_explanations(batch_items: list[dict]) -> list[str]:
    """Generate natural language explanations for a list of requirement-to-code matches.

    Each item in batch_items must contain keys:
      'id': identifier (int or str)
      'requirement': requirement text (str)
      'file_path': code file path (str)
      'code_snippet': matched code content (str)

    Returns a list of explanation strings corresponding to the order of batch_items.
    """
    client = _get_gemini_client()
    if client is None:
        return [""] * len(batch_items)

    inputs = []
    for item in batch_items:
        inputs.append({
            "id": item["id"],
            "requirement": item["requirement"],
            "file_path": item["file_path"],
            "code_snippet": item["code_snippet"][:1200]
        })

    prompt = (
        "You are a software traceability expert. Analyze the relationship between the requirement and the matched code snippet for each of the following items.\n\n"
        "For each item, explain in 1 or 2 concise, clear, and professional sentences why they match. "
        "Explain specifically which part of the code addresses which aspect of the requirement. "
        "Keep each explanation brief (under 50 words) and directly focused on the mapping.\n\n"
        f"ITEMS:\n{json.dumps(inputs, indent=2)}\n\n"
        "Respond ONLY with a JSON object mapping the item ID (as a string) to its explanation string. "
        "Example format: {\"0\": \"This method validates the user login credentials as specified in UC10.\"}"
    )

    try:
        from google.genai import types
        model_name = os.environ.get("TRACEAI_EXPLAINER_MODEL", "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        
        if response and response.text:
            text = response.text.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            
            data = json.loads(text)
            results = []
            for item in batch_items:
                id_str = str(item["id"])
                results.append(data.get(id_str, "").strip())
            return results
    except Exception as exc:
        logger.warning("Failed to generate batch explanations from Gemini: %s", exc)
        
    return [""] * len(batch_items)
