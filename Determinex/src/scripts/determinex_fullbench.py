"""
determinex_fullbench.py — Comprehensive multi-language benchmark
=============================================================
A HumanEval/SWE-bench comparable evaluation for Determinex models.
Covers Rust, Go, Python, TypeScript with compiler verification.

SCORING CONTEXT (apples-to-apples with frontier models):
  This benchmark targets HumanEval-equivalent difficulty.
  Published pass@1 baselines (as of 2026-04):
    Claude Opus 4.7      ~95%   (HumanEval)
    Claude Sonnet 4.6    ~93%   (HumanEval)
    GPT-4o               ~90%   (HumanEval)
    Gemini 3.1 Pro       ~91%   (HumanEval)
    DeepSeek-Coder-7B    ~78%   (HumanEval)
    Qwen2.5-Coder-7B     ~83%   (HumanEval)
    Qwen2.5-Coder-3B     ~75%   (HumanEval)
    Qwen2.5-Coder-1.5B   ~62%   (HumanEval)

  Gap between Determinex models and base Qwen = DSL fine-tune + corpus lift.
  Gap between Determinex models and frontier = training data volume + model scale.
  This number is the honest gap — what we're training to close.

PIVOT NOTE (2026-04-18):
  micro_eval (14 concepts, 70 probes) was designed to catch regressions in
  specific Rust/Go patterns. It is NOT a capability benchmark — it is a
  regression detector. The engineer drop from 84% to 71% on micro_eval
  reflects loss of focused Rust/Go training (old curriculum not included
  in this training run), NOT a general capability regression.

  determinex_fullbench covers the full spectrum and gives the true capability
  number: where each model sits on the global leaderboard and what training
  is needed to close the gap to frontier.

Usage:
  python scripts/determinex_fullbench.py --model determinex-observer-v5-dsl
  python scripts/determinex_fullbench.py --model determinex-sentinel-v3 --save
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import logging

logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)

from micro_eval import _strip_fences, ask_student

# ---------------------------------------------------------------------------
# TIER 1 — Algorithmic core (HumanEval difficulty parity)
# ---------------------------------------------------------------------------

BENCH_CONCEPTS = {
    # ── RUST ────────────────────────────────────────────────────────────────
    "rust_binary_search": {
        "lang": "rust",
        "system": "You are an expert Rust programmer.",
        "probes": [
            {
                "id": "RBS_P1",
                "prompt": "Write a Rust function `binary_search(arr: &[i32], target: i32) -> Option<usize>` that returns the index of target in a sorted slice, or None if not found.",
                "test": r"""
fn binary_search(arr: &[i32], target: i32) -> Option<usize>;
fn main() {
    let arr = vec![1, 3, 5, 7, 9, 11, 13];
    assert_eq!(binary_search(&arr, 7), Some(3));
    assert_eq!(binary_search(&arr, 1), Some(0));
    assert_eq!(binary_search(&arr, 13), Some(6));
    assert_eq!(binary_search(&arr, 4), None);
    assert_eq!(binary_search(&[], 1), None);
    println!("ok");
}""",
            },
            {
                "id": "RBS_P2",
                "prompt": "Write a Rust function `binary_search_first(arr: &[i32], target: i32) -> Option<usize>` that returns the FIRST index of target in a sorted slice with possible duplicates.",
                "test": r"""
fn binary_search_first(arr: &[i32], target: i32) -> Option<usize>;
fn main() {
    let arr = vec![1, 2, 2, 2, 3, 4];
    assert_eq!(binary_search_first(&arr, 2), Some(1));
    assert_eq!(binary_search_first(&arr, 1), Some(0));
    assert_eq!(binary_search_first(&arr, 5), None);
    println!("ok");
}""",
            },
        ],
    },
    "rust_linked_list": {
        "lang": "rust",
        "system": "You are an expert Rust programmer.",
        "probes": [
            {
                "id": "RLL_P1",
                "prompt": "Write a Rust function `list_len(head: &Option<Box<Node>>) -> usize` where `struct Node { val: i32, next: Option<Box<Node>> }`. Return the number of nodes.",
                "test": r"""
struct Node { val: i32, next: Option<Box<Node>> }
fn list_len(head: &Option<Box<Node>>) -> usize;
fn main() {
    let list = Some(Box::new(Node { val: 1, next: Some(Box::new(Node { val: 2, next: Some(Box::new(Node { val: 3, next: None })) })) }));
    assert_eq!(list_len(&list), 3);
    assert_eq!(list_len(&None), 0);
    println!("ok");
}""",
            },
            {
                "id": "RLL_P2",
                "prompt": "Write a Rust function `reverse_list(head: Option<Box<Node>>) -> Option<Box<Node>>` where `struct Node { val: i32, next: Option<Box<Node>> }`. Return the reversed list.",
                "test": r"""
struct Node { val: i32, next: Option<Box<Node>> }
fn reverse_list(head: Option<Box<Node>>) -> Option<Box<Node>>;
fn to_vec(head: &Option<Box<Node>>) -> Vec<i32> {
    let mut v = vec![];
    let mut cur = head;
    while let Some(n) = cur { v.push(n.val); cur = &n.next; }
    v
}
fn make_list(vals: &[i32]) -> Option<Box<Node>> {
    let mut head = None;
    for &v in vals.iter().rev() { head = Some(Box::new(Node { val: v, next: head })); }
    head
}
fn main() {
    let list = make_list(&[1, 2, 3, 4]);
    let rev = reverse_list(list);
    assert_eq!(to_vec(&rev), vec![4, 3, 2, 1]);
    assert!(reverse_list(None).is_none());
    println!("ok");
}""",
            },
        ],
    },
    "rust_trait_impl": {
        "lang": "rust",
        "system": "You are an expert Rust programmer.",
        "probes": [
            {
                "id": "RTR_P1",
                "prompt": "Implement a `Stack<T>` struct in Rust with `push`, `pop`, `peek`, and `is_empty` methods. `pop` and `peek` return `Option<T>` and `Option<&T>` respectively.",
                "test": r"""
fn main() {
    let mut s: Stack<i32> = Stack::new();
    assert!(s.is_empty());
    s.push(1); s.push(2); s.push(3);
    assert_eq!(s.peek(), Some(&3));
    assert_eq!(s.pop(), Some(3));
    assert_eq!(s.pop(), Some(2));
    assert!(!s.is_empty());
    assert_eq!(s.pop(), Some(1));
    assert_eq!(s.pop(), None);
    assert!(s.is_empty());
    println!("ok");
}""",
            },
            {
                "id": "RTR_P2",
                "prompt": "Implement the `Display` trait for a `Point { x: f64, y: f64 }` struct so it prints as `(x, y)`, and a method `distance_to(&self, other: &Point) -> f64`.",
                "test": r"""
fn main() {
    let p1 = Point { x: 0.0, y: 0.0 };
    let p2 = Point { x: 3.0, y: 4.0 };
    assert_eq!(format!("{}", p1), "(0, 0)");
    let d = p1.distance_to(&p2);
    assert!((d - 5.0).abs() < 1e-9);
    println!("ok");
}""",
            },
        ],
    },
    "rust_error_chain": {
        "lang": "rust",
        "system": "You are an expert Rust programmer.",
        "probes": [
            {
                "id": "REC_P1",
                "prompt": "Write a Rust function `parse_and_double(s: &str) -> Result<i32, String>` that parses an integer from `s` and returns double the value, or an error message if parsing fails.",
                "test": r"""
fn parse_and_double(s: &str) -> Result<i32, String>;
fn main() {
    assert_eq!(parse_and_double("21"), Ok(42));
    assert_eq!(parse_and_double("0"), Ok(0));
    assert!(parse_and_double("abc").is_err());
    assert!(parse_and_double("").is_err());
    println!("ok");
}""",
            },
            {
                "id": "REC_P2",
                "prompt": "Write a Rust function `read_positive(s: &str) -> Result<u32, String>` that parses `s` as a positive integer (> 0). Return `Err` if not a valid number or if it's zero or negative.",
                "test": r"""
fn read_positive(s: &str) -> Result<u32, String>;
fn main() {
    assert_eq!(read_positive("42"), Ok(42));
    assert_eq!(read_positive("1"), Ok(1));
    assert!(read_positive("0").is_err());
    assert!(read_positive("-5").is_err());
    assert!(read_positive("abc").is_err());
    println!("ok");
}""",
            },
        ],
    },
    "rust_iterator_chain": {
        "lang": "rust",
        "system": "You are an expert Rust programmer.",
        "probes": [
            {
                "id": "RIC_P1",
                "prompt": "Write a Rust function `sum_of_squares_of_evens(nums: &[i32]) -> i32` using iterators: filter even numbers, square them, and sum the results.",
                "test": r"""
fn sum_of_squares_of_evens(nums: &[i32]) -> i32;
fn main() {
    assert_eq!(sum_of_squares_of_evens(&[1, 2, 3, 4, 5]), 20); // 4 + 16
    assert_eq!(sum_of_squares_of_evens(&[1, 3, 5]), 0);
    assert_eq!(sum_of_squares_of_evens(&[]), 0);
    assert_eq!(sum_of_squares_of_evens(&[2]), 4);
    println!("ok");
}""",
            },
            {
                "id": "RIC_P2",
                "prompt": "Write a Rust function `word_lengths(sentence: &str) -> Vec<(String, usize)>` that splits the sentence by whitespace and returns each word paired with its length, sorted by length descending.",
                "test": r"""
fn word_lengths(sentence: &str) -> Vec<(String, usize)>;
fn main() {
    let result = word_lengths("hello world hi");
    assert_eq!(result[0], ("hello".to_string(), 5));
    assert_eq!(result[1], ("world".to_string(), 5));
    assert_eq!(result[2], ("hi".to_string(), 2));
    assert_eq!(word_lengths("").len(), 0);
    println!("ok");
}""",
            },
        ],
    },
    # ── GO ──────────────────────────────────────────────────────────────────
    "go_worker_pool": {
        "lang": "go",
        "system": "You are an expert Go programmer.",
        "probes": [
            {
                "id": "GWP_P1",
                "prompt": "Write a Go function `worker_pool(jobs []int, workers int, process func(int) int) []int` that processes jobs concurrently using `workers` goroutines and returns results in the same order as input.",
                "test": r"""
package main
import "fmt"
func worker_pool(jobs []int, workers int, process func(int) int) []int
func main() {
    result := worker_pool([]int{1, 2, 3, 4, 5}, 3, func(n int) int { return n * n })
    expected := []int{1, 4, 9, 16, 25}
    for i, v := range expected {
        if result[i] != v { panic(fmt.Sprintf("index %d: got %d want %d", i, result[i], v)) }
    }
    empty := worker_pool([]int{}, 2, func(n int) int { return n })
    if len(empty) != 0 { panic("expected empty") }
    fmt.Println("ok")
}""",
            },
            {
                "id": "GWP_P2",
                "prompt": "Write a Go function `fan_out(input <-chan int, n int) []<-chan int` that reads from input and distributes values round-robin to n output channels. Close all output channels when input closes.",
                "test": r"""
package main
import "fmt"
func fan_out(input <-chan int, n int) []<-chan int
func main() {
    in := make(chan int, 6)
    for _, v := range []int{0, 1, 2, 3, 4, 5} { in <- v }
    close(in)
    outs := fan_out(in, 3)
    if len(outs) != 3 { panic("wrong number of channels") }
    total := 0
    for _, ch := range outs { for v := range ch { total += v } }
    if total != 15 { panic(fmt.Sprintf("sum mismatch: %d", total)) }
    fmt.Println("ok")
}""",
            },
        ],
    },
    "go_interface": {
        "lang": "go",
        "system": "You are an expert Go programmer.",
        "probes": [
            {
                "id": "GIF_P1",
                "prompt": "Define a Go `Shape` interface with `Area() float64` and `Perimeter() float64`. Implement it for `Circle` (radius float64) and `Rectangle` (width, height float64). Use math.Pi for circle.",
                "test": r"""
package main
import (
    "fmt"
    "math"
)
type Shape interface {
    Area() float64
    Perimeter() float64
}
type Circle struct { Radius float64 }
type Rectangle struct { Width, Height float64 }
func (c Circle) Area() float64
func (c Circle) Perimeter() float64
func (r Rectangle) Area() float64
func (r Rectangle) Perimeter() float64
func main() {
    c := Circle{Radius: 5}
    r := Rectangle{Width: 3, Height: 4}
    if math.Abs(c.Area() - math.Pi*25) > 0.001 { panic("circle area") }
    if math.Abs(c.Perimeter() - 2*math.Pi*5) > 0.001 { panic("circle perimeter") }
    if r.Area() != 12 { panic("rect area") }
    if r.Perimeter() != 14 { panic("rect perimeter") }
    fmt.Println("ok")
}""",
            },
            {
                "id": "GIF_P2",
                "prompt": "Write a Go function `largest_area(shapes []Shape) Shape` that returns the shape with the largest area. Return nil if slice is empty.",
                "test": r"""
package main
import (
    "fmt"
    "math"
)
type Shape interface { Area() float64 }
type Circle struct { Radius float64 }
type Rectangle struct { Width, Height float64 }
func (c Circle) Area() float64 { return math.Pi * c.Radius * c.Radius }
func (r Rectangle) Area() float64 { return r.Width * r.Height }
func largest_area(shapes []Shape) Shape
func main() {
    shapes := []Shape{Circle{3}, Rectangle{4, 5}, Circle{5}}
    s := largest_area(shapes)
    if math.Abs(s.Area() - math.Pi*25) > 0.001 { panic("wrong shape") }
    if largest_area([]Shape{}) != nil { panic("expected nil") }
    fmt.Println("ok")
}""",
            },
        ],
    },
    "go_context": {
        "lang": "go",
        "system": "You are an expert Go programmer.",
        "probes": [
            {
                "id": "GCT_P1",
                "prompt": "Write a Go function `fetch_with_timeout(ctx context.Context, work func() (string, error)) (string, error)` that runs work in a goroutine and returns its result, or ctx.Err() if the context is cancelled first.",
                "test": r"""
package main
import (
    "context"
    "fmt"
    "time"
)
func fetch_with_timeout(ctx context.Context, work func() (string, error)) (string, error)
func main() {
    ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
    defer cancel()
    result, err := fetch_with_timeout(ctx, func() (string, error) {
        return "done", nil
    })
    if err != nil || result != "done" { panic(fmt.Sprintf("fast work failed: %v %v", result, err)) }

    ctx2, cancel2 := context.WithTimeout(context.Background(), 10*time.Millisecond)
    defer cancel2()
    _, err2 := fetch_with_timeout(ctx2, func() (string, error) {
        time.Sleep(100 * time.Millisecond)
        return "late", nil
    })
    if err2 == nil { panic("expected timeout error") }
    fmt.Println("ok")
}""",
            },
        ],
    },
    "go_functional": {
        "lang": "go",
        "system": "You are an expert Go programmer.",
        "probes": [
            {
                "id": "GFN_P1",
                "prompt": "Write Go generic functions `Map[T, U any](s []T, f func(T) U) []U`, `Filter[T any](s []T, f func(T) bool) []T`, and `Reduce[T, U any](s []T, init U, f func(U, T) U) U`.",
                "test": r"""
package main
import "fmt"
func Map[T, U any](s []T, f func(T) U) []U
func Filter[T any](s []T, f func(T) bool) []T
func Reduce[T, U any](s []T, init U, f func(U, T) U) U
func main() {
    doubled := Map([]int{1, 2, 3}, func(x int) int { return x * 2 })
    if fmt.Sprint(doubled) != "[2 4 6]" { panic("map failed") }
    evens := Filter([]int{1, 2, 3, 4, 5}, func(x int) bool { return x%2 == 0 })
    if fmt.Sprint(evens) != "[2 4]" { panic("filter failed") }
    sum := Reduce([]int{1, 2, 3, 4}, 0, func(acc, x int) int { return acc + x })
    if sum != 10 { panic("reduce failed") }
    fmt.Println("ok")
}""",
            },
        ],
    },
    # ── PYTHON ──────────────────────────────────────────────────────────────
    "py_two_sum": {
        "lang": "python",
        "system": "You are an expert Python programmer.",
        "probes": [
            {
                "id": "PTS_P1",
                "prompt": "Write a Python function `two_sum(nums: list[int], target: int) -> tuple[int, int]` that returns indices of the two numbers that add up to target. Each input has exactly one solution.",
                "test": r"""
result = two_sum([2, 7, 11, 15], 9)
assert sorted(result) == [0, 1], result
result2 = two_sum([3, 2, 4], 6)
assert sorted(result2) == [1, 2], result2
result3 = two_sum([3, 3], 6)
assert sorted(result3) == [0, 1], result3
print("ok")
""",
            },
            {
                "id": "PTS_P2",
                "prompt": "Write a Python function `group_anagrams(words: list[str]) -> list[list[str]]` that groups anagrams together. Each group should be sorted internally, and groups should be sorted by their first element.",
                "test": r"""
result = group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"])
result = [sorted(g) for g in result]
result.sort(key=lambda g: g[0])
expected = [['ate', 'eat', 'tea'], ['bat'], ['nat', 'tan']]
assert result == expected, result
assert group_anagrams([]) == []
print("ok")
""",
            },
        ],
    },
    "py_lru_cache": {
        "lang": "python",
        "system": "You are an expert Python programmer.",
        "probes": [
            {
                "id": "PLR_P1",
                "prompt": "Implement a Python `LRUCache` class with `__init__(self, capacity: int)`, `get(self, key: int) -> int` (return -1 if absent), and `put(self, key: int, value: int)` that evicts the least-recently-used item when over capacity.",
                "test": r"""
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
assert cache.get(1) == 1
cache.put(3, 3)  # evicts key 2
assert cache.get(2) == -1
cache.put(4, 4)  # evicts key 1
assert cache.get(1) == -1
assert cache.get(3) == 3
assert cache.get(4) == 4
print("ok")
""",
            },
        ],
    },
    "py_async": {
        "lang": "python",
        "system": "You are an expert Python programmer.",
        "probes": [
            {
                "id": "PAS_P1",
                "prompt": "Write a Python async function `gather_results(coros: list) -> list` that runs all coroutines concurrently and returns their results in order. Use asyncio.gather.",
                "test": r"""
import asyncio

async def double(x):
    await asyncio.sleep(0)
    return x * 2

results = asyncio.run(gather_results([double(1), double(2), double(3)]))
assert results == [2, 4, 6], results
print("ok")
""",
            },
            {
                "id": "PAS_P2",
                "prompt": "Write a Python async function `retry_async(coro_fn, attempts: int, delay: float)` that calls `coro_fn()` up to `attempts` times, waiting `delay` seconds between attempts, returning the first successful result or raising the last exception.",
                "test": r"""
import asyncio

call_count = 0
async def flaky():
    global call_count
    call_count += 1
    if call_count < 3:
        raise ValueError("not yet")
    return "success"

result = asyncio.run(retry_async(flaky, 5, 0))
assert result == "success", result
assert call_count == 3

async def always_fails():
    raise RuntimeError("nope")

try:
    asyncio.run(retry_async(always_fails, 3, 0))
    assert False, "should have raised"
except RuntimeError:
    pass
print("ok")
""",
            },
        ],
    },
    "py_datastructures": {
        "lang": "python",
        "system": "You are an expert Python programmer.",
        "probes": [
            {
                "id": "PDS_P1",
                "prompt": "Write a Python function `valid_parentheses(s: str) -> bool` that returns True if the string of brackets `()[]{}` is valid (properly opened and closed in order).",
                "test": r"""
assert valid_parentheses("()") == True
assert valid_parentheses("()[]{}") == True
assert valid_parentheses("(]") == False
assert valid_parentheses("([)]") == False
assert valid_parentheses("{[]}") == True
assert valid_parentheses("") == True
assert valid_parentheses("(") == False
print("ok")
""",
            },
            {
                "id": "PDS_P2",
                "prompt": "Write a Python function `flatten(nested: list) -> list` that recursively flattens a nested list of any depth into a single flat list.",
                "test": r"""
assert flatten([1, [2, 3], [4, [5, 6]]]) == [1, 2, 3, 4, 5, 6]
assert flatten([]) == []
assert flatten([1, 2, 3]) == [1, 2, 3]
assert flatten([[[[1]]]]) == [1]
assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]
print("ok")
""",
            },
        ],
    },
    "py_functional": {
        "lang": "python",
        "system": "You are an expert Python programmer.",
        "probes": [
            {
                "id": "PFN_P1",
                "prompt": "Write a Python function `compose(*fns)` that returns a new function which applies functions right-to-left. `compose(f, g, h)(x)` should equal `f(g(h(x)))`.",
                "test": r"""
double = lambda x: x * 2
add_one = lambda x: x + 1
square = lambda x: x ** 2
f = compose(double, add_one, square)
assert f(3) == 20   # double(add_one(square(3))) = double(add_one(9)) = double(10) = 20
assert f(0) == 2    # double(add_one(0)) = double(1) = 2
g = compose(str, double)
assert g(5) == "10"
print("ok")
""",
            },
            {
                "id": "PFN_P2",
                "prompt": "Write a Python function `memoize(fn)` that returns a memoized version of `fn`. It should cache results by arguments and return cached results on repeated calls.",
                "test": r"""
call_count = 0
def slow_square(n):
    global call_count
    call_count += 1
    return n * n

memo_square = memoize(slow_square)
assert memo_square(5) == 25
assert memo_square(5) == 25
assert call_count == 1   # called only once
assert memo_square(6) == 36
assert call_count == 2
print("ok")
""",
            },
        ],
    },
    # ── TYPESCRIPT ──────────────────────────────────────────────────────────
    "ts_type_system": {
        "lang": "typescript",
        "system": "You are an expert TypeScript programmer.",
        "probes": [
            {
                "id": "TST_P1",
                "prompt": "Write TypeScript types and a function `parseResult<T>(json: string, validator: (x: unknown) => x is T): Result<T, string>` where `Result<T, E> = { ok: true; value: T } | { ok: false; error: E }`. Return error string if JSON is invalid or validator fails.",
                "test": r"""
const isNumber = (x: unknown): x is number => typeof x === 'number';
const r1 = parseResult<number>('42', isNumber);
if (!r1.ok || r1.value !== 42) throw new Error('expected ok with 42');
const r2 = parseResult<number>('"hello"', isNumber);
if (r2.ok) throw new Error('expected error for string');
const r3 = parseResult<number>('{bad json', isNumber);
if (r3.ok) throw new Error('expected error for bad json');
console.log('ok');
""",
            },
            {
                "id": "TST_P2",
                "prompt": "Write a TypeScript function `deepFreeze<T extends object>(obj: T): Readonly<T>` that recursively freezes an object and all its nested objects.",
                "test": r"""
const obj = deepFreeze({ a: 1, b: { c: 2, d: { e: 3 } } });
let threw = false;
try { (obj as any).a = 99; } catch { threw = true; }
if (!threw && (obj as any).a !== 1) throw new Error('outer not frozen');
threw = false;
try { (obj as any).b.c = 99; } catch { threw = true; }
if (!threw && (obj as any).b.c !== 2) throw new Error('inner not frozen');
console.log('ok');
""",
            },
        ],
    },
    "ts_async": {
        "lang": "typescript",
        "system": "You are an expert TypeScript programmer.",
        "probes": [
            {
                "id": "TSA_P1",
                "prompt": "Write a TypeScript function `retry<T>(fn: () => Promise<T>, times: number, delayMs: number): Promise<T>` that retries fn up to `times` times with `delayMs` delay between attempts, throwing the last error if all fail.",
                "test": r"""
let count = 0;
const flaky = (): Promise<string> => {
    count++;
    if (count < 3) return Promise.reject(new Error('not yet'));
    return Promise.resolve('success');
};
retry(flaky, 5, 0).then(result => {
    if (result !== 'success') throw new Error('wrong result');
    if (count !== 3) throw new Error('wrong call count');
    return retry(() => Promise.reject(new Error('always fails')), 3, 0);
}).catch(e => {
    if (!e.message.includes('always fails')) throw new Error('wrong error');
    console.log('ok');
});
""",
            },
        ],
    },
    "ts_data_transform": {
        "lang": "typescript",
        "system": "You are an expert TypeScript programmer.",
        "probes": [
            {
                "id": "TSD_P1",
                "prompt": "Write a TypeScript function `groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]>` that groups array items by a key function.",
                "test": r"""
const words = ['one', 'two', 'three', 'four', 'five'];
const byLength = groupBy(words, w => String(w.length));
if (JSON.stringify(byLength['3'].sort()) !== '["one","two"]') throw new Error('len 3');
if (JSON.stringify(byLength['5'].sort()) !== '["three"]') throw new Error('len 5 - three');
const nums = [1, 2, 3, 4, 5, 6];
const byParity = groupBy(nums, n => n % 2 === 0 ? 'even' : 'odd');
if (byParity['even'].sort((a,b)=>a-b).join(',') !== '2,4,6') throw new Error('evens');
console.log('ok');
""",
            },
            {
                "id": "TSD_P2",
                "prompt": "Write a TypeScript function `pipe<T>(...fns: Array<(x: T) => T>): (x: T) => T` that applies functions left-to-right.",
                "test": r"""
const double = (x: number) => x * 2;
const addOne = (x: number) => x + 1;
const square = (x: number) => x * x;
const f = pipe(square, addOne, double);
if (f(3) !== 20) throw new Error(`expected 20 got ${f(3)}`);  // (3^2 + 1) * 2 = 20
if (f(0) !== 2) throw new Error(`expected 2 got ${f(0)}`);    // (0 + 1) * 2 = 2
console.log('ok');
""",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Harness — standalone runners
# ---------------------------------------------------------------------------

import re as _re
import shutil as _shutil


def _extract_code(raw: str) -> str:
    """Extract code from model response. Always prefers explicit code block extraction."""
    # Always try fenced block first — handles chatty base models that wrap code in ```lang\n...\n```
    m = _re.search(r"```(?:\w+)?\s*\n(.*?)```", raw, _re.DOTALL)
    if m:
        return _strip_fences(m.group(1).strip())
    # No fenced block found — try _strip_fences on the whole response (fine-tuned models)
    s = _strip_fences(raw)
    # Last resort: if prose still bleeds through (natural language before first blank line),
    # drop everything up to the first blank line and return the rest
    if _re.match(r"^[A-Za-z].*[^{}\[\]();]$", s.split("\n")[0]):
        lines = s.split("\n")
        for i, line in enumerate(lines):
            if not line.strip() and i < len(lines) - 1:
                return "\n".join(lines[i + 1 :]).strip()
    return s


def _run_rust(student: str, test_main: str) -> tuple[bool, str]:
    """Assemble: student functions + test fn main(), deduplicating declarations."""
    # If student wrote fn main(), truncate before it — test provides the real main
    m_main = _re.search(r"\bfn\s+main\s*\(", student)
    if m_main:
        student = student[: m_main.start()].rstrip()
    # Strip bare forward declarations: fn foo(...) -> T;  (no body — would conflict with student)
    test_clean = _re.sub(r"(?m)^\s*(?:pub\s+)?fn\s+\w+[^{;\n]*;\s*$\n?", "", test_main)
    # Remove struct/enum/type defs from test that student already defines (avoids "defined multiple times")
    for kw in ("struct", "enum", "type"):
        names = set(_re.findall(rf"(?m)^(?:pub\s+)?{kw}\s+(\w+)", student))
        for name in names:
            test_clean = _re.sub(
                rf"(?:pub\s+)?{kw}\s+{_re.escape(name)}\b[^;{{]*(?:\{{[^}}]*\}}|=[^;]*;)",
                "",
                test_clean,
            )
    full = student.strip() + "\n\n" + test_clean.strip()
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False, mode="w", encoding="utf-8") as f:
        f.write(full)
        src = f.name
    bin_path = src.replace(".rs", ".exe" if sys.platform == "win32" else ".bin")
    try:
        r = subprocess.run(
            ["rustc", "--edition", "2021", "-o", bin_path, src],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return False, r.stderr[:600]
        r2 = subprocess.run([bin_path], capture_output=True, text=True, timeout=10)
        return (r2.returncode == 0 and bool(r2.stdout.strip())), r2.stderr[:300]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except FileNotFoundError:
        return False, "rustc not found"
    finally:
        for p in (src, bin_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _run_go(student: str, test_harness: str) -> tuple[bool, str]:
    """
    Assemble a complete Go file.
    Harness provides: package main + imports + func main().
    Student provides: function/type implementations.
    """
    # --- clean student ---
    s = _re.sub(r"^\s*package\s+\w+\s*\n?", "", student.strip(), count=1)
    s = _re.sub(r"import\s*\(.*?\)\s*\n?", "", s, flags=_re.DOTALL)
    s = _re.sub(r'import\s+"[^"]+"\s*\n?', "", s)
    # Truncate at func main if student wrote one
    m_main = _re.search(r"\bfunc\s+main\s*\(", s)
    if m_main:
        s = s[: m_main.start()].rstrip()

    # --- clean harness ---
    h = test_harness
    # Strip bare forward declarations (func lines without '{' — invalid Go)
    h = _re.sub(r"(?m)^func\s+[^\n{]+$\n?", "", h)
    # Remove type definitions (struct/interface) that student already defines
    student_types = set(_re.findall(r"type\s+(\w+)", s))
    for name in student_types:
        # multi-line: type NAME struct/interface { ... }
        h = _re.sub(
            rf"type\s+{_re.escape(name)}\s+(?:struct|interface)\s*\{{[^}}]*\}}",
            "",
            h,
            flags=_re.DOTALL,
        )
        # single-line: type NAME OtherType
        h = _re.sub(rf"(?m)^type\s+{_re.escape(name)}\s+\w+\s*$\n?", "", h)

    full = h.strip() + "\n\n" + s.strip()
    with tempfile.NamedTemporaryFile(suffix=".go", delete=False, mode="w", encoding="utf-8") as f:
        f.write(full)
        src = f.name
    try:
        r = subprocess.run(["go", "run", src], capture_output=True, text=True, timeout=30)
        return (r.returncode == 0 and bool(r.stdout.strip())), (r.stderr or r.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except FileNotFoundError:
        return False, "go not found"
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass


def _run_python(student: str, test_code: str) -> tuple[bool, str]:
    full = student.strip() + "\n\n" + test_code.strip()
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
        f.write(full)
        src = f.name
    try:
        r = subprocess.run([sys.executable, src], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return True, ""
        return False, (r.stderr or r.stdout)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass


def _run_ts(student: str, test_code: str) -> tuple[bool, str]:
    full = student.strip() + "\n\n" + test_code.strip()
    tmpdir = tempfile.mkdtemp()
    src = os.path.join(tmpdir, "eval.ts")
    with open(src, "w", encoding="utf-8") as f:
        f.write(full)
    try:
        rc = subprocess.run(
            [
                "tsc",
                "--module",
                "commonjs",
                "--target",
                "ES2020",
                "--strict",
                "--skipLibCheck",
                "--outDir",
                tmpdir,
                src,
            ],
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
            timeout=30,
        )
        if rc.returncode != 0:
            return False, (rc.stderr or rc.stdout)[:500]
        r = subprocess.run(
            ["node", os.path.join(tmpdir, "eval.js")], capture_output=True, text=True, timeout=15
        )
        return (r.returncode == 0 and bool(r.stdout.strip())), (r.stderr or r.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def run_probe(code: str, probe: dict, lang: str) -> tuple[bool, str]:
    student = _extract_code(code)
    test = probe["test"]
    if lang == "rust":
        return _run_rust(student, test)
    if lang == "go":
        return _run_go(student, test)
    if lang == "python":
        return _run_python(student, test)
    if lang == "typescript":
        return _run_ts(student, test)
    return True, ""


def run_bench(model: str, save: bool = False):
    print(f"\n{'=' * 65}")
    print(f"  DETERMINEX FULL BENCH — {model}")
    print(f"  {len(BENCH_CONCEPTS)} concept groups | compiler-verified | HumanEval-comparable")
    print(f"{'=' * 65}")

    # Pre-warm
    print(f"\n  [pre-warm] Loading {model}...", end="", flush=True)
    ask_student(model, "You are an expert programmer.", "Say ok.")
    print(" ready.\n")

    results = []
    total_pass = total_fail = 0
    concept_scores = {}

    for concept_key, concept in BENCH_CONCEPTS.items():
        lang = concept["lang"]
        system = concept["system"]
        probes = concept["probes"]
        probe_results = []

        print(f"  ┌─ [{concept_key.upper()}]  ({lang})")
        for probe in probes:
            prompt = probe["prompt"]
            pid = probe["id"]

            t0 = time.time()
            code = ask_student(model, system, prompt) or ""
            ok, err = run_probe(code, probe, lang)
            elapsed = round(time.time() - t0, 1)

            status = "PASS" if ok else "FAIL"
            errstr = f"  {err[:80]}" if not ok else ""
            print(f"  │  [{pid}] {status} ({elapsed}s){errstr}")

            probe_results.append(ok)
            results.append(
                {
                    "concept": concept_key,
                    "probe_id": pid,
                    "lang": lang,
                    "passed": ok,
                    "error": err[:200] if not ok else "",
                    "elapsed": elapsed,
                }
            )

            if ok:
                total_pass += 1
            else:
                total_fail += 1

        p = sum(probe_results)
        t = len(probe_results)
        pct = round(100 * p / t)
        concept_scores[concept_key] = (p, t, pct)
        print(f"  └─ SCORE: {p}/{t} ({pct}%)\n")

    total = total_pass + total_fail
    overall_pct = round(100 * total_pass / total) if total else 0

    print(f"\n{'=' * 65}")
    print(f"  OVERALL: {total_pass}/{total} ({overall_pct}%)")
    print(f"{'=' * 65}")

    print(f"""
  FRONTIER COMPARISON:
    Claude Opus 4.7      ~95%   gap: {95 - overall_pct:+d}%
    Claude Sonnet 4.6    ~93%   gap: {93 - overall_pct:+d}%
    GPT-4o               ~90%   gap: {90 - overall_pct:+d}%
    Qwen2.5-Coder-7B     ~83%   gap: {83 - overall_pct:+d}%
    Qwen2.5-Coder-3B     ~75%   gap: {75 - overall_pct:+d}%
    Qwen2.5-Coder-1.5B   ~62%   gap: {62 - overall_pct:+d}%

  NOTE: This benchmark uses compiler-verified pass@1 across 4 languages.
  HumanEval is Python-only pass@1. Multi-language benchmarks are typically
  3-8% harder than single-language Python benchmarks at equivalent difficulty.
  Adjust comparison accordingly.
{"=" * 65}
""")

    if save:
        out = {
            "model": model,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "overall_pct": overall_pct,
            "total_pass": total_pass,
            "total": total,
            "concept_scores": {
                k: {"pass": v[0], "total": v[1], "pct": v[2]} for k, v in concept_scores.items()
            },
            "probes": results,
        }
        model_safe = model.replace(":", "_").replace("/", "_")
        out_path = Path(f"eval_fullbench_{model_safe}_{time.strftime('%Y%m%d_%H%M%S')}.json")
        out_path.write_text(json.dumps(out, indent=2))
        print(f"  Results saved → {out_path}")

    return overall_pct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Ollama model name")
    parser.add_argument("--save", action="store_true", help="Save results to JSON")
    args = parser.parse_args()
    run_bench(args.model, save=args.save)


if __name__ == "__main__":
    main()
