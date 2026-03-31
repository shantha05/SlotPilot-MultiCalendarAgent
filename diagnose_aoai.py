"""Diagnose Azure AI Foundry / Azure OpenAI 404 errors — checks endpoint and deployment name."""
import os, json, urllib.request
from dotenv import load_dotenv

load_dotenv()

endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
api_key    = os.environ.get("AZURE_OPENAI_API_KEY", "")
deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")

print(f"Endpoint    : {endpoint!r}")
print(f"Deployment  : {deployment!r}")

if not endpoint or not api_key:
    print("\nERROR: AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY is not set in .env")
    raise SystemExit(1)

# Azure AI Inference uses /models endpoint; Azure OpenAI uses /openai/deployments
candidates = []
# Test the actual chat completions endpoint (what the app uses)
payload = json.dumps({
    "messages": [{"role": "user", "content": "Say OK"}],
    "max_tokens": 5,
}).encode()

url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21"
req = urllib.request.Request(url, data=payload,
                              headers={"api-key": api_key, "Content-Type": "application/json"},
                              method="POST")
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    reply = data["choices"][0]["message"]["content"]
    print(f"\nSUCCESS — model replied: {reply!r}")
    print("Azure OpenAI endpoint is working correctly.")
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace")[:400]
    print(f"\n{e.code} error: {body}")
    if e.code == 401:
        print("→ API key is wrong or expired.")
    elif e.code == 404:
        print("→ Deployment name or endpoint is wrong.")
except Exception as e:
    print(f"\nRequest failed: {e}")
