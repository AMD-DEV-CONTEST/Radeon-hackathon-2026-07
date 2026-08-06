"""
mock_responses.py — Pre-scripted, expert-level RTL mock LLM responses.

Used when MOCK_MODE=true so the full agent pipeline (streaming, verilator,
self-correction) can be demoed without a live LLM endpoint.

Tier 1 (lint) responses: tuples of (llm_response_text, verilator_error_or_None).
  - First element has a deliberate syntax bug, second element is clean.

Tier 2 (functional sim) responses: SimResult objects from simulator_tool.
  - The counter scenario passes lint but fails simulation on the first attempt
    (wrong clock edge / behavioral bug that verilator --lint-only cannot catch),
    then the corrected DUT passes on the second attempt.
  - A per-session call counter drives the sequence so successive mock calls
    return the scripted FAIL→PASS sequence without external state injection.
"""

from typing import List, Tuple, Optional


MockResponse = Tuple[str, Optional[str]]


# ─────────────────────────────────────────────────────────────────────────────
#  Helper: wrap SV code in an LLM-style response
# ─────────────────────────────────────────────────────────────────────────────
def _llm_wrap(code: str, preamble: str = "", postamble: str = "") -> str:
    parts = []
    if preamble:
        parts.append(preamble)
    parts.append(f"```systemverilog\n{code}\n```")
    if postamble:
        parts.append(postamble)
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  N-bit Synchronous Counter
# ─────────────────────────────────────────────────────────────────────────────
_COUNTER_BUGGY = """\
`timescale 1ns/1ps
`default_nettype none

module counter #(
    parameter WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,
    input  logic             en,
    output logic [WIDTH-1:0] count,
    output logic             overflow
);

    // Internal carry signal
    logic [WIDTH:0] count_next;

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
        end else if (en) begin
            count <= count_next[WIDTH-1:0]  // MISSING SEMICOLON — verilator error
        end
    end

    always_comb begin
        count_next = {1'b0, count} + 1'b1;
        overflow   = count_next[WIDTH];
    end

endmodule

`default_nettype wire"""

_COUNTER_VERILATOR_ERROR = """\
%Error: design_iter1.sv:18:44: syntax error, unexpected end of file, expecting ';'
   18 |             count <= count_next[WIDTH-1:0]  // MISSING SEMICOLON
      |                                            ^
%Error: Exiting due to 1 error(s)"""

_COUNTER_CLEAN = """\
`timescale 1ns/1ps
`default_nettype none

module counter #(
    parameter WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,
    input  logic             en,
    output logic [WIDTH-1:0] count,
    output logic             overflow
);

    // Extended count to detect overflow on MSB carry
    logic [WIDTH:0] count_ext;

    // ─── Sequential: load next count on each enabled cycle ───────────────
    always_ff @(posedge clk) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
        end else if (en) begin
            count <= count_ext[WIDTH-1:0];
        end
    end

    // ─── Combinational: compute next value and overflow flag ─────────────
    always_comb begin
        count_ext = {1'b0, count} + 1'b1;
        overflow  = count_ext[WIDTH];
    end

endmodule

`default_nettype wire"""


# ─────────────────────────────────────────────────────────────────────────────
#  Synchronous FIFO
# ─────────────────────────────────────────────────────────────────────────────
_FIFO_BUGGY = """\
`timescale 1ns/1ps
`default_nettype none

module sync_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16
) (
    input  logic                  clk,
    input  logic                  rst,
    // Write port
    input  logic                  wr_en,
    input  logic [DATA_WIDTH-1:0] wr_data,
    output logic                  full,
    // Read port
    input  logic                  rd_en,
    output logic [DATA_WIDTH-1:0] rd_data,
    output logic                  empty,
    output logic [$clog2(DEPTH):0] count
);

    localparam PTR_W = $clog2(DEPTH);

    // Memory array and pointers
    logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    logic [PTR_W:0]        wr_ptr;
    reg   [PTR_W:0]        rd_ptr;   // BUG: using reg instead of logic

    assign full  = (count == DEPTH);
    assign empty = (count == 0);

    always_ff @(posedge clk) begin
        if (rst) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            if (wr_en && !full) begin
                mem[wr_ptr[PTR_W-1:0]] <= wr_data;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (rd_en && !empty) begin
                rd_ptr <= rd_ptr + 1'b1;
            end
        end
    end

    assign rd_data = mem[rd_ptr[PTR_W-1:0]];
    assign count   = wr_ptr - rd_ptr;

endmodule

`default_nettype wire"""

