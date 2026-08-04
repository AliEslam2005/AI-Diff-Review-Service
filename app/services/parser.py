import re

def parse_diff_lines(diff_text: str):
    """
    Parses a unified diff and yields (file_path, new_line_number, added_line_text)
    """
    lines = diff_text.splitlines()
    file_path = ""
    new_line_num = 0
    
    for line in lines:
        if line.startswith("+++ "):
            # Extract file path, removing 'b/' prefix if present
            path = line[4:].strip().split('\t')[0]
            if path.startswith("b/"):
                path = path[2:]
            file_path = path
        elif line.startswith("@@ "):
            # Extract new line start from @@ -x,y +start,count @@
            match = re.search(r"\+(\d+)", line)
            if match:
                new_line_num = int(match.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            # This is an added line we need to scan
            added_content = line[1:]
            yield (file_path, new_line_num, added_content)
            new_line_num += 1
        elif line.startswith("-") and not line.startswith("---"):
            # Removed lines don't increment the new file's line number
            pass 
        elif line.startswith(" ") or line == "":
            # Context line (unchanged), increment the new file line number
            new_line_num += 1