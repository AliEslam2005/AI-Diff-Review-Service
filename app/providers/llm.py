import os
import json
import hashlib
import google.generativeai as genai

# The SDK will automatically look for the GEMINI_API_KEY environment variable
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def generate_finding_id(path: str, line: int, rule_id: str) -> str:
    """Generates a deterministic ID to support the global deduplication rule."""
    unique_string = f"{path}:{line}:{rule_id}"
    return hashlib.md5(unique_string.encode("utf-8")).hexdigest()

def scan_diff_with_llm(diff_text: str) -> list[dict]:
    """
    Sends a chunked diff to Gemini and returns a list of formatted findings.
    """
    # Using gemini-1.5-flash for fast, cost-effective processing. 
    # You can change this to "gemini-1.5-pro" for deeper reasoning.
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    
    prompt = f"""
    You are an expert strict code reviewer. Analyze the following unified git diff.
    Your task is to identify bugs, security vulnerabilities, or code quality issues ONLY in the added lines (lines starting with '+').
    
    Return a JSON array containing objects with the following exact keys:
    - "path": the file path (string)
    - "line": the integer line number of the added line in the new file (integer)
    - "ruleId": a short, uppercase string identifier for the issue (e.g., "SEC-001", "BUG-002")
    - "message": a concise description of the issue (string)
    - "severity": must be strictly one of "Critical", "High", "Medium", "Low", "Info"
    
    If there are no issues, return an empty array [].
    
    Diff to analyze:
    {diff_text}
    """
    
    try:
        response = model.generate_content(prompt)
        findings_data = json.loads(response.text)
        
        # Ensure the LLM returned a list, and format the IDs
        if not isinstance(findings_data, list):
            return []
            
        formatted_findings = []
        for item in findings_data:
            # Safety check to ensure the LLM provided all required keys
            if all(k in item for k in ("path", "line", "ruleId", "message", "severity")):
                formatted_findings.append({
                    "id": generate_finding_id(item["path"], item["line"], item["ruleId"]),
                    "path": item["path"],
                    "line": int(item["line"]),
                    "ruleId": item["ruleId"],
                    "message": item["message"],
                    "severity": item["severity"]
                })
        return formatted_findings
        
    except Exception as e:
        # In a background worker, if the LLM errors out, we safely return empty for this chunk
        print(f"LLM Processing Error: {e}")
        return []