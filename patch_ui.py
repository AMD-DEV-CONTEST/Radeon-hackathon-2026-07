import re

# 1. Patch main.rs
with open('forge/src/main.rs', 'r') as f:
    main_content = f.read()

if 'mod qualification_lab;' not in main_content:
    main_content = re.sub(r'(mod v3_slice;)', r'\1\nmod qualification_lab;', main_content)

if '.merge(qualification_lab::router())' not in main_content:
    main_content = re.sub(r'(\.route\("/cluster/fleet/clear-all", post\(fleet_clear_all\)\))',
                          r'\1\n        .merge(qualification_lab::router())', main_content)

with open('forge/src/main.rs', 'w') as f:
    f.write(main_content)

print("Patched main.rs")