_FIFO_VERILATOR_ERROR = """\
%Warning-VARHIDDEN: design_iter1.sv:22:5: Declaration of signal hides declaration in upper scope: 'rd_ptr'
%Warning-SYMRSVD: design_iter1.sv:22:5: Use of Verilog reserved word as identifier: 'reg'
%Error: design_iter1.sv:22:5: Unsupported: SystemVerilog 'reg' type not compatible with --lint-only mode; use 'logic'
%Error: Exiting due to 1 error(s), 2 warning(s)"""

_FIFO_CLEAN = """\
`timescale 1ns/1ps
`default_nettype none

module sync_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16
) (
    input  logic                   clk,
    input  logic                   rst,
    // ─── Write Port ───
    input  logic                   wr_en,
    input  logic [DATA_WIDTH-1:0]  wr_data,
    output logic                   full,
    // ─── Read Port ────
    input  logic                   rd_en,
    output logic [DATA_WIDTH-1:0]  rd_data,
    output logic                   empty,
    output logic [$clog2(DEPTH):0] count
);

    localparam PTR_W = $clog2(DEPTH);

    // ─── Storage and Pointers ─────────────────────────────────────────────
    logic [DATA_WIDTH-1:0] mem     [0:DEPTH-1];
    logic [PTR_W:0]        wr_ptr;
    logic [PTR_W:0]        rd_ptr;

    // ─── Status flags ─────────────────────────────────────────────────────
    assign full    = (count == DEPTH[PTR_W:0]);
    assign empty   = (count == '0);
    assign count   = wr_ptr - rd_ptr;
    assign rd_data = mem[rd_ptr[PTR_W-1:0]];

    // ─── Sequential: pointer updates and write ────────────────────────────
    always_ff @(posedge clk) begin
        if (rst) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            if (wr_en && !full) begin
                mem[wr_ptr[PTR_W-1:0]] <= wr_data;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (rd_en && !empty) begin
                rd_ptr <= rd_ptr + 1'b1;
            end
        end
    end

endmodule

`default_nettype wire"""


# ─────────────────────────────────────────────────────────────────────────────
#  32-bit ALU
# ─────────────────────────────────────────────────────────────────────────────
_ALU_BUGGY = """\
`timescale 1ns/1ps
`default_nettype none

module alu #(
    parameter WIDTH = 32
) (
    input  logic [WIDTH-1:0] a,
    input  logic [WIDTH-1:0] b,
    input  logic [3:0]       op,
    output logic [WIDTH-1:0] result,
    output logic             zero,
    output logic             overflow,
    output logic             carry_out
);

    // ALU operation codes
    localparam OP_ADD  = 4'h0;
    localparam OP_SUB  = 4'h1;
    localparam OP_AND  = 4'h2;
    localparam OP_OR   = 4'h3;
    localparam OP_XOR  = 4'h4;
    localparam OP_NOR  = 4'h5;
    localparam OP_SLL  = 4'h6;
    localparam OP_SRL  = 4'h7;
    localparam OP_SRA  = 4'h8;
    localparam OP_SLT  = 4'h9;

    logic [WIDTH:0] add_result;
    logic [WIDTH:0] sub_result;

    always_comb begin
        add_result = {1'b0, a} + {1'b0, b};
        sub_result = {1'b0, a} - {1'b0, b};
        carry_out  = 1'b0;
        overflow   = 1'b0;
        result     = '0;

        case (op)
            OP_ADD: begin
                result    = add_result[WIDTH-1:0];
                carry_out = add_result[WIDTH];
                overflow  = (a[WIDTH-1] == b[WIDTH-1]) && (result[WIDTH-1] != a[WIDTH-1]);
            end
            OP_SUB: begin
                result   = sub_result[WIDTH-1:0];
                overflow = (a[WIDTH-1] != b[WIDTH-1]) && (result[WIDTH-1] != a[WIDTH-1]);
            end
            OP_AND: result = a & b;
            OP_OR:  result = a | b;
            OP_XOR: result = a ^ b;
            OP_NOR: result = ~(a | b);
            OP_SLL: result = a << b[4:0];
            OP_SRL: result = a >> b[4:0];
            OP_SRA: result = $signed(a) >>> b[4:0]  // MISSING SEMICOLON
            OP_SLT: result = ($signed(a) < $signed(b)) ? {{WIDTH-1{1'b0}}, 1'b1} : '0;
            default: result = '0;
        endcase

        zero = (result == '0);
    end

endmodule

`default_nettype wire"""

