def split_diff_by_files(diff_text: str) -> list[str]:
    """Splits a unified diff into a list of strings, each representing one file."""
    lines = diff_text.splitlines(keepends=True)
    files = []
    current_file = []
    
    for i, line in enumerate(lines):
        # A new file diff standardly begins with 'diff --git '
        if line.startswith("diff --git "):
            if current_file:
                files.append("".join(current_file))
                current_file = []
        # Fallback for plain unified diffs without a git header
        elif line.startswith("--- ") and i + 1 < len(lines) and lines[i+1].startswith("+++ "):
            if any(l.strip() for l in current_file) and not any(l.startswith("diff --git ") for l in current_file):
                files.append("".join(current_file))
                current_file = []
        
        current_file.append(line)
        
    if current_file:
        files.append("".join(current_file))
        
    return files


def chunk_diff(diff_text: str, max_bytes: int = 65536) -> list[str]:
    """
    Packs file diffs into chunks of at most max_bytes. 
    Files larger than max_bytes are strictly isolated into their own chunks.
    """
    file_blocks = split_diff_by_files(diff_text)
    chunks = []
    current_chunk = ""
    
    for block in file_blocks:
        block_bytes = len(block.encode('utf-8'))
        
        # If adding this file exceeds the limit, flush the current chunk
        if len(current_chunk.encode('utf-8')) + block_bytes > max_bytes:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            
            # If the file itself exceeds max_bytes, it becomes its own standalone chunk
            if block_bytes > max_bytes:
                chunks.append(block)
            else:
                current_chunk = block
        else:
            current_chunk += block
            
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks