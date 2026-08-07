import re
from app.services.parser import parse_diff_lines

# The exact rule table defined in the Xsolla contract
MOCK_RULES = [
    {"ruleId": "MOCK-001", "severity": "critical", "category": "security", "title": "eval usage", "regex": re.compile(r"eval\(")},
    {"ruleId": "MOCK-002", "severity": "critical", "category": "security", "title": "hardcoded credential", "regex": re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")},
    {"ruleId": "MOCK-003", "severity": "high", "category": "security", "title": "SQL string concatenation", "regex": re.compile(r"(?i)(SELECT|INSERT|UPDATE|DELETE).*?\+")},
    {"ruleId": "MOCK-004", "severity": "high", "category": "correctness", "title": "swallowed exception", "regex": re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")}, 
    {"ruleId": "MOCK-005", "severity": "medium", "category": "correctness", "title": "loose null comparison", "regex": re.compile(r"==\s*null|!=\s*null")},
    {"ruleId": "MOCK-006", "severity": "medium", "category": "performance", "title": "deep-clone via JSON", "regex": re.compile(r"JSON\.parse\(JSON\.stringify\(")},
    {"ruleId": "MOCK-007", "severity": "low", "category": "style", "title": "console.log left in", "regex": re.compile(r"console\.log\(")},
    {"ruleId": "MOCK-008", "severity": "low", "category": "style", "title": "unresolved marker", "regex": re.compile(r"TODO|FIXME")},
    {"ruleId": "MOCK-INJ", "severity": "critical", "category": "security", "title": "prompt-injection content", "regex": re.compile(r"(?i)(ignore previous instructions|disregard all prior|you are now)")}
]

def scan_diff_with_mock(diff_text: str):
    findings = []
    
    # Convert the generator to a list so we can index it for multi-line look-aheads
    parsed_lines = list(parse_diff_lines(diff_text))
    
    # 1. Parse lines and match rules
    for i, (file_path, line_num, line_content) in enumerate(parsed_lines):
        
        # Apply all standard single-line rules
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
        
        # 2. Multi-line empty catch block detection (MOCK-004)
        # Check if this line OPENS a catch block but does NOT close it on the same line
        if re.search(r"catch\s*\([^)]*\)\s*\{", line_content) and not re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", line_content):
            is_empty_multiline = False
            
            # Look ahead at the upcoming added lines in the parsed list
            for j in range(i + 1, len(parsed_lines)):
                next_path, _, next_content = parsed_lines[j]
                
                # If we cross into a different file's diff, stop looking
                if next_path != file_path:
                    break
                    
                stripped_next = next_content.strip()
                
                if stripped_next == "}":
                    # We hit the closing brace without finding any actual code
                    is_empty_multiline = True
                    break
                elif stripped_next == "" or stripped_next.startswith("//"):
                    # Blank lines or comments are ignored, keep looking down
                    continue
                else:
                    # We hit actual code (e.g., console.log). Not an empty catch!
                    break
                    
            if is_empty_multiline:
                # Grab the MOCK-004 rule dynamically from the list
                rule_004 = next(r for r in MOCK_RULES if r["ruleId"] == "MOCK-004")
                finding_id = f"{rule_004['ruleId']}:{file_path}:{line_num}"
                findings.append({
                    "id": finding_id,
                    "ruleId": rule_004["ruleId"],
                    "path": file_path,
                    "line": line_num,
                    "severity": rule_004["severity"],
                    "category": rule_004["category"],
                    "title": rule_004["title"],
                    "evidence": line_content
                })
                
    # 3. Sort exactly as required: by path, then line, then ruleId
    findings.sort(key=lambda x: (x["path"], x["line"], x["ruleId"]))
    
    # 4. Deduplicate by unique 'id'
    unique_findings = []
    seen_ids = set()
    for finding in findings:
        if finding["id"] not in seen_ids:
            seen_ids.add(finding["id"])
            unique_findings.append(finding)
            
    return unique_findings