_ALU_VERILATOR_ERROR = """\
%Error: design_iter1.sv:51:13: syntax error, unexpected OP_SLT
   51 |             OP_SLT: result = ($signed(a) < $signed(b)) ? ...
      |             ^
%Error: Exiting due to 1 error(s)"""

_ALU_CLEAN = """\
`timescale 1ns/1ps
`default_nettype none

module alu #(
    parameter WIDTH = 32
) (
    input  logic [WIDTH-1:0] a,
    input  logic [WIDTH-1:0] b,
    input  logic [3:0]       op,
    output logic [WIDTH-1:0] result,
    output logic             zero,
    output logic             overflow,
    output logic             carry_out
);

    // ─── Operation Codes ──────────────────────────────────────────────────
    localparam OP_ADD = 4'h0;
    localparam OP_SUB = 4'h1;
    localparam OP_AND = 4'h2;
    localparam OP_OR  = 4'h3;
    localparam OP_XOR = 4'h4;
    localparam OP_NOR = 4'h5;
    localparam OP_SLL = 4'h6;
    localparam OP_SRL = 4'h7;
    localparam OP_SRA = 4'h8;
    localparam OP_SLT = 4'h9;

    // Extended width for carry/borrow detection
    logic [WIDTH:0] add_result;
    logic [WIDTH:0] sub_result;

    // ─── Combinational ALU ────────────────────────────────────────────────
    always_comb begin
        add_result = {1'b0, a} + {1'b0, b};
        sub_result = {1'b0, a} - {1'b0, b};
        carry_out  = 1'b0;
        overflow   = 1'b0;
        result     = '0;

        case (op)
            OP_ADD: begin
                result    = add_result[WIDTH-1:0];
                carry_out = add_result[WIDTH];
                overflow  = (a[WIDTH-1] == b[WIDTH-1]) && (result[WIDTH-1] != a[WIDTH-1]);
            end
            OP_SUB: begin
                result   = sub_result[WIDTH-1:0];
                overflow = (a[WIDTH-1] != b[WIDTH-1]) && (result[WIDTH-1] != a[WIDTH-1]);
            end
            OP_AND:  begin result = a & b;                                end
            OP_OR:   begin result = a | b;                                end
            OP_XOR:  begin result = a ^ b;                                end
            OP_NOR:  begin result = ~(a | b);                             end
            OP_SLL:  begin result = a << b[4:0];                          end
            OP_SRL:  begin result = a >> b[4:0];                          end
            OP_SRA:  begin result = WIDTH'($signed(a) >>> b[4:0]);        end
            OP_SLT:  begin result = ($signed(a) < $signed(b)) ? {{WIDTH-1{1'b0}}, 1'b1} : '0; end
            default: begin result = '0;                                   end
        endcase

        zero = (result == '0);
    end

endmodule

`default_nettype wire"""


# ─────────────────────────────────────────────────────────────────────────────
#  UART Transmitter
# ─────────────────────────────────────────────────────────────────────────────
_UART_BUGGY = """\
`timescale 1ns/1ps
`default_nettype none

module uart_tx #(
    parameter CLK_FREQ  = 50_000_000,
    parameter BAUD_RATE = 115_200
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       tx_start,
    input  logic [7:0] tx_data,
    output logic       tx_serial,
    output logic       tx_busy
);

    localparam CLKS_PER_BIT = CLK_FREQ / BAUD_RATE;
    localparam CNT_W        = $clog2(CLKS_PER_BIT);

    typedef enum logic [2:0] {
        IDLE    = 3'b000,
        START   = 3'b001,
        DATA    = 3'b010,
        STOP    = 3'b011
    } state_t;

    state_t          state;
    logic [CNT_W-1:0] baud_cnt;
    logic [2:0]      bit_idx;
    logic [7:0]      tx_shift;

    always_ff @(posedge clk) begin
        if (rst) begin
            state     <= IDLE;
            tx_serial <= 1'b1;
            tx_busy   <= 1'b0;
            baud_cnt  <= '0;
            bit_idx   <= '0;
            tx_shift  <= '0;
        end else
            // MISSING begin after else — latch risk and verilator error
            case (state)
                IDLE: begin
                    tx_serial <= 1'b1;
                    tx_busy   <= 1'b0;
                    if (tx_start) begin
                        tx_shift <= tx_data;
                        baud_cnt <= '0;
                        state    <= START;
                        tx_busy  <= 1'b1;
                    end
                end
                START: begin
                    tx_serial <= 1'b0;
                    if (baud_cnt == CNT_W'(CLKS_PER_BIT - 1)) begin
                        baud_cnt <= '0;
                        bit_idx  <= '0;
                        state    <= DATA;
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end
                DATA: begin
                    tx_serial <= tx_shift[bit_idx];
                    if (baud_cnt == CNT_W'(CLKS_PER_BIT - 1)) begin
                        baud_cnt <= '0;
                        if (bit_idx == 3'd7) begin
                            state <= STOP;
                        end else begin
                            bit_idx <= bit_idx + 1'b1;
                        end
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end
                STOP: begin
                    tx_serial <= 1'b1;
                    if (baud_cnt == CNT_W'(CLKS_PER_BIT - 1)) begin
                        state    <= IDLE;
                        tx_busy  <= 1'b0;
                        baud_cnt <= '0;
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end
                default: begin
                    state <= IDLE;
                end
            endcase
    end

endmodule

`default_nettype wire"""

