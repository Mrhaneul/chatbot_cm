import os
import re

def extract_strings(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()
    
    # Try finding ASCII strings
    ascii_strings = re.findall(b'[\\x20-\\x7E]{10,}', data)
    
    # Try finding UTF-16 strings (common in .msg files)
    utf16_strings = re.findall(b'(?:[\\x20-\\x7E]\\x00){10,}', data)
    
    print(f"--- File: {file_path} ---")
    print("ASCII:")
    for s in ascii_strings[:10]:
        print(s.decode('ascii', errors='ignore'))
    
    print("\nUTF-16:")
    for s in utf16_strings[:10]:
        # Simple decode for the matched pattern
        print(s.decode('utf-16le', errors='ignore'))
    print("-" * 30)

emails_dir = 'emails'
for filename in os.listdir(emails_dir):
    if filename.endswith('.msg'):
        extract_strings(os.path.join(emails_dir, filename))
