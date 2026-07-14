#!/usr/bin/env python3
"""Convert a Shadowrocket [Rule] section into a Clash-compatible `rules:` YAML list."""
import sys


def convert_sr_to_clash(input_file, output_file):
    rules = []
    in_rule_section = False

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Check sections
            if line.startswith('['):
                if line == '[Rule]':
                    in_rule_section = True
                    continue
                else:
                    in_rule_section = False
                    continue

            if not in_rule_section:
                continue

            # Process rule line
            # Remove comments (lines starting with # or content after // or #)
            if line.startswith('#') or line.startswith('//'):
                continue

            # Split by // or # to remove trailing comments
            line = line.split('//')[0].split('#')[0].strip()

            if not line:
                continue

            # Replace FINAL with MATCH
            if line.startswith('FINAL,'):
                line = line.replace('FINAL,', 'MATCH,', 1)

            rules.append(line)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("rules:\n")
        for rule in rules:
            f.write(f"  - {rule}\n")

    print(f"Successfully converted {len(rules)} rules to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_to_clash.py <input.conf> <output.yaml>")
        sys.exit(1)
    convert_sr_to_clash(sys.argv[1], sys.argv[2])