_UART_VERILATOR_ERROR = """\
%Error: design_iter1.sv:43:13: Unsupported or syntax error: case statement not inside begin/end block after else
   43 |             case (state)
      |             ^~~~
%Error: design_iter1.sv:43:13: Suggest wrapping the 'else' body in begin/end
%Error: Exiting due to 2 error(s)"""

_UART_CLEAN = """\
`timescale 1ns/1ps
`default_nettype none

module uart_tx #(
    parameter CLK_FREQ  = 50_000_000,
    parameter BAUD_RATE = 115_200
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       tx_start,
    input  logic [7:0] tx_data,
    output logic       tx_serial,
    output logic       tx_busy
);

    // ─── Baud Rate Generator ──────────────────────────────────────────────
    localparam int CLKS_PER_BIT = CLK_FREQ / BAUD_RATE;
    localparam int CNT_W        = $clog2(CLKS_PER_BIT) + 1;

    // ─── FSM State Encoding ───────────────────────────────────────────────
    typedef enum logic [1:0] {
        IDLE  = 2'b00,
        START = 2'b01,
        DATA  = 2'b10,
        STOP  = 2'b11
    } state_t;

    state_t           state;
    logic [CNT_W-1:0] baud_cnt;
    logic [2:0]       bit_idx;
    logic [7:0]       tx_shift;

    // ─── Main UART-TX FSM ─────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (rst) begin
            state     <= IDLE;
            tx_serial <= 1'b1;   // line idles high
            tx_busy   <= 1'b0;
            baud_cnt  <= '0;
            bit_idx   <= '0;
            tx_shift  <= '0;
        end else begin
            case (state)
                IDLE: begin
                    tx_serial <= 1'b1;
                    tx_busy   <= 1'b0;
                    if (tx_start) begin
                        tx_shift <= tx_data;
                        baud_cnt <= '0;
                        tx_busy  <= 1'b1;
                        state    <= START;
                    end
                end

                START: begin
                    tx_serial <= 1'b0;   // start bit
                    if (baud_cnt == CNT_W'(CLKS_PER_BIT - 1)) begin
                        baud_cnt <= '0;
                        bit_idx  <= '0;
                        state    <= DATA;
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end

                DATA: begin
                    tx_serial <= tx_shift[bit_idx];
                    if (baud_cnt == CNT_W'(CLKS_PER_BIT - 1)) begin
                        baud_cnt <= '0;
                        if (bit_idx == 3'd7) begin
                            state <= STOP;
                        end else begin
                            bit_idx <= bit_idx + 1'b1;
                        end
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end

                STOP: begin
                    tx_serial <= 1'b1;   // stop bit
                    if (baud_cnt == CNT_W'(CLKS_PER_BIT - 1)) begin
                        state    <= IDLE;
                        tx_busy  <= 1'b0;
                        baud_cnt <= '0;
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end

                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule

`default_nettype wire"""


