with open('app/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# The class access clarification block starts at line 1343 and ends at line 1420
# Lines are 0-indexed, so subtract 1
start_line = 1343 - 1  # 1342
end_line = 1420 - 1      # 1419

# Extract the block (lines 1343-1420)
block_lines = lines[start_line:end_line+1]

# Remove the block from current location
lines_without_block = lines[:start_line] + lines[end_line+1:]

# Find the new insertion point - before "if session.get("awaiting_platform_type", False):"
insert_content = '        if session.get("awaiting_platform_type", False):\n'

insert_idx = None
for i, line in enumerate(lines_without_block):
    if insert_content in line:
        insert_idx = i
        break

if insert_idx is None:
    print("Could not find insertion point")
else:
    # Insert the block before the awaiting_platform_type check
    new_lines = lines_without_block[:insert_idx] + ['\n'] + block_lines + ['\n'] + lines_without_block[insert_idx:]
    
    with open('app/main.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"Successfully moved block to before line {insert_idx + 1}")
