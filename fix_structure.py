import re

with open('app/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Extract the class access clarification block
class_access_pattern = r'''(            # Handle class access clarification state
            if session\.get\("awaiting_class_access_clarification", False\):
                print\(f".*?Processing class access clarification response"\)

                if is_confirmed_class_access_issue\(message\):.*?llm_time_ms=0\s*\)
                elif is_confirmed_materials_issue\(message\):.*?llm_time_ms=0\s*\)
                else:.*?llm_time_ms=0\s*\))'''

match = re.search(class_access_pattern, content, re.DOTALL)
if match:
    print("Found class access block, extracting...")
    class_access_block = match.group(1)

    # Remove it from its current location
    content_without_block = content[:match.start()] + content[match.end():]

    # Find where to insert it
    insert_marker = '        if session.get("awaiting_platform_type", False):'

    if insert_marker in content_without_block:
        new_content = content_without_block.replace(
            insert_marker,
            class_access_block + '\n\n' + insert_marker
        )

        with open('app/main.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Successfully restructured!")
    else:
        print("Could not find insertion marker")
else:
    print("Could not find class access clarification block")