# ─────────────────────────────────────────────────────────────────────────────
#  FSM (Traffic Light Controller)
# ─────────────────────────────────────────────────────────────────────────────
_FSM_BUGGY = """\
`timescale 1ns/1ps
`default_nettype none

module traffic_fsm #(
    parameter GREEN_CYCLES  = 10,
    parameter YELLOW_CYCLES = 3,
    parameter RED_CYCLES    = 10
) (
    input  logic clk,
    input  logic rst,
    input  logic emergency,
    output logic red,
    output logic yellow,
    output logic green
);

    typedef enum logic [1:0] {
        S_GREEN  = 2'b00,
        S_YELLOW = 2'b01,
        S_RED    = 2'b10
    } state_t;

    state_t       state;
    logic [3:0]   timer;  // BUG: width too narrow for GREEN_CYCLES=10 (needs 4 bits = max 15, OK)
                          // but using blocking assignment in always_ff below

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= S_RED;
            timer <= '0;
        end else if (emergency) begin
            state <= S_RED;
            timer = '0;   // BUG: blocking assignment inside always_ff
        end else begin
            case (state)
                S_GREEN: begin
                    if (timer == 4'(GREEN_CYCLES - 1)) begin
                        state <= S_YELLOW;
                        timer <= '0;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end
                S_YELLOW: begin
                    if (timer == 4'(YELLOW_CYCLES - 1)) begin
                        state <= S_RED;
                        timer <= '0;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end
                S_RED: begin
                    if (timer == 4'(RED_CYCLES - 1)) begin
                        state <= S_GREEN;
                        timer <= '0;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end
                default: state <= S_RED;
            endcase
        end
    end

    always_comb begin
        green  = (state == S_GREEN);
        yellow = (state == S_YELLOW);
        red    = (state == S_RED) | emergency;
    end

endmodule

`default_nettype wire"""

_FSM_VERILATOR_ERROR = """\
%Warning-BLKSEQ: design_iter1.sv:38:13: Blocking assignment to a sequential variable. Use non-blocking '<='.
   38 |             timer = '0;   // BUG: blocking assignment inside always_ff
      |             ^~~~~
%Error-BLKSEQ: Exiting due to warning treated as error under --Wall. Change to non-blocking '<=' assignment.
%Error: Exiting due to 1 error(s)"""

_FSM_CLEAN = """\
`timescale 1ns/1ps
`default_nettype none

module traffic_fsm #(
    parameter int GREEN_CYCLES  = 10,
    parameter int YELLOW_CYCLES = 3,
    parameter int RED_CYCLES    = 10
) (
    input  logic clk,
    input  logic rst,
    input  logic emergency,
    output logic red,
    output logic yellow,
    output logic green
);

    // Timer width: enough to hold max(GREEN, YELLOW, RED) cycles
    localparam int MAX_CNT = (GREEN_CYCLES > RED_CYCLES) ? GREEN_CYCLES : RED_CYCLES;
    localparam int TMR_W   = $clog2(MAX_CNT + 1) + 1;

    // ─── State Encoding ───────────────────────────────────────────────────
    typedef enum logic [1:0] {
        S_GREEN  = 2'b00,
        S_YELLOW = 2'b01,
        S_RED    = 2'b10
    } state_t;

    state_t          state;
    logic [TMR_W-1:0] timer;

    // ─── Sequential FSM ───────────────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (rst) begin
            state <= S_RED;
            timer <= '0;
        end else if (emergency) begin
            state <= S_RED;     // emergency overrides — non-blocking
            timer <= '0;
        end else begin
            case (state)
                S_GREEN: begin
                    if (timer == TMR_W'(GREEN_CYCLES - 1)) begin
                        state <= S_YELLOW;
                        timer <= '0;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end
                S_YELLOW: begin
                    if (timer == TMR_W'(YELLOW_CYCLES - 1)) begin
                        state <= S_RED;
                        timer <= '0;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end
                S_RED: begin
                    if (timer == TMR_W'(RED_CYCLES - 1)) begin
                        state <= S_GREEN;
                        timer <= '0;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end
                default: begin
                    state <= S_RED;
                end
            endcase
        end
    end

    // ─── Combinational Output Decode ──────────────────────────────────────
    always_comb begin
        green  = (state == S_GREEN)  && !emergency;
        yellow = (state == S_YELLOW) && !emergency;
        red    = (state == S_RED)    || emergency;
    end

endmodule

`default_nettype wire"""


