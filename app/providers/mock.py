import re
from app.services.parser import parse_diff_lines

# The exact rule table defined in the Xsolla contract
MOCK_RULES = [
    {"ruleId": "MOCK-001", "severity": "critical", "category": "security", "title": "eval usage", "regex": re.compile(r"eval\(")},
    {"ruleId": "MOCK-002", "severity": "critical", "category": "security", "title": "hardcoded credential", "regex": re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")},
    {"ruleId": "MOCK-003", "severity": "high", "category": "security", "title": "SQL string concatenation", "regex": re.compile(r"(?i)(SELECT|INSERT|UPDATE|DELETE).*?\+")},
    {"ruleId": "MOCK-004", "severity": "high", "category": "correctness", "title": "swallowed exception", "regex": re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")}, # Note: We may need to refine this later for multi-line catches
    {"ruleId": "MOCK-005", "severity": "medium", "category": "correctness", "title": "loose null comparison", "regex": re.compile(r"==\s*null|!=\s*null")},
    {"ruleId": "MOCK-006", "severity": "medium", "category": "performance", "title": "deep-clone via JSON", "regex": re.compile(r"JSON\.parse\(JSON\.stringify\(")},
    {"ruleId": "MOCK-007", "severity": "low", "category": "style", "title": "console.log left in", "regex": re.compile(r"console\.log\(")},
    {"ruleId": "MOCK-008", "severity": "low", "category": "style", "title": "unresolved marker", "regex": re.compile(r"TODO|FIXME")},
    {"ruleId": "MOCK-INJ", "severity": "critical", "category": "security", "title": "prompt-injection content", "regex": re.compile(r"(?i)(ignore previous instructions|disregard all prior|you are now)")}
]

def scan_diff_with_mock(diff_text: str):
    findings = []
    
    # 1. Parse lines and match rules
    for file_path, line_num, line_content in parse_diff_lines(diff_text):
        for rule in MOCK_RULES:
            if rule["regex"].search(line_content):
                finding_id = f"{rule['ruleId']}:{file_path}:{line_num}"
                findings.append({
                    "id": finding_id,
                    "ruleId": rule["ruleId"],
                    "path": file_path,
                    "line": line_num,
                    "severity": rule["severity"],
                    "category": rule["category"],
                    "title": rule["title"],
                    "evidence": line_content
                })
                
    # 2. Sort exactly as required: by path, then line, then ruleId
    findings.sort(key=lambda x: (x["path"], x["line"], x["ruleId"]))
    
    # 3. Deduplicate by unique 'id'
    unique_findings = []
    seen_ids = set()
    for finding in findings:
        if finding["id"] not in seen_ids:
            seen_ids.add(finding["id"])
            unique_findings.append(finding)
            
    return unique_findings