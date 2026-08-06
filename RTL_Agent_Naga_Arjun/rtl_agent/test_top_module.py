"""
test_top_module.py — Unit tests for top-module extraction in simulator_tool and sv_parser.
"""

from tools.simulator_tool import extract_tb_top_module, _strip_comments
from tools.sv_parser import extract_module_name

test_cases = [
    (
        "Comment with module directly",
        """
// We'll test the module directly with WIDTH=1
module tb_full_adder (
    output logic [3:0] s
);
endmodule
// Another comment: test module directly again
""",
        "tb_full_adder",
    ),
    (
        "Block comment with fake module",
        """
/* 
module fake_module (
    input a
);
*/
module tb_shift_reg #(
    parameter WIDTH = 8
) (
    input logic clk
);
endmodule
""",
        "tb_shift_reg",
    ),
    (
        "Generic module without tb_ prefix",
        """
// test the module directly
module my_mux;
endmodule
""",
        "my_mux",
    ),
    (
        "Both DUT and TB in same file (prefers tb_)",
        """
module full_adder(input a, b, cin, output sum, cout);
  assign {cout, sum} = a + b + cin;
endmodule

// Test module directly
module tb_full_adder;
  // body
endmodule
""",
        "tb_full_adder",
    ),
    (
        "Module declaration with semicolon on next line",
        """
module tb_alu
  #(parameter DATA_WIDTH = 32)
  (
    input logic clk
  );
endmodule
""",
        "tb_alu",
    ),
]

all_passed = True
for name, code, expected in test_cases:
    actual_tb = extract_tb_top_module(code)
    actual_sv = extract_module_name(code)
    ok = (actual_tb == expected) and (actual_sv == expected)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    print(f"       extract_tb_top_module: got '{actual_tb}', expected '{expected}'")
    print(f"       extract_module_name  : got '{actual_sv}', expected '{expected}'")
    if not ok:
        all_passed = False

print()
if all_passed:
    print("ALL TOP-MODULE EXTRACTION TESTS PASSED!")
else:
    print("SOME TESTS FAILED!")
    exit(1)