# ─────────────────────────────────────────────────────────────────────────────
#  Dispatcher: keyword → responses
# ─────────────────────────────────────────────────────────────────────────────
def get_mock_responses(spec: str) -> List[MockResponse]:
    """
    Return a list of (llm_response_text, verilator_error_or_None) pairs
    based on keywords found in the user's hardware specification.

    The list is ordered: first element has a bug, second element is clean.
    """
    s = spec.lower()

    if any(kw in s for kw in ["uart", "serial", "baud", "transmit"]):
        return [
            (_llm_wrap(_UART_BUGGY,
                "I'll implement the UART transmitter. Note the FSM-based approach with "
                "a baud-rate counter for precise timing."),
             _UART_VERILATOR_ERROR),
            (_llm_wrap(_UART_CLEAN,
                "I identified the issue: the `else` branch after the reset block was "
                "missing `begin`/`end`, causing a parse error. Here is the corrected UART TX:"),
             None),
        ]
    elif any(kw in s for kw in ["fifo", "queue", "buffer", "depth"]):
        return [
            (_llm_wrap(_FIFO_BUGGY,
                "Here is the synchronous FIFO implementation with separate read/write pointers."),
             _FIFO_VERILATOR_ERROR),
            (_llm_wrap(_FIFO_CLEAN,
                "Fixed: replaced the `reg` declaration with `logic` for `rd_ptr`. "
                "All pointer arithmetic is now clean under `--Wall`."),
             None),
        ]
    elif any(kw in s for kw in ["alu", "arithmetic", "adder", "subtractor", "multiply"]):
        return [
            (_llm_wrap(_ALU_BUGGY,
                "Implementing a parameterized 32-bit ALU with 10 operations."),
             _ALU_VERILATOR_ERROR),
            (_llm_wrap(_ALU_CLEAN,
                "Fixed: added a missing semicolon after the `OP_SRA` case line. "
                "All 10 operations now compile cleanly."),
             None),
        ]
    elif any(kw in s for kw in ["fsm", "state machine", "traffic", "controller", "sequence"]):
        return [
            (_llm_wrap(_FSM_BUGGY,
                "Implementing a Mealy/Moore hybrid traffic-light FSM."),
             _FSM_VERILATOR_ERROR),
            (_llm_wrap(_FSM_CLEAN,
                "Fixed: changed blocking assignment `=` to non-blocking `<=` inside "
                "the `always_ff` block for the emergency timer reset."),
             None),
        ]
    else:
        # Default: parameterized counter (covers 'counter', 'count', and anything else)
        return [
            (_llm_wrap(_COUNTER_BUGGY,
                "I'll design a parameterized synchronous counter with enable and overflow detection."),
             _COUNTER_VERILATOR_ERROR),
            (_llm_wrap(_COUNTER_CLEAN,
                "Fixed: added the missing semicolon after `count <= count_next[WIDTH-1:0]`. "
                "The design now has zero verilator warnings or errors."),
             None),
        ]


# =============================================================================
#  TIER 2 — FUNCTIONAL SIMULATION MOCK DATA
#
#  Scenario: counter with an ASYNCHRONOUS reset (passes verilator --lint-only
#  because async resets are syntactically valid SV) but the spec requires a
#  SYNCHRONOUS reset. The testbench detects this because applying reset mid-cycle
#  immediately clears the counter rather than waiting for the next rising edge.
#
#  This is the canonical example of a bug class that Tier 1 lint CANNOT catch
#  but Tier 2 simulation CAN — exactly the gap the two-tier loop was built to close.
# =============================================================================

# DUT with ASYNC reset — passes --lint-only, fails simulation
_COUNTER_ASYNC_RESET_BUGGY = """\
`timescale 1ns/1ps
`default_nettype none

module counter #(
    parameter WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,
    input  logic             en,
    output logic [WIDTH-1:0] count,
    output logic             overflow
);
    logic [WIDTH:0] count_ext;

    // BUG: asynchronous reset — spec requires synchronous.
    // verilator --lint-only cannot detect this policy violation.
    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
        end else if (en) begin
            count <= count_ext[WIDTH-1:0];
        end
    end

    always_comb begin
        count_ext = {1'b0, count} + 1'b1;
        overflow  = count_ext[WIDTH];
    end

endmodule

`default_nettype wire"""

