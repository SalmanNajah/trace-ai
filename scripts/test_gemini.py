"""Quick smoke test for the Gemini explainer integration.

Tests:
  1. API key is loaded and valid
  2. Gemini client initializes successfully
  3. generate_batch_explanations returns meaningful text for a sample payload
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def run_tests():
    print("=" * 60)
    print("Gemini Explainer Integration Test")
    print("=" * 60)

    # --- Test 1: API Key Present ---
    api_key = os.environ.get("GEMINI_API_KEY", "")
    masked = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "(empty)"
    if api_key and api_key not in ("your_gemini_api_key_here", "PASTE_YOUR_KEY_HERE"):
        print(f"\n{GREEN}✓ Test 1 PASS:{RESET} GEMINI_API_KEY loaded ({masked})")
    else:
        print(f"\n{RED}✗ Test 1 FAIL:{RESET} GEMINI_API_KEY not set or placeholder")
        return False

    # --- Test 2: Client Initialization ---
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        print(f"{GREEN}✓ Test 2 PASS:{RESET} google.genai.Client initialized")
    except ImportError:
        print(f"{RED}✗ Test 2 FAIL:{RESET} google-genai package not installed (pip install google-genai)")
        return False
    except Exception as exc:
        print(f"{RED}✗ Test 2 FAIL:{RESET} Client init error: {exc}")
        return False

    # --- Test 3: Simple API call (model list or lightweight generate) ---
    print(f"\n{YELLOW}Running Test 3: Live API call...{RESET}")
    try:
        from google.genai import types
        start = time.time()
        model_name = os.environ.get("TRACEAI_EXPLAINER_MODEL", "gemini-2.5-flash")
        print(f"  Using model: {model_name}")
        response = client.models.generate_content(
            model=model_name,
            contents="Respond with exactly: {\"status\": \"ok\"}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0
            ),
        )
        elapsed = time.time() - start
        if response and response.text:
            data = json.loads(response.text.strip())
            print(f"{GREEN}✓ Test 3 PASS:{RESET} API responded in {elapsed:.2f}s → {data}")
        else:
            print(f"{RED}✗ Test 3 FAIL:{RESET} Empty response from Gemini")
            return False
    except Exception as exc:
        print(f"{RED}✗ Test 3 FAIL:{RESET} API call error: {exc}")
        return False

    # --- Test 4: generate_batch_explanations with real payload ---
    print(f"\n{YELLOW}Running Test 4: generate_batch_explanations...{RESET}")
    from traceai_v2.explainer import generate_batch_explanations

    sample_batch = [
        {
            "id": 0,
            "requirement": "REQ-AUTH-001: The system shall allow users to log in with email and password.",
            "file_path": "app/controllers/sessions_controller.rb",
            "code_snippet": "def create\n  user = User.find_by(email: params[:email])\n  if user&.authenticate(params[:password])\n    session[:user_id] = user.id\n    redirect_to root_path\n  else\n    flash[:alert] = 'Invalid credentials'\n    render :new\n  end\nend",
        },
        {
            "id": 1,
            "requirement": "REQ-UI-005: The dashboard shall display the user's account balance.",
            "file_path": "app/frontend/components/Dashboard.tsx",
            "code_snippet": "export function Dashboard({ user }: Props) {\n  return (\n    <div className='balance-card'>\n      <h2>Account Balance</h2>\n      <span>{formatCurrency(user.balance)}</span>\n    </div>\n  );\n}",
        },
    ]

    start = time.time()
    results = generate_batch_explanations(sample_batch)
    elapsed = time.time() - start

    all_ok = True
    for i, (item, explanation) in enumerate(zip(sample_batch, results)):
        if explanation and len(explanation) > 10:
            print(f"  {GREEN}✓ Item {i}:{RESET} \"{explanation[:100]}{'...' if len(explanation) > 100 else ''}\"")
        else:
            print(f"  {RED}✗ Item {i}:{RESET} Empty or too-short explanation: \"{explanation}\"")
            all_ok = False

    if all_ok:
        print(f"\n{GREEN}✓ Test 4 PASS:{RESET} All {len(results)} explanations generated in {elapsed:.2f}s")
    else:
        print(f"\n{RED}✗ Test 4 FAIL:{RESET} Some explanations missing")

    print("\n" + "=" * 60)
    if all_ok:
        print(f"{GREEN}ALL TESTS PASSED{RESET} — Gemini explainer is working correctly!")
    else:
        print(f"{RED}SOME TESTS FAILED{RESET} — Check output above for details.")
    print("=" * 60)
    return all_ok


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
