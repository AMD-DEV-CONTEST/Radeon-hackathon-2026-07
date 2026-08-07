import re

with open('forge/src/main.rs', 'r') as f:
    main_content = f.read()

main_content = main_content.replace('mod v3_slice;', '//mod v3_slice;')

# we also need to disable the routes that use v3_slice
main_content = re.sub(
    r'\.route\("/forge/v3/demo/aircraft-test-lab", post\(v3_slice::run_aircraft_test_lab_demo\)\)',
    r'//.route("/forge/v3/demo/aircraft-test-lab", post(v3_slice::run_aircraft_test_lab_demo))',
    main_content
)

with open('forge/src/main.rs', 'w') as f:
    f.write(main_content)

print("Patched v3_slice out of main.rs")