# DUT with SYNC reset — passes both lint and simulation
_COUNTER_SYNC_RESET_CLEAN = """\
`timescale 1ns/1ps
`default_nettype none

module counter #(
    parameter WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,
    input  logic             en,
    output logic [WIDTH-1:0] count,
    output logic             overflow
);
    // Extended count to detect overflow on MSB carry
    logic [WIDTH:0] count_ext;

    // Synchronous active-high reset — corrected from async version
    always_ff @(posedge clk) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
        end else if (en) begin
            count <= count_ext[WIDTH-1:0];
        end
    end

    always_comb begin
        count_ext = {1'b0, count} + 1'b1;
        overflow  = count_ext[WIDTH];
    end

endmodule

`default_nettype wire"""


# Mock testbench that the agent "generates" in Tier 2 (counter scenario)
_COUNTER_TB_MOCK = """\
```verilog
`timescale 1ns/1ps
`default_nettype none

module tb_counter;
    localparam WIDTH = 4;

    logic             clk = 0;
    logic             rst;
    logic             en;
    logic [WIDTH-1:0] count;
    logic             overflow;

    // DUT instantiation
    counter #(.WIDTH(WIDTH)) dut (
        .clk      (clk),
        .rst      (rst),
        .en       (en),
        .count    (count),
        .overflow (overflow)
    );

    always #5 clk = ~clk;  // 100 MHz clock

    // Watchdog: 500-cycle timeout
    integer cycle_count = 0;
    always_ff @(posedge clk) begin
        cycle_count <= cycle_count + 1;
        if (cycle_count >= 500) begin
            $display("FAIL: timeout — simulation exceeded cycle limit");
            $fatal;
        end
    end

    initial begin
        // ── Test 1: Reset behaviour ──────────────────────────────────────
        rst = 1; en = 0;
        @(posedge clk); #1;
        if (count !== 4'd0) begin
            $display("FAIL: count should be 0 after SYNCHRONOUS reset, got %0d", count);
            $fatal;
        end

        // Release reset, verify count stays at 0 with en=0
        rst = 0; en = 0;
        @(posedge clk); #1;
        if (count !== 4'd0) begin
            $display("FAIL: count should remain 0 when en=0, got %0d", count);
            $fatal;
        end

        // ── Test 2: Normal increment ─────────────────────────────────────
        en = 1;
        repeat(4) @(posedge clk);
        #1;
        if (count !== 4'd4) begin
            $display("FAIL: expected count=4 after 4 enabled cycles, got %0d", count);
            $fatal;
        end

        // ── Test 3: Wraparound / overflow ────────────────────────────────
        en = 1;
        repeat(11) @(posedge clk);
        #1;
        // After 4+11=15 cycles, count should be 15 and overflow next cycle
        if (count !== 4'd15) begin
            $display("FAIL: expected count=15 before overflow, got %0d", count);
            $fatal;
        end
        @(posedge clk); #1;
        if (count !== 4'd0) begin
            $display("FAIL: expected count to wrap to 0 after overflow, got %0d", count);
            $fatal;
        end
        if (overflow !== 1'b0) begin
            // overflow is a combinational look-ahead; at 0 it should be 0
            $display("FAIL: overflow should be 0 when count=0, got %0b", overflow);
            $fatal;
        end

        $display("PASS: all checks passed");
        $finish;
    end
endmodule

`default_nettype wire
```"""

# What the agent says when it "generates" the corrected DUT (Tier 2 correction)
_COUNTER_FUNCTIONAL_FIX_RESPONSE = _llm_wrap(
    _COUNTER_SYNC_RESET_CLEAN,
    "The simulation revealed that the counter uses an asynchronous reset "
    "(`always_ff @(posedge clk or posedge rst)`) but the specification requires "
    "a synchronous active-high reset. The testbench's mid-cycle reset check detected "
    "this because async reset fires immediately rather than on the next clock edge. "
    "I've corrected the sensitivity list to `always_ff @(posedge clk)` — "
    "the reset is now synchronous and the behavioral check will pass.",
)


# ─── Functional mock LLM responses ───────────────────────────────────────────
def get_mock_tb_response(spec: str) -> str:
    """
    Return the mock testbench LLM response for the given spec.
    Used by _mock_loop in agent.py to simulate the testbench-generation step.
    """
    # All scenarios use the counter testbench for the mock demo.
    return _COUNTER_TB_MOCK


def get_mock_functional_fix_response(spec: str) -> str:
    """
    Return the mock LLM response for the functional-correction step.
    This is the DUT rewrite the agent emits after a Tier 2 FAIL.
    """
    return _COUNTER_FUNCTIONAL_FIX_RESPONSE


# ─── Functional SimResult mock ───────────────────────────────────────────────
# Module-level counter tracks how many times get_mock_sim_result has been called
# per session so successive calls return the scripted FAIL→PASS sequence.
_mock_sim_call_count: int = 0


def reset_mock_sim_counter() -> None:
    """Reset the mock simulation call counter — call this at the start of each new session."""
    global _mock_sim_call_count
    _mock_sim_call_count = 0


def get_mock_sim_result(dut_path: str, tb_code: str):
    """
    Return a scripted SimResult for mock mode.

    Call 1: FAIL (behavioral) — counter has async reset, testbench catches it.
    Call 2+: PASS — corrected DUT passes all testbench checks.
    """
    # Lazy import to avoid circular dependency at module load time
    from tools.simulator_tool import SimResult

    global _mock_sim_call_count
    _mock_sim_call_count += 1

    if _mock_sim_call_count == 1:
        # First call: behavioral failure (async reset detected by testbench)
        return SimResult(
            passed=False,
            stdout=(
                "FAIL: count should be 0 after SYNCHRONOUS reset, got 0\n"
                "FAIL: simulation detected asynchronous reset behaviour.\n"
                "      The counter cleared mid-cycle (not on clock edge).\n"
                "      Expected: count remains unchanged until posedge clk after rst=1.\n"
                "      Got: count cleared immediately when rst asserted asynchronously."
            ),
            stderr="%Fatal: tb_counter.sv:42: Verilog $fatal",
            returncode=1,
            timed_out=False,
            phase="run",
            elapsed_ms=312.4,
        )
    else:
        # Second call onward: corrected DUT passes
        mock_vcd = (
            "$date Mon Aug 03 11:00:00 2026 $end\n"
            "$version Verilator 5.020 $end\n"
            "$timescale 1ns $end\n"
            "$scope module tb_counter $end\n"
            "$var wire 1 ! clk $end\n"
            "$var wire 1 \" rst $end\n"
            "$var wire 1 # en $end\n"
            "$var wire 4 $ count [3:0] $end\n"
            "$var wire 1 % overflow $end\n"
            "$upscope $end\n"
            "$enddefinitions $end\n"
            "#0\n0!\n1\"\n0#\nb0000 $\n0%\n"
            "#5\n1!\n#10\n0!\n#15\n1!\n#20\n0!\n0\"\n1#\n"
            "#25\n1!\nb0001 $\n#30\n0!\n#35\n1!\nb0010 $\n"
            "#40\n0!\n#45\n1!\nb0011 $\n#50\n0!\n#55\n1!\nb0100 $\n#60\n0!\n"
            "#65\n1!\nb0101 $\n#70\n0!\n#75\n1!\nb0110 $\n#80\n0!\n"
        )
        return SimResult(
            passed=True,
            stdout="PASS: all checks passed",
            stderr="",
            returncode=0,
            timed_out=False,
            phase="run",
            elapsed_ms=289.1,
            vcd_data=mock_vcd,
            vcd_size_bytes=len(mock_vcd.encode("utf-8")),
        )


def get_mock_architect_response(spec: str) -> str:
    """Return a structured Micro-Architecture and Verification Plan for mock mode."""
    return f"""### Micro-Architecture & Verification Plan

1. Module Overview:
   - Target Spec: {spec.strip()}
   - Architecture: Synchronous digital design with clean clock/reset domains.

2. Interface & Port Definitions:
   - input  logic        clk       // System clock (100MHz / 10ns period)
   - input  logic        rst       // Synchronous active-high reset
   - input  logic        en        // Operation enable strobe
   - output logic [3:0]  count     // Primary registered datapath output
   - output logic        overflow  // Boundary condition indicator

3. Internal Datapath & Registers:
   - Registered datapath with explicit width match to prevent truncation warnings.
   - Separate sequential state registers from combinational next-state computation.

4. Edge Cases & Boundary Handling:
   - Reset assertion during multi-cycle active operations.
   - Max count boundary wraparound (4'b1111 -> 4'b0000) with single-cycle overflow flag.
   - Enable deassertion holding current state without unintended latches.

5. Verification Strategy:
   - Phase 1: Reset assertion and verification of zeroed outputs.
   - Phase 2: Sequential step counting under active enable.
   - Phase 3: Corner-case stimulus checking overflow generation and wraparound.
   - Phase 4: Watchdog timeout bounded to 5000 time units with VCD trace dump.
"""

