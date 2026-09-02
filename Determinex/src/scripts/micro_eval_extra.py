"""
micro_eval_extra.py — Extended concept set for Determinex corpus generation
36 new concepts across Rust, Go, Python, TypeScript (250 probes total new)
Import EXTRA_CONCEPTS and merge with CONCEPTS from micro_eval.py
"""

EXTRA_CONCEPTS = {
    # ── RUST ──────────────────────────────────────────────────────────────────
    "rust_hashmap": {
        "lang": "rust",
        "description": "HashMap<String,i32> word frequency counter",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "RHM_P1_basic",
                "label": "Count word frequencies",
                "lang": "rust",
                "fn_name": "word_count",
                "prompt": "Write a Rust function word_count(text: &str) -> std::collections::HashMap<String, i32> that splits the text on whitespace and counts how many times each word appears.",
                "test_harness": """
use std::collections::HashMap;
fn word_count(text: &str) -> HashMap<String, i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    let m = word_count("hello world hello");
    assert_eq!(m["hello"], 2);
    assert_eq!(m["world"], 1);
    let m2 = word_count("");
    assert!(m2.is_empty());
    println!("RHM_P1 PASS");
}
""",
            },
            {
                "id": "RHM_P2_contains",
                "label": "Key existence check with contains_key",
                "lang": "rust",
                "fn_name": "has_key",
                "prompt": "Write a Rust function has_key(map: &std::collections::HashMap<String,i32>, key: &str) -> bool that returns true if key exists in map.",
                "test_harness": """
use std::collections::HashMap;
fn has_key(map: &HashMap<String, i32>, key: &str) -> bool {
    // <<STUDENT_CODE>>
}
fn main() {
    let mut m = HashMap::new();
    m.insert("a".to_string(), 1);
    assert!(has_key(&m, "a"));
    assert!(!has_key(&m, "b"));
    println!("RHM_P2 PASS");
}
""",
            },
            {
                "id": "RHM_P3_entry",
                "label": "entry().or_insert() increment pattern",
                "lang": "rust",
                "fn_name": "increment_key",
                "prompt": "Write a Rust function increment_key(map: &mut std::collections::HashMap<String,i32>, key: &str) that increments the value for key by 1, inserting 0 first if key is absent.",
                "test_harness": """
use std::collections::HashMap;
fn increment_key(map: &mut HashMap<String, i32>, key: &str) {
    // <<STUDENT_CODE>>
}
fn main() {
    let mut m = HashMap::new();
    increment_key(&mut m, "x");
    assert_eq!(m["x"], 1);
    increment_key(&mut m, "x");
    assert_eq!(m["x"], 2);
    println!("RHM_P3 PASS");
}
""",
            },
            {
                "id": "RHM_P4_merge",
                "label": "Merge two HashMaps, summing values",
                "lang": "rust",
                "fn_name": "merge_counts",
                "prompt": "Write a Rust function merge_counts(a: std::collections::HashMap<String,i32>, b: std::collections::HashMap<String,i32>) -> std::collections::HashMap<String,i32> that returns a new map with keys from both, summing values for shared keys.",
                "test_harness": """
use std::collections::HashMap;
fn merge_counts(a: HashMap<String,i32>, b: HashMap<String,i32>) -> HashMap<String,i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    let mut a = HashMap::new(); a.insert("x".to_string(), 1); a.insert("y".to_string(), 2);
    let mut b = HashMap::new(); b.insert("x".to_string(), 3); b.insert("z".to_string(), 4);
    let m = merge_counts(a, b);
    assert_eq!(m["x"], 4);
    assert_eq!(m["y"], 2);
    assert_eq!(m["z"], 4);
    println!("RHM_P4 PASS");
}
""",
            },
            {
                "id": "RHM_P5_rename",
                "label": "Concept transfer: renamed to char_count",
                "lang": "rust",
                "fn_name": "char_count",
                "prompt": "Write a Rust function char_count(s: &str) -> std::collections::HashMap<char, usize> that counts how many times each character appears in s.",
                "test_harness": """
use std::collections::HashMap;
fn char_count(s: &str) -> HashMap<char, usize> {
    // <<STUDENT_CODE>>
}
fn main() {
    let m = char_count("aabb");
    assert_eq!(m[&'a'], 2);
    assert_eq!(m[&'b'], 2);
    assert!(!m.contains_key(&'c'));
    println!("RHM_P5 PASS");
}
""",
            },
        ],
    },
    "rust_option_chain": {
        "lang": "rust",
        "description": "Option chaining: map, and_then, unwrap_or",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "ROC_P1_map",
                "label": "Option::map to transform inner value",
                "lang": "rust",
                "fn_name": "double_if_some",
                "prompt": "Write a Rust function double_if_some(x: Option<i32>) -> Option<i32> that returns None if x is None, or Some(value * 2) if x is Some.",
                "test_harness": """
fn double_if_some(x: Option<i32>) -> Option<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(double_if_some(Some(3)), Some(6));
    assert_eq!(double_if_some(None), None);
    assert_eq!(double_if_some(Some(0)), Some(0));
    println!("ROC_P1 PASS");
}
""",
            },
            {
                "id": "ROC_P2_and_then",
                "label": "Option::and_then for chained fallible ops",
                "lang": "rust",
                "fn_name": "parse_and_double",
                "prompt": "Write a Rust function parse_and_double(s: &str) -> Option<i32> that parses s as i32, returning None on parse failure, or Some(n*2) on success.",
                "test_harness": """
fn parse_and_double(s: &str) -> Option<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(parse_and_double("5"), Some(10));
    assert_eq!(parse_and_double("abc"), None);
    assert_eq!(parse_and_double("-3"), Some(-6));
    println!("ROC_P2 PASS");
}
""",
            },
            {
                "id": "ROC_P3_unwrap_or",
                "label": "unwrap_or / unwrap_or_else default",
                "lang": "rust",
                "fn_name": "get_or_default",
                "prompt": "Write a Rust function get_or_default(x: Option<i32>, default: i32) -> i32 that returns the inner value if Some, or default if None.",
                "test_harness": """
fn get_or_default(x: Option<i32>, default: i32) -> i32 {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(get_or_default(Some(7), 0), 7);
    assert_eq!(get_or_default(None, 42), 42);
    assert_eq!(get_or_default(Some(0), 99), 0);
    println!("ROC_P3 PASS");
}
""",
            },
            {
                "id": "ROC_P4_filter",
                "label": "Option::filter conditional keep",
                "lang": "rust",
                "fn_name": "keep_positive",
                "prompt": "Write a Rust function keep_positive(x: Option<i32>) -> Option<i32> that returns None if x is None or if the value is <= 0, otherwise returns the value.",
                "test_harness": """
fn keep_positive(x: Option<i32>) -> Option<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(keep_positive(Some(5)), Some(5));
    assert_eq!(keep_positive(Some(-1)), None);
    assert_eq!(keep_positive(Some(0)), None);
    assert_eq!(keep_positive(None), None);
    println!("ROC_P4 PASS");
}
""",
            },
            {
                "id": "ROC_P5_chain",
                "label": "Chained Option operations",
                "lang": "rust",
                "fn_name": "first_positive_doubled",
                "prompt": "Write a Rust function first_positive_doubled(nums: &[i32]) -> Option<i32> that finds the first positive number (> 0) and returns it doubled, or None if none exists.",
                "test_harness": """
fn first_positive_doubled(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(first_positive_doubled(&[0, -1, 3, 5]), Some(6));
    assert_eq!(first_positive_doubled(&[-1, -2]), None);
    assert_eq!(first_positive_doubled(&[]), None);
    println!("ROC_P5 PASS");
}
""",
            },
        ],
    },
    "rust_result_chain": {
        "lang": "rust",
        "description": "Result<T,E> error propagation with ? operator",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "RRC_P1_question",
                "label": "? operator for early return on error",
                "lang": "rust",
                "fn_name": "parse_sum",
                "prompt": "Write a Rust function parse_sum(a: &str, b: &str) -> Result<i32, std::num::ParseIntError> that parses both strings as i32 and returns their sum, propagating any parse error with ?.",
                "test_harness": """
fn parse_sum(a: &str, b: &str) -> Result<i32, std::num::ParseIntError> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(parse_sum("3", "4").unwrap(), 7);
    assert!(parse_sum("x", "4").is_err());
    assert!(parse_sum("3", "y").is_err());
    println!("RRC_P1 PASS");
}
""",
            },
            {
                "id": "RRC_P2_map_err",
                "label": "map_err to convert error type",
                "lang": "rust",
                "fn_name": "parse_positive",
                "prompt": "Write a Rust function parse_positive(s: &str) -> Result<u32, String> that parses s as i32, returns Err(String) describing the parse failure, and also returns Err if the number is negative.",
                "test_harness": """
fn parse_positive(s: &str) -> Result<u32, String> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(parse_positive("5").unwrap(), 5u32);
    assert!(parse_positive("-1").is_err());
    assert!(parse_positive("abc").is_err());
    println!("RRC_P2 PASS");
}
""",
            },
            {
                "id": "RRC_P3_ok",
                "label": "Result::ok() to convert to Option",
                "lang": "rust",
                "fn_name": "try_parse",
                "prompt": "Write a Rust function try_parse(s: &str) -> Option<i32> that attempts to parse s as i32, returning Some(n) on success and None on failure.",
                "test_harness": """
fn try_parse(s: &str) -> Option<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(try_parse("42"), Some(42));
    assert_eq!(try_parse("bad"), None);
    assert_eq!(try_parse("-7"), Some(-7));
    println!("RRC_P3 PASS");
}
""",
            },
            {
                "id": "RRC_P4_chain",
                "label": "Chained Result with and_then",
                "lang": "rust",
                "fn_name": "parse_and_sqrt",
                "prompt": "Write a Rust function parse_and_sqrt(s: &str) -> Result<f64, String> that parses s as f64, returns Err if parse fails or if the number is negative, otherwise returns Ok(sqrt).",
                "test_harness": """
fn parse_and_sqrt(s: &str) -> Result<f64, String> {
    // <<STUDENT_CODE>>
}
fn main() {
    let r = parse_and_sqrt("4.0").unwrap();
    assert!((r - 2.0).abs() < 1e-9);
    assert!(parse_and_sqrt("-1").is_err());
    assert!(parse_and_sqrt("abc").is_err());
    println!("RRC_P4 PASS");
}
""",
            },
            {
                "id": "RRC_P5_collect",
                "label": "collect() into Result<Vec<_>, E>",
                "lang": "rust",
                "fn_name": "parse_all",
                "prompt": "Write a Rust function parse_all(items: &[&str]) -> Result<Vec<i32>, std::num::ParseIntError> that parses every string as i32, returning all values or the first parse error.",
                "test_harness": """
fn parse_all(items: &[&str]) -> Result<Vec<i32>, std::num::ParseIntError> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(parse_all(&["1","2","3"]).unwrap(), vec![1,2,3]);
    assert!(parse_all(&["1","x","3"]).is_err());
    assert_eq!(parse_all(&[]).unwrap(), vec![]);
    println!("RRC_P5 PASS");
}
""",
            },
        ],
    },
    "rust_struct_impl": {
        "lang": "rust",
        "description": "struct with impl block and methods",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the struct definition and impl block — no markdown fences, no preamble."
        ),
        "probes": [
            {
                "id": "RSI_P1_new",
                "label": "struct with new() constructor",
                "lang": "rust",
                "fn_name": "new",
                "prompt": "Write a Rust struct Counter with a single field count: u32, and an impl block with: new() -> Counter (count starts at 0), increment(&mut self), and value(&self) -> u32.",
                "test_harness": """
struct Counter {
    // <<STUDENT_CODE>>
}
fn main() {
    let mut c = Counter::new();
    assert_eq!(c.value(), 0);
    c.increment();
    c.increment();
    assert_eq!(c.value(), 2);
    println!("RSI_P1 PASS");
}
""",
            },
            {
                "id": "RSI_P2_methods",
                "label": "Rectangle struct with area and perimeter",
                "lang": "rust",
                "fn_name": "area",
                "prompt": "Write a Rust struct Rectangle with fields width: f64 and height: f64, and an impl block with: new(width: f64, height: f64) -> Rectangle, area(&self) -> f64, perimeter(&self) -> f64.",
                "test_harness": """
struct Rectangle {
    // <<STUDENT_CODE>>
}
fn main() {
    let r = Rectangle::new(3.0, 4.0);
    assert!((r.area() - 12.0).abs() < 1e-9);
    assert!((r.perimeter() - 14.0).abs() < 1e-9);
    println!("RSI_P2 PASS");
}
""",
            },
            {
                "id": "RSI_P3_default",
                "label": "impl Default for struct",
                "lang": "rust",
                "fn_name": "default",
                "prompt": "Write a Rust struct Config with fields debug: bool (default false) and max_retries: u32 (default 3), and impl Default for Config.",
                "test_harness": """
struct Config {
    // <<STUDENT_CODE>>
}
fn main() {
    let c = Config::default();
    assert!(!c.debug);
    assert_eq!(c.max_retries, 3);
    println!("RSI_P3 PASS");
}
""",
            },
            {
                "id": "RSI_P4_builder",
                "label": "Builder pattern with method chaining",
                "lang": "rust",
                "fn_name": "build",
                "prompt": 'Write a Rust struct QueryBuilder with field table: String and an impl with: new() -> QueryBuilder (table = empty string), table(mut self, t: &str) -> QueryBuilder (sets table and returns self), build(&self) -> String (returns "SELECT * FROM {table}").',
                "test_harness": """
struct QueryBuilder {
    // <<STUDENT_CODE>>
}
fn main() {
    let q = QueryBuilder::new().table("users").build();
    assert_eq!(q, "SELECT * FROM users");
    println!("RSI_P4 PASS");
}
""",
            },
            {
                "id": "RSI_P5_display",
                "label": "impl Display for struct",
                "lang": "rust",
                "fn_name": "fmt",
                "prompt": 'Write a Rust struct Point with fields x: f64 and y: f64, and impl std::fmt::Display for Point so that format!("{}", p) produces "(x, y)" with 2 decimal places.',
                "test_harness": """
use std::fmt;
struct Point {
    x: f64,
    y: f64,
}
impl fmt::Display for Point {
    // <<STUDENT_CODE>>
}
fn main() {
    let p = Point { x: 1.5, y: -2.0 };
    assert_eq!(format!("{}", p), "(1.50, -2.00)");
    println!("RSI_P5 PASS");
}
""",
            },
        ],
    },
    "rust_enum_match": {
        "lang": "rust",
        "description": "enum with data variants and pattern matching",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the enum/function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "REM_P1_basic",
                "label": "Match on simple enum",
                "lang": "rust",
                "fn_name": "describe_direction",
                "prompt": 'Write a Rust enum Direction with variants North, South, East, West. Write a function describe_direction(d: Direction) -> &\'static str that returns "north", "south", "east", or "west".',
                "test_harness": """
enum Direction { North, South, East, West }
fn describe_direction(d: Direction) -> &'static str {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(describe_direction(Direction::North), "north");
    assert_eq!(describe_direction(Direction::South), "south");
    assert_eq!(describe_direction(Direction::East), "east");
    assert_eq!(describe_direction(Direction::West), "west");
    println!("REM_P1 PASS");
}
""",
            },
            {
                "id": "REM_P2_data",
                "label": "Enum with data variants",
                "lang": "rust",
                "fn_name": "area",
                "prompt": "Write a Rust enum Shape with variants Circle(f64) for radius and Rectangle(f64, f64) for width and height. Write fn area(s: Shape) -> f64 using std::f64::consts::PI for circles.",
                "test_harness": """
use std::f64::consts::PI;
enum Shape { Circle(f64), Rectangle(f64, f64) }
fn area(s: Shape) -> f64 {
    // <<STUDENT_CODE>>
}
fn main() {
    assert!((area(Shape::Circle(1.0)) - PI).abs() < 1e-9);
    assert!((area(Shape::Rectangle(3.0, 4.0)) - 12.0).abs() < 1e-9);
    println!("REM_P2 PASS");
}
""",
            },
            {
                "id": "REM_P3_option_like",
                "label": "Custom Option-like enum",
                "lang": "rust",
                "fn_name": "unwrap_or",
                "prompt": "Write a Rust enum Maybe<T> with variants Just(T) and Nothing. Write fn unwrap_or<T>(m: Maybe<T>, default: T) -> T.",
                "test_harness": """
enum Maybe<T> { Just(T), Nothing }
fn unwrap_or<T>(m: Maybe<T>, default: T) -> T {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(unwrap_or(Maybe::Just(5), 0), 5);
    assert_eq!(unwrap_or(Maybe::Nothing, 99), 99);
    println!("REM_P3 PASS");
}
""",
            },
            {
                "id": "REM_P4_nested",
                "label": "Nested match with guard",
                "lang": "rust",
                "fn_name": "classify_temp",
                "prompt": 'Write a Rust function classify_temp(celsius: f64) -> &\'static str that returns "freezing" if < 0, "cold" if 0..15, "comfortable" if 15..25, "hot" if >= 25.',
                "test_harness": """
fn classify_temp(celsius: f64) -> &'static str {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(classify_temp(-5.0), "freezing");
    assert_eq!(classify_temp(0.0), "cold");
    assert_eq!(classify_temp(10.0), "cold");
    assert_eq!(classify_temp(20.0), "comfortable");
    assert_eq!(classify_temp(30.0), "hot");
    println!("REM_P4 PASS");
}
""",
            },
            {
                "id": "REM_P5_if_let",
                "label": "if let destructuring",
                "lang": "rust",
                "fn_name": "first_name",
                "prompt": "Write a Rust function first_name(names: &[Option<&str>]) -> Option<&str> that returns the first Some value in the slice, or None if all are None.",
                "test_harness": """
fn first_name<'a>(names: &[Option<&'a str>]) -> Option<&'a str> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(first_name(&[None, Some("Alice"), Some("Bob")]), Some("Alice"));
    assert_eq!(first_name(&[None, None]), None);
    assert_eq!(first_name(&[Some("X")]), Some("X"));
    println!("REM_P5 PASS");
}
""",
            },
        ],
    },
    "rust_iter_collect": {
        "lang": "rust",
        "description": "Iterator chains: filter, map, flat_map, collect",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "RIC_P1_filter_map",
                "label": "filter then map",
                "lang": "rust",
                "fn_name": "evens_doubled",
                "prompt": "Write a Rust function evens_doubled(nums: &[i32]) -> Vec<i32> that returns only the even numbers from nums, each multiplied by 2.",
                "test_harness": """
fn evens_doubled(nums: &[i32]) -> Vec<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(evens_doubled(&[1,2,3,4,5,6]), vec![4,8,12]);
    assert_eq!(evens_doubled(&[1,3,5]), vec![]);
    assert_eq!(evens_doubled(&[]), vec![]);
    println!("RIC_P1 PASS");
}
""",
            },
            {
                "id": "RIC_P2_flat_map",
                "label": "flat_map to flatten nested",
                "lang": "rust",
                "fn_name": "flatten_words",
                "prompt": "Write a Rust function flatten_words(sentences: &[&str]) -> Vec<String> that splits each sentence on whitespace and collects all words into one flat Vec.",
                "test_harness": """
fn flatten_words(sentences: &[&str]) -> Vec<String> {
    // <<STUDENT_CODE>>
}
fn main() {
    let r = flatten_words(&["hello world", "foo bar"]);
    assert_eq!(r, vec!["hello","world","foo","bar"]);
    assert_eq!(flatten_words(&[]), Vec::<String>::new());
    println!("RIC_P2 PASS");
}
""",
            },
            {
                "id": "RIC_P3_chain",
                "label": "chain two iterators",
                "lang": "rust",
                "fn_name": "concat_vecs",
                "prompt": "Write a Rust function concat_vecs(a: &[i32], b: &[i32]) -> Vec<i32> that returns all elements of a followed by all elements of b.",
                "test_harness": """
fn concat_vecs(a: &[i32], b: &[i32]) -> Vec<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(concat_vecs(&[1,2], &[3,4]), vec![1,2,3,4]);
    assert_eq!(concat_vecs(&[], &[1]), vec![1]);
    assert_eq!(concat_vecs(&[1], &[]), vec![1]);
    println!("RIC_P3 PASS");
}
""",
            },
            {
                "id": "RIC_P4_enumerate",
                "label": "enumerate to get (index, value)",
                "lang": "rust",
                "fn_name": "index_of_first_negative",
                "prompt": "Write a Rust function index_of_first_negative(nums: &[i32]) -> Option<usize> that returns the index of the first negative number, or None.",
                "test_harness": """
fn index_of_first_negative(nums: &[i32]) -> Option<usize> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(index_of_first_negative(&[1,2,-3,4]), Some(2));
    assert_eq!(index_of_first_negative(&[1,2,3]), None);
    assert_eq!(index_of_first_negative(&[-1,2,3]), Some(0));
    println!("RIC_P4 PASS");
}
""",
            },
            {
                "id": "RIC_P5_fold",
                "label": "fold to accumulate",
                "lang": "rust",
                "fn_name": "product",
                "prompt": "Write a Rust function product(nums: &[i64]) -> i64 that returns the product of all numbers (return 1 for empty slice).",
                "test_harness": """
fn product(nums: &[i64]) -> i64 {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(product(&[1,2,3,4]), 24);
    assert_eq!(product(&[]), 1);
    assert_eq!(product(&[5]), 5);
    assert_eq!(product(&[-2,3]), -6);
    println!("RIC_P5 PASS");
}
""",
            },
        ],
    },
    "rust_string_ops": {
        "lang": "rust",
        "description": "String manipulation: split, trim, contains, replace",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "RSO_P1_split_collect",
                "label": "split on delimiter, collect to Vec",
                "lang": "rust",
                "fn_name": "csv_fields",
                "prompt": "Write a Rust function csv_fields(line: &str) -> Vec<&str> that splits line on ',' and returns the parts as a Vec<&str>.",
                "test_harness": """
fn csv_fields(line: &str) -> Vec<&str> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(csv_fields("a,b,c"), vec!["a","b","c"]);
    assert_eq!(csv_fields("only"), vec!["only"]);
    assert_eq!(csv_fields(""), vec![""]);
    println!("RSO_P1 PASS");
}
""",
            },
            {
                "id": "RSO_P2_trim",
                "label": "trim whitespace from each line",
                "lang": "rust",
                "fn_name": "trim_lines",
                "prompt": "Write a Rust function trim_lines(text: &str) -> Vec<String> that splits text on newlines and returns each line with leading/trailing whitespace removed, skipping empty lines.",
                "test_harness": """
fn trim_lines(text: &str) -> Vec<String> {
    // <<STUDENT_CODE>>
}
fn main() {
    let r = trim_lines("  hello  \n  world  \n\n  foo  ");
    assert_eq!(r, vec!["hello","world","foo"]);
    assert_eq!(trim_lines(""), Vec::<String>::new());
    println!("RSO_P2 PASS");
}
""",
            },
            {
                "id": "RSO_P3_contains_starts",
                "label": "contains and starts_with",
                "lang": "rust",
                "fn_name": "is_http_url",
                "prompt": 'Write a Rust function is_http_url(s: &str) -> bool that returns true if s starts with "http://" or "https://".',
                "test_harness": """
fn is_http_url(s: &str) -> bool {
    // <<STUDENT_CODE>>
}
fn main() {
    assert!(is_http_url("http://example.com"));
    assert!(is_http_url("https://example.com"));
    assert!(!is_http_url("ftp://example.com"));
    assert!(!is_http_url("example.com"));
    println!("RSO_P3 PASS");
}
""",
            },
            {
                "id": "RSO_P4_replace",
                "label": "String replace and to_uppercase",
                "lang": "rust",
                "fn_name": "normalize",
                "prompt": "Write a Rust function normalize(s: &str) -> String that replaces all '-' with '_' and converts to lowercase.",
                "test_harness": """
fn normalize(s: &str) -> String {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(normalize("Hello-World"), "hello_world");
    assert_eq!(normalize("FOO-BAR-BAZ"), "foo_bar_baz");
    assert_eq!(normalize("already"), "already");
    println!("RSO_P4 PASS");
}
""",
            },
            {
                "id": "RSO_P5_join",
                "label": "join Vec<String> with separator",
                "lang": "rust",
                "fn_name": "join_with",
                "prompt": "Write a Rust function join_with(parts: &[String], sep: &str) -> String that joins all parts with sep between them.",
                "test_harness": """
fn join_with(parts: &[String], sep: &str) -> String {
    // <<STUDENT_CODE>>
}
fn main() {
    let parts: Vec<String> = vec!["a".into(),"b".into(),"c".into()];
    assert_eq!(join_with(&parts, ", "), "a, b, c");
    assert_eq!(join_with(&[], ", "), "");
    let single: Vec<String> = vec!["only".into()];
    assert_eq!(join_with(&single, "-"), "only");
    println!("RSO_P5 PASS");
}
""",
            },
        ],
    },
    "rust_vec_ops": {
        "lang": "rust",
        "description": "Vec operations: sort, dedup, retain, partition",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "RVO_P1_sort_dedup",
                "label": "sort and dedup",
                "lang": "rust",
                "fn_name": "sorted_unique",
                "prompt": "Write a Rust function sorted_unique(nums: Vec<i32>) -> Vec<i32> that returns a sorted, deduplicated version of the input.",
                "test_harness": """
fn sorted_unique(nums: Vec<i32>) -> Vec<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(sorted_unique(vec![3,1,2,1,3]), vec![1,2,3]);
    assert_eq!(sorted_unique(vec![]), vec![]);
    assert_eq!(sorted_unique(vec![5,5,5]), vec![5]);
    println!("RVO_P1 PASS");
}
""",
            },
            {
                "id": "RVO_P2_retain",
                "label": "retain to filter in-place",
                "lang": "rust",
                "fn_name": "remove_negatives",
                "prompt": "Write a Rust function remove_negatives(nums: &mut Vec<i32>) that removes all negative numbers from the Vec in-place.",
                "test_harness": """
fn remove_negatives(nums: &mut Vec<i32>) {
    // <<STUDENT_CODE>>
}
fn main() {
    let mut v = vec![1, -2, 3, -4, 5];
    remove_negatives(&mut v);
    assert_eq!(v, vec![1,3,5]);
    let mut empty: Vec<i32> = vec![];
    remove_negatives(&mut empty);
    assert_eq!(empty, vec![]);
    println!("RVO_P2 PASS");
}
""",
            },
            {
                "id": "RVO_P3_partition",
                "label": "partition into two Vecs",
                "lang": "rust",
                "fn_name": "split_evens_odds",
                "prompt": "Write a Rust function split_evens_odds(nums: Vec<i32>) -> (Vec<i32>, Vec<i32>) that returns (evens, odds) preserving original order.",
                "test_harness": """
fn split_evens_odds(nums: Vec<i32>) -> (Vec<i32>, Vec<i32>) {
    // <<STUDENT_CODE>>
}
fn main() {
    let (e, o) = split_evens_odds(vec![1,2,3,4,5,6]);
    assert_eq!(e, vec![2,4,6]);
    assert_eq!(o, vec![1,3,5]);
    let (e2, o2) = split_evens_odds(vec![]);
    assert!(e2.is_empty() && o2.is_empty());
    println!("RVO_P3 PASS");
}
""",
            },
            {
                "id": "RVO_P4_windows",
                "label": "windows() for sliding pairs",
                "lang": "rust",
                "fn_name": "max_consecutive_sum",
                "prompt": "Write a Rust function max_consecutive_sum(nums: &[i32]) -> Option<i32> that returns the maximum sum of any two consecutive elements, or None if fewer than 2 elements.",
                "test_harness": """
fn max_consecutive_sum(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(max_consecutive_sum(&[1,3,2,4]), Some(6));
    assert_eq!(max_consecutive_sum(&[1]), None);
    assert_eq!(max_consecutive_sum(&[]), None);
    assert_eq!(max_consecutive_sum(&[-1,-2,-3]), Some(-3));
    println!("RVO_P4 PASS");
}
""",
            },
            {
                "id": "RVO_P5_chunks",
                "label": "chunks() to batch process",
                "lang": "rust",
                "fn_name": "chunk_sums",
                "prompt": "Write a Rust function chunk_sums(nums: &[i32], size: usize) -> Vec<i32> that returns the sum of each chunk of `size` elements.",
                "test_harness": """
fn chunk_sums(nums: &[i32], size: usize) -> Vec<i32> {
    // <<STUDENT_CODE>>
}
fn main() {
    assert_eq!(chunk_sums(&[1,2,3,4,5,6], 2), vec![3,7,11]);
    assert_eq!(chunk_sums(&[1,2,3,4,5], 3), vec![6,9]);
    assert_eq!(chunk_sums(&[], 2), vec![]);
    println!("RVO_P5 PASS");
}
""",
            },
        ],
    },
    # ── GO ────────────────────────────────────────────────────────────────────
    "go_interface": {
        "lang": "go",
        "description": "Define and implement a Go interface",
        "system": (
            "You are an expert Go programmer. Write idiomatic, clean Go. "
            "Output ONLY the Go function/type — no package declaration, no imports, no markdown fences."
        ),
        "probes": [
            {
                "id": "GIF_P1_basic",
                "label": "Implement Stringer interface",
                "lang": "go",
                "fn_name": "String",
                "prompt": 'Write a Go struct Dog with field Name string, and implement the fmt.Stringer interface so String() returns "Dog: {Name}".',
                "test_harness": """package main
import "fmt"
type Dog struct {
    Name string
}
func (d Dog) String() string {
    // <<STUDENT_CODE>>
}
func main() {
    d := Dog{Name: "Rex"}
    if fmt.Sprintf("%v", d) != "Dog: Rex" { panic("wrong String()") }
    fmt.Println("GIF_P1 PASS")
}
""",
            },
            {
                "id": "GIF_P2_interface_impl",
                "label": "Struct implements custom interface",
                "lang": "go",
                "fn_name": "Area",
                "prompt": "Write a Go struct Circle with field Radius float64, and implement an Area() float64 method using math.Pi.",
                "test_harness": """package main
import (
    "fmt"
    "math"
)
type Circle struct {
    Radius float64
}
func (c Circle) Area() float64 {
    // <<STUDENT_CODE>>
}
func main() {
    c := Circle{Radius: 1.0}
    if math.Abs(c.Area()-math.Pi) > 1e-9 { panic("wrong area") }
    fmt.Println("GIF_P2 PASS")
}
""",
            },
            {
                "id": "GIF_P3_polymorphism",
                "label": "Interface used polymorphically",
                "lang": "go",
                "fn_name": "total_area",
                "prompt": "Given interface Shaper with method Area() float64, write a Go function total_area(shapes []Shaper) float64 that returns the sum of all areas.",
                "test_harness": """package main
import "fmt"
type Shaper interface { Area() float64 }
type Rect struct{ W, H float64 }
func (r Rect) Area() float64 { return r.W * r.H }
func total_area(shapes []Shaper) float64 {
    // <<STUDENT_CODE>>
}
func main() {
    shapes := []Shaper{Rect{3,4}, Rect{2,5}}
    if total_area(shapes) != 22.0 { panic("wrong total") }
    if total_area([]Shaper{}) != 0.0 { panic("empty failed") }
    fmt.Println("GIF_P3 PASS")
}
""",
            },
            {
                "id": "GIF_P4_error_interface",
                "label": "Custom error type implementing error interface",
                "lang": "go",
                "fn_name": "Error",
                "prompt": 'Write a Go struct ValidationError with fields Field string and Message string, and implement the error interface so Error() returns "{Field}: {Message}".',
                "test_harness": """package main
import "fmt"
type ValidationError struct {
    Field   string
    Message string
}
func (e *ValidationError) Error() string {
    // <<STUDENT_CODE>>
}
func main() {
    err := &ValidationError{Field: "email", Message: "invalid format"}
    if err.Error() != "email: invalid format" { panic("wrong error") }
    fmt.Println("GIF_P4 PASS")
}
""",
            },
            {
                "id": "GIF_P5_type_assert",
                "label": "Type assertion from interface",
                "lang": "go",
                "fn_name": "get_int_value",
                "prompt": "Write a Go function get_int_value(v interface{}) (int, bool) that returns the int value and true if v holds an int, otherwise 0 and false.",
                "test_harness": """package main
import "fmt"
func get_int_value(v interface{}) (int, bool) {
    // <<STUDENT_CODE>>
}
func main() {
    n, ok := get_int_value(42)
    if !ok || n != 42 { panic("int failed") }
    _, ok2 := get_int_value("hello")
    if ok2 { panic("string should fail") }
    fmt.Println("GIF_P5 PASS")
}
""",
            },
        ],
    },
    "go_map_ops": {
        "lang": "go",
        "description": "Go map operations: create, access, ok-idiom, delete",
        "system": (
            "You are an expert Go programmer. Write idiomatic, clean Go. "
            "Output ONLY the Go function — no package declaration, no imports, no markdown fences."
        ),
        "probes": [
            {
                "id": "GMO_P1_freq",
                "label": "Character frequency map",
                "lang": "go",
                "fn_name": "charFrequency",
                "prompt": "Write a Go function charFrequency(s string) map[rune]int that counts how many times each rune appears in s.",
                "test_harness": """package main
import "fmt"
func charFrequency(s string) map[rune]int {
    // <<STUDENT_CODE>>
}
func main() {
    m := charFrequency("hello")
    if m['l'] != 2 { panic("l count wrong") }
    if m['h'] != 1 { panic("h count wrong") }
    if charFrequency("")[' '] != 0 { panic("empty failed") }
    fmt.Println("GMO_P1 PASS")
}
""",
            },
            {
                "id": "GMO_P2_ok_idiom",
                "label": "ok-idiom for safe map access",
                "lang": "go",
                "fn_name": "getOrDefault",
                "prompt": "Write a Go function getOrDefault(m map[string]int, key string, def int) int that returns the value for key if present, otherwise def.",
                "test_harness": """package main
import "fmt"
func getOrDefault(m map[string]int, key string, def int) int {
    // <<STUDENT_CODE>>
}
func main() {
    m := map[string]int{"a": 1, "b": 2}
    if getOrDefault(m, "a", 0) != 1 { panic("existing key failed") }
    if getOrDefault(m, "z", 99) != 99 { panic("missing key failed") }
    fmt.Println("GMO_P2 PASS")
}
""",
            },
            {
                "id": "GMO_P3_invert",
                "label": "Invert a map (swap keys and values)",
                "lang": "go",
                "fn_name": "invertMap",
                "prompt": "Write a Go function invertMap(m map[string]string) map[string]string that swaps keys and values.",
                "test_harness": """package main
import "fmt"
func invertMap(m map[string]string) map[string]string {
    // <<STUDENT_CODE>>
}
func main() {
    m := map[string]string{"a": "1", "b": "2"}
    inv := invertMap(m)
    if inv["1"] != "a" { panic("invert failed") }
    if inv["2"] != "b" { panic("invert failed") }
    fmt.Println("GMO_P3 PASS")
}
""",
            },
            {
                "id": "GMO_P4_group_by",
                "label": "Group slice elements by key",
                "lang": "go",
                "fn_name": "groupByLength",
                "prompt": "Write a Go function groupByLength(words []string) map[int][]string that groups words by their length.",
                "test_harness": """package main
import (
    "fmt"
    "sort"
)
func groupByLength(words []string) map[int][]string {
    // <<STUDENT_CODE>>
}
func main() {
    m := groupByLength([]string{"cat", "dog", "bear", "ant"})
    sort.Strings(m[3])
    if fmt.Sprintf("%v", m[3]) != "[ant cat dog]" { panic("len 3 wrong") }
    if fmt.Sprintf("%v", m[4]) != "[bear]" { panic("len 4 wrong") }
    fmt.Println("GMO_P4 PASS")
}
""",
            },
            {
                "id": "GMO_P5_filter",
                "label": "Filter map by value predicate",
                "lang": "go",
                "fn_name": "filterPositive",
                "prompt": "Write a Go function filterPositive(m map[string]int) map[string]int that returns a new map containing only entries where the value is > 0.",
                "test_harness": """package main
import "fmt"
func filterPositive(m map[string]int) map[string]int {
    // <<STUDENT_CODE>>
}
func main() {
    m := map[string]int{"a": 1, "b": -1, "c": 0, "d": 5}
    r := filterPositive(m)
    if r["a"] != 1 || r["d"] != 5 { panic("positive values missing") }
    if _, ok := r["b"]; ok { panic("negative should be excluded") }
    if _, ok := r["c"]; ok { panic("zero should be excluded") }
    fmt.Println("GMO_P5 PASS")
}
""",
            },
        ],
    },
    "go_slice_ops": {
        "lang": "go",
        "description": "Go slice operations: append, copy, filter, reverse",
        "system": (
            "You are an expert Go programmer. Write idiomatic, clean Go. "
            "Output ONLY the Go function — no package declaration, no imports, no markdown fences."
        ),
        "probes": [
            {
                "id": "GSO_P1_filter",
                "label": "Filter slice by predicate",
                "lang": "go",
                "fn_name": "filterEven",
                "prompt": "Write a Go function filterEven(nums []int) []int that returns a new slice containing only the even numbers.",
                "test_harness": """package main
import "fmt"
func filterEven(nums []int) []int {
    // <<STUDENT_CODE>>
}
func main() {
    r := filterEven([]int{1,2,3,4,5,6})
    if fmt.Sprintf("%v", r) != "[2 4 6]" { panic("wrong result") }
    if len(filterEven([]int{})) != 0 { panic("empty failed") }
    fmt.Println("GSO_P1 PASS")
}
""",
            },
            {
                "id": "GSO_P2_reverse",
                "label": "Reverse a slice in-place",
                "lang": "go",
                "fn_name": "reverseInts",
                "prompt": "Write a Go function reverseInts(nums []int) that reverses the slice in-place.",
                "test_harness": """package main
import "fmt"
func reverseInts(nums []int) {
    // <<STUDENT_CODE>>
}
func main() {
    s := []int{1,2,3,4,5}
    reverseInts(s)
    if fmt.Sprintf("%v", s) != "[5 4 3 2 1]" { panic("wrong reverse") }
    empty := []int{}
    reverseInts(empty)
    fmt.Println("GSO_P2 PASS")
}
""",
            },
            {
                "id": "GSO_P3_unique",
                "label": "Remove duplicates preserving order",
                "lang": "go",
                "fn_name": "uniqueInts",
                "prompt": "Write a Go function uniqueInts(nums []int) []int that returns a new slice with duplicates removed, preserving first-occurrence order.",
                "test_harness": """package main
import "fmt"
func uniqueInts(nums []int) []int {
    // <<STUDENT_CODE>>
}
func main() {
    r := uniqueInts([]int{1,2,2,3,1,4})
    if fmt.Sprintf("%v", r) != "[1 2 3 4]" { panic("wrong unique") }
    if len(uniqueInts([]int{})) != 0 { panic("empty failed") }
    fmt.Println("GSO_P3 PASS")
}
""",
            },
            {
                "id": "GSO_P4_chunk",
                "label": "Chunk slice into groups of n",
                "lang": "go",
                "fn_name": "chunkBy",
                "prompt": "Write a Go function chunkBy(nums []int, size int) [][]int that splits nums into consecutive sub-slices of at most size elements.",
                "test_harness": """package main
import "fmt"
func chunkBy(nums []int, size int) [][]int {
    // <<STUDENT_CODE>>
}
func main() {
    r := chunkBy([]int{1,2,3,4,5}, 2)
    if len(r) != 3 { panic("wrong chunk count") }
    if fmt.Sprintf("%v", r[0]) != "[1 2]" { panic("chunk 0 wrong") }
    if fmt.Sprintf("%v", r[2]) != "[5]" { panic("chunk 2 wrong") }
    fmt.Println("GSO_P4 PASS")
}
""",
            },
            {
                "id": "GSO_P5_flatten",
                "label": "Flatten [][]int to []int",
                "lang": "go",
                "fn_name": "flatten",
                "prompt": "Write a Go function flatten(matrix [][]int) []int that concatenates all inner slices into a single flat slice.",
                "test_harness": """package main
import "fmt"
func flatten(matrix [][]int) []int {
    // <<STUDENT_CODE>>
}
func main() {
    r := flatten([][]int{{1,2},{3,4},{5}})
    if fmt.Sprintf("%v", r) != "[1 2 3 4 5]" { panic("wrong flatten") }
    if len(flatten([][]int{})) != 0 { panic("empty failed") }
    fmt.Println("GSO_P5 PASS")
}
""",
            },
        ],
    },
    "go_defer_cleanup": {
        "lang": "go",
        "description": "defer for cleanup and LIFO execution order",
        "system": (
            "You are an expert Go programmer. Write idiomatic, clean Go. "
            "Output ONLY the Go function — no package declaration, no imports, no markdown fences."
        ),
        "probes": [
            {
                "id": "GDC_P1_basic",
                "label": "defer runs after function returns",
                "lang": "go",
                "fn_name": "withCleanup",
                "prompt": 'Write a Go function withCleanup(log *[]string) that appends "start" to log, defers appending "cleanup", then appends "work". The deferred call must run after the appends.',
                "test_harness": """package main
import "fmt"
func withCleanup(log *[]string) {
    // <<STUDENT_CODE>>
}
func main() {
    var log []string
    withCleanup(&log)
    if len(log) != 3 { panic("wrong log length") }
    if log[0] != "start" || log[1] != "work" || log[2] != "cleanup" {
        panic(fmt.Sprintf("wrong order: %v", log))
    }
    fmt.Println("GDC_P1 PASS")
}
""",
            },
            {
                "id": "GDC_P2_lifo",
                "label": "Multiple defers run in LIFO order",
                "lang": "go",
                "fn_name": "lifoOrder",
                "prompt": 'Write a Go function lifoOrder() []string that defers appending "first", "second", "third" in that order, then returns the log. Defers must execute in reverse (LIFO) order.',
                "test_harness": """package main
import "fmt"
func lifoOrder() []string {
    // <<STUDENT_CODE>>
}
func main() {
    r := lifoOrder()
    if fmt.Sprintf("%v", r) != "[third second first]" {
        panic(fmt.Sprintf("wrong LIFO: %v", r))
    }
    fmt.Println("GDC_P2 PASS")
}
""",
            },
            {
                "id": "GDC_P3_panic_recover",
                "label": "defer + recover from panic",
                "lang": "go",
                "fn_name": "safeCall",
                "prompt": "Write a Go function safeCall(fn func()) (recovered bool) that calls fn() and recovers from any panic, returning true if a panic occurred.",
                "test_harness": """package main
import "fmt"
func safeCall(fn func()) (recovered bool) {
    // <<STUDENT_CODE>>
}
func main() {
    ok := safeCall(func() { panic("boom") })
    if !ok { panic("should have recovered") }
    notOk := safeCall(func() {})
    if notOk { panic("no panic should return false") }
    fmt.Println("GDC_P3 PASS")
}
""",
            },
            {
                "id": "GDC_P4_error_annotate",
                "label": "defer to annotate named return error",
                "lang": "go",
                "fn_name": "riskyOp",
                "prompt": 'Write a Go function riskyOp(fail bool) (err error) that uses a deferred function to wrap the returned error with "riskyOp: " prefix if err is non-nil. If fail is true, set err to errors.New("base error").',
                "test_harness": """package main
import (
    "errors"
    "fmt"
    "strings"
)
func riskyOp(fail bool) (err error) {
    // <<STUDENT_CODE>>
}
func main() {
    err := riskyOp(true)
    if err == nil { panic("expected error") }
    if !strings.HasPrefix(err.Error(), "riskyOp: ") { panic("missing prefix: " + err.Error()) }
    if riskyOp(false) != nil { panic("non-fail should return nil") }
    fmt.Println("GDC_P4 PASS")
}
""",
            },
            {
                "id": "GDC_P5_rename",
                "label": "Concept transfer: resource tracking",
                "lang": "go",
                "fn_name": "trackResource",
                "prompt": "Write a Go function trackResource(name string, active *[]string) func() that appends name to active and returns a cleanup func that removes it from active.",
                "test_harness": """package main
import "fmt"
func trackResource(name string, active *[]string) func() {
    // <<STUDENT_CODE>>
}
func main() {
    var active []string
    cleanup := trackResource("db", &active)
    if len(active) != 1 || active[0] != "db" { panic("not added") }
    cleanup()
    if len(active) != 0 { panic("not removed") }
    fmt.Println("GDC_P5 PASS")
}
""",
            },
        ],
    },
    "go_context_cancel": {
        "lang": "go",
        "description": "context.WithTimeout and WithCancel for cancellation",
        "system": (
            "You are an expert Go programmer. Write idiomatic, clean Go. "
            "Output ONLY the Go function — no package declaration, no imports, no markdown fences."
        ),
        "probes": [
            {
                "id": "GCC_P1_done_check",
                "label": "Check context.Done() channel",
                "lang": "go",
                "fn_name": "workerWithCtx",
                "prompt": "Write a Go function workerWithCtx(ctx context.Context, results chan<- int, n int) that sends integers 0..n-1 to results, stopping early if ctx.Done() is closed before each send.",
                "test_harness": """package main
import (
    "context"
    "fmt"
)
func workerWithCtx(ctx context.Context, results chan<- int, n int) {
    // <<STUDENT_CODE>>
}
func main() {
    ctx := context.Background()
    ch := make(chan int, 5)
    workerWithCtx(ctx, ch, 3)
    close(ch)
    var got []int
    for v := range ch { got = append(got, v) }
    if fmt.Sprintf("%v", got) != "[0 1 2]" { panic(fmt.Sprintf("wrong: %v", got)) }
    fmt.Println("GCC_P1 PASS")
}
""",
            },
            {
                "id": "GCC_P2_timeout",
                "label": "context.WithTimeout cancels slow work",
                "lang": "go",
                "fn_name": "runWithTimeout",
                "prompt": "Write a Go function runWithTimeout(timeout time.Duration, work func(context.Context) error) error that runs work with a context that times out after timeout, returning context.DeadlineExceeded if it times out.",
                "test_harness": """package main
import (
    "context"
    "errors"
    "fmt"
    "time"
)
func runWithTimeout(timeout time.Duration, work func(context.Context) error) error {
    // <<STUDENT_CODE>>
}
func main() {
    fast := func(ctx context.Context) error { return nil }
    if err := runWithTimeout(time.Second, fast); err != nil { panic("fast should not error") }
    slow := func(ctx context.Context) error {
        select {
        case <-ctx.Done(): return ctx.Err()
        case <-time.After(10 * time.Second): return nil
        }
    }
    err := runWithTimeout(10*time.Millisecond, slow)
    if !errors.Is(err, context.DeadlineExceeded) { panic("should timeout") }
    fmt.Println("GCC_P2 PASS")
}
""",
            },
            {
                "id": "GCC_P3_cancel",
                "label": "WithCancel — manual cancel propagates",
                "lang": "go",
                "fn_name": "countWithCancel",
                "prompt": "Write a Go function countWithCancel(parent context.Context, max int) (int, context.CancelFunc) that creates a child context with cancel, starts a goroutine counting to max (1ms per step), and returns the count channel result and the cancel func.",
                "test_harness": """package main
import (
    "context"
    "fmt"
    "time"
)
func countWithCancel(ctx context.Context, max int) (<-chan int, context.CancelFunc) {
    // <<STUDENT_CODE>>
}
func main() {
    ctx := context.Background()
    ch, cancel := countWithCancel(ctx, 100)
    time.Sleep(5 * time.Millisecond)
    cancel()
    count := <-ch
    if count >= 100 { panic("cancel did not stop early") }
    if count < 1 { panic("no counts recorded") }
    fmt.Println("GCC_P3 PASS")
}
""",
            },
            {
                "id": "GCC_P4_value",
                "label": "context.WithValue for request-scoped data",
                "lang": "go",
                "fn_name": "getRequestID",
                "prompt": 'Write a Go function getRequestID(ctx context.Context) string that retrieves the value stored with key "request_id" from ctx, returning "unknown" if absent.',
                "test_harness": """package main
import (
    "context"
    "fmt"
)
func getRequestID(ctx context.Context) string {
    // <<STUDENT_CODE>>
}
func main() {
    ctx := context.WithValue(context.Background(), "request_id", "abc-123")
    if getRequestID(ctx) != "abc-123" { panic("wrong id") }
    if getRequestID(context.Background()) != "unknown" { panic("missing should return unknown") }
    fmt.Println("GCC_P4 PASS")
}
""",
            },
            {
                "id": "GCC_P5_rename",
                "label": "Concept transfer: retry with context",
                "lang": "go",
                "fn_name": "retryWithCtx",
                "prompt": "Write a Go function retryWithCtx(ctx context.Context, fn func() error, maxAttempts int) error that calls fn up to maxAttempts times, stopping early if ctx is cancelled, returning the last error.",
                "test_harness": """package main
import (
    "context"
    "errors"
    "fmt"
)
func retryWithCtx(ctx context.Context, fn func() error, maxAttempts int) error {
    // <<STUDENT_CODE>>
}
func main() {
    calls := 0
    alwaysFail := func() error { calls++; return errors.New("fail") }
    err := retryWithCtx(context.Background(), alwaysFail, 3)
    if err == nil { panic("should fail") }
    if calls != 3 { panic(fmt.Sprintf("should call 3 times, got %d", calls)) }
    calls = 0
    succeed := func() error { calls++; if calls < 2 { return errors.New("not yet") }; return nil }
    if retryWithCtx(context.Background(), succeed, 5) != nil { panic("should succeed on 2nd") }
    fmt.Println("GCC_P5 PASS")
}
""",
            },
        ],
    },
    # ── PYTHON ───────────────────────────────────────────────────────────────
    "py_generator": {
        "lang": "python",
        "description": "Generator functions with yield",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "PGN_P1_range",
                "label": "Generator that yields a range of values",
                "lang": "python",
                "fn_name": "count_up",
                "prompt": "Write a Python generator function count_up(start: int, stop: int, step: int = 1) that yields integers from start up to (not including) stop, incrementing by step.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert list(count_up(0, 5)) == [0, 1, 2, 3, 4]
    assert list(count_up(0, 10, 2)) == [0, 2, 4, 6, 8]
    assert list(count_up(5, 5)) == []
    print("PGN_P1 PASS")

main()
""",
            },
            {
                "id": "PGN_P2_filter_gen",
                "label": "Generator that filters values",
                "lang": "python",
                "fn_name": "evens_gen",
                "prompt": "Write a Python generator function evens_gen(nums: list[int]) that yields only the even numbers from nums.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert list(evens_gen([1, 2, 3, 4, 5, 6])) == [2, 4, 6]
    assert list(evens_gen([])) == []
    assert list(evens_gen([1, 3, 5])) == []
    print("PGN_P2 PASS")

main()
""",
            },
            {
                "id": "PGN_P3_infinite",
                "label": "Infinite generator with take limit",
                "lang": "python",
                "fn_name": "fibonacci",
                "prompt": "Write a Python generator function fibonacci() that yields the Fibonacci sequence indefinitely: 0, 1, 1, 2, 3, 5, 8, ...",
                "test_harness": """
import itertools
# <<STUDENT_CODE>>

def main():
    result = list(itertools.islice(fibonacci(), 8))
    assert result == [0, 1, 1, 2, 3, 5, 8, 13], f"got {result}"
    print("PGN_P3 PASS")

main()
""",
            },
            {
                "id": "PGN_P4_pipeline",
                "label": "Generator pipeline: transform then filter",
                "lang": "python",
                "fn_name": "positive_squares",
                "prompt": "Write a Python generator function positive_squares(nums: list[int]) that yields the square of each number, but only for positive inputs.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert list(positive_squares([1, -2, 3, -4, 5])) == [1, 9, 25]
    assert list(positive_squares([])) == []
    assert list(positive_squares([-1, -2])) == []
    print("PGN_P4 PASS")

main()
""",
            },
            {
                "id": "PGN_P5_send",
                "label": "Generator as accumulator using send()",
                "lang": "python",
                "fn_name": "running_total",
                "prompt": "Write a Python generator function running_total() that starts at 0, accepts values via send(), and yields the running total after each send.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    gen = running_total()
    next(gen)  # prime the generator
    assert gen.send(10) == 10
    assert gen.send(5) == 15
    assert gen.send(-3) == 12
    print("PGN_P5 PASS")

main()
""",
            },
        ],
    },
    "py_list_ops": {
        "lang": "python",
        "description": "List comprehensions, sorting, grouping",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "PLO_P1_comprehension",
                "label": "List comprehension with condition",
                "lang": "python",
                "fn_name": "squares_of_evens",
                "prompt": "Write a Python function squares_of_evens(nums: list[int]) -> list[int] that returns the squares of all even numbers in nums.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert squares_of_evens([1,2,3,4,5,6]) == [4, 16, 36]
    assert squares_of_evens([]) == []
    assert squares_of_evens([1,3,5]) == []
    print("PLO_P1 PASS")

main()
""",
            },
            {
                "id": "PLO_P2_sort_key",
                "label": "Sort by custom key",
                "lang": "python",
                "fn_name": "sort_by_length",
                "prompt": "Write a Python function sort_by_length(words: list[str]) -> list[str] that returns the words sorted by length ascending, with ties broken alphabetically.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert sort_by_length(["banana", "fig", "apple", "kiwi"]) == ["fig", "kiwi", "apple", "banana"]
    assert sort_by_length([]) == []
    assert sort_by_length(["a", "b", "c"]) == ["a", "b", "c"]
    print("PLO_P2 PASS")

main()
""",
            },
            {
                "id": "PLO_P3_flatten",
                "label": "Flatten nested list",
                "lang": "python",
                "fn_name": "flatten",
                "prompt": "Write a Python function flatten(nested: list[list[int]]) -> list[int] that flattens one level of nesting.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert flatten([[1,2],[3,4],[5]]) == [1,2,3,4,5]
    assert flatten([]) == []
    assert flatten([[], [1], []]) == [1]
    print("PLO_P3 PASS")

main()
""",
            },
            {
                "id": "PLO_P4_group_by",
                "label": "Group items by key function",
                "lang": "python",
                "fn_name": "group_by",
                "prompt": "Write a Python function group_by(items: list, key_fn) -> dict that groups items by the result of key_fn(item).",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    words = ["cat", "dog", "bear", "ant"]
    result = group_by(words, len)
    assert sorted(result[3]) == ["ant", "cat", "dog"]
    assert result[4] == ["bear"]
    print("PLO_P4 PASS")

main()
""",
            },
            {
                "id": "PLO_P5_sliding_window",
                "label": "Sliding window of size n",
                "lang": "python",
                "fn_name": "sliding_window",
                "prompt": "Write a Python function sliding_window(items: list, n: int) -> list[tuple] that returns all consecutive n-element windows as tuples.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert sliding_window([1,2,3,4,5], 3) == [(1,2,3),(2,3,4),(3,4,5)]
    assert sliding_window([1,2], 3) == []
    assert sliding_window([], 2) == []
    assert sliding_window([1,2,3], 1) == [(1,),(2,),(3,)]
    print("PLO_P5 PASS")

main()
""",
            },
        ],
    },
    "py_dict_ops": {
        "lang": "python",
        "description": "Dict comprehensions, merging, transformation",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "PDO_P1_invert",
                "label": "Invert dict keys and values",
                "lang": "python",
                "fn_name": "invert_dict",
                "prompt": "Write a Python function invert_dict(d: dict) -> dict that swaps keys and values.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert invert_dict({"a": 1, "b": 2}) == {1: "a", 2: "b"}
    assert invert_dict({}) == {}
    print("PDO_P1 PASS")

main()
""",
            },
            {
                "id": "PDO_P2_merge",
                "label": "Merge two dicts, later values win",
                "lang": "python",
                "fn_name": "merge_dicts",
                "prompt": "Write a Python function merge_dicts(a: dict, b: dict) -> dict that returns a new dict with all key-value pairs from both, with b's values overriding a's on conflicts.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert merge_dicts({"x": 1, "y": 2}, {"y": 99, "z": 3}) == {"x": 1, "y": 99, "z": 3}
    assert merge_dicts({}, {"a": 1}) == {"a": 1}
    assert merge_dicts({"a": 1}, {}) == {"a": 1}
    print("PDO_P2 PASS")

main()
""",
            },
            {
                "id": "PDO_P3_filter",
                "label": "Filter dict by value predicate",
                "lang": "python",
                "fn_name": "filter_dict",
                "prompt": "Write a Python function filter_dict(d: dict[str, int], predicate) -> dict[str, int] that returns a new dict with only entries where predicate(value) is True.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    d = {"a": 1, "b": -1, "c": 2, "d": -3}
    assert filter_dict(d, lambda v: v > 0) == {"a": 1, "c": 2}
    assert filter_dict({}, lambda v: True) == {}
    print("PDO_P3 PASS")

main()
""",
            },
            {
                "id": "PDO_P4_count",
                "label": "Count occurrences into dict",
                "lang": "python",
                "fn_name": "count_items",
                "prompt": "Write a Python function count_items(items: list) -> dict that counts how many times each item appears.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert count_items(["a","b","a","c","b","a"]) == {"a":3,"b":2,"c":1}
    assert count_items([]) == {}
    assert count_items([1,1,1]) == {1:3}
    print("PDO_P4 PASS")

main()
""",
            },
            {
                "id": "PDO_P5_transform_values",
                "label": "Apply function to all values",
                "lang": "python",
                "fn_name": "map_values",
                "prompt": "Write a Python function map_values(d: dict, fn) -> dict that returns a new dict with fn applied to every value.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert map_values({"a":1,"b":2,"c":3}, lambda x: x*2) == {"a":2,"b":4,"c":6}
    assert map_values({}, str) == {}
    assert map_values({"x":"hello"}, str.upper) == {"x":"HELLO"}
    print("PDO_P5 PASS")

main()
""",
            },
        ],
    },
    "py_class_basic": {
        "lang": "python",
        "description": "Python class with __init__, methods, properties",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python class — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "PCB_P1_stack",
                "label": "Stack class with push/pop",
                "lang": "python",
                "fn_name": "__init__",
                "prompt": "Write a Python class Stack with methods: push(item), pop() -> item (raises IndexError if empty), peek() -> item, is_empty() -> bool, and __len__() -> int.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    s = Stack()
    assert s.is_empty()
    assert len(s) == 0
    s.push(1); s.push(2); s.push(3)
    assert len(s) == 3
    assert s.peek() == 3
    assert s.pop() == 3
    assert s.pop() == 2
    assert not s.is_empty()
    try:
        empty = Stack(); empty.pop()
        assert False, "should raise"
    except IndexError:
        pass
    print("PCB_P1 PASS")

main()
""",
            },
            {
                "id": "PCB_P2_property",
                "label": "Class with @property and validation",
                "lang": "python",
                "fn_name": "temperature",
                "prompt": "Write a Python class Temperature with a Celsius value stored internally. Provide: __init__(celsius: float), a celsius property (getter/setter — raises ValueError if set below -273.15), and a fahrenheit property (getter only, returns celsius * 9/5 + 32).",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    t = Temperature(0)
    assert t.celsius == 0
    assert t.fahrenheit == 32.0
    t.celsius = 100
    assert abs(t.fahrenheit - 212.0) < 1e-9
    try:
        t.celsius = -300
        assert False, "should raise"
    except ValueError:
        pass
    print("PCB_P2 PASS")

main()
""",
            },
            {
                "id": "PCB_P3_repr",
                "label": "__repr__ and __eq__",
                "lang": "python",
                "fn_name": "__repr__",
                "prompt": "Write a Python class Vector2D with fields x: float and y: float. Implement __repr__ (returns 'Vector2D(x, y)'), __eq__ (compares x and y), and __add__ (adds component-wise).",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    v1 = Vector2D(1.0, 2.0)
    v2 = Vector2D(3.0, 4.0)
    assert repr(v1) == "Vector2D(1.0, 2.0)"
    assert v1 == Vector2D(1.0, 2.0)
    assert v1 != v2
    v3 = v1 + v2
    assert v3 == Vector2D(4.0, 6.0)
    print("PCB_P3 PASS")

main()
""",
            },
            {
                "id": "PCB_P4_classmethod",
                "label": "@classmethod factory constructor",
                "lang": "python",
                "fn_name": "from_string",
                "prompt": "Write a Python class Color with fields r: int, g: int, b: int. Implement __init__(r, g, b) and a classmethod from_hex(hex_str: str) -> 'Color' that parses '#RRGGBB' format.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    c = Color.from_hex("#FF8000")
    assert c.r == 255 and c.g == 128 and c.b == 0
    c2 = Color(10, 20, 30)
    assert c2.r == 10
    print("PCB_P4 PASS")

main()
""",
            },
            {
                "id": "PCB_P5_iter",
                "label": "__iter__ and __next__ for iterable",
                "lang": "python",
                "fn_name": "__iter__",
                "prompt": "Write a Python class Countdown that takes a start: int and implements __iter__ and __next__ to count down from start to 1 inclusive, raising StopIteration when done.",
                "test_harness": """
# <<STUDENT_CODE>>

def main():
    assert list(Countdown(5)) == [5, 4, 3, 2, 1]
    assert list(Countdown(1)) == [1]
    assert list(Countdown(0)) == []
    print("PCB_P5 PASS")

main()
""",
            },
        ],
    },
    "py_decorator": {
        "lang": "python",
        "description": "Function decorators: timing, caching, retry",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python function/decorator — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "PDR_P1_log_calls",
                "label": "Decorator that logs call count",
                "lang": "python",
                "fn_name": "call_counter",
                "prompt": "Write a Python decorator call_counter that adds a call_count attribute to the decorated function, incrementing it each time the function is called.",
                "test_harness": """
import functools
# <<STUDENT_CODE>>

@call_counter
def add(a, b):
    return a + b

def main():
    add(1, 2)
    add(3, 4)
    add(5, 6)
    assert add.call_count == 3, f"expected 3, got {add.call_count}"
    assert add(1, 1) == 2
    print("PDR_P1 PASS")

main()
""",
            },
            {
                "id": "PDR_P2_memoize",
                "label": "Memoization decorator",
                "lang": "python",
                "fn_name": "memoize",
                "prompt": "Write a Python decorator memoize that caches the return value of a function based on its arguments, so repeated calls with the same args don't re-execute the function body.",
                "test_harness": """
import functools
# <<STUDENT_CODE>>

calls = 0
@memoize
def expensive(n):
    global calls
    calls += 1
    return n * 2

def main():
    assert expensive(5) == 10
    assert expensive(5) == 10
    assert expensive(3) == 6
    assert calls == 2, f"expected 2 calls, got {calls}"
    print("PDR_P2 PASS")

main()
""",
            },
            {
                "id": "PDR_P3_validate",
                "label": "Decorator that validates argument types",
                "lang": "python",
                "fn_name": "require_positive",
                "prompt": "Write a Python decorator require_positive that raises ValueError if the first positional argument to the decorated function is not a positive number (> 0).",
                "test_harness": """
# <<STUDENT_CODE>>

@require_positive
def sqrt_approx(n):
    return n ** 0.5

def main():
    assert abs(sqrt_approx(4) - 2.0) < 1e-9
    try:
        sqrt_approx(-1)
        assert False, "should raise"
    except ValueError:
        pass
    try:
        sqrt_approx(0)
        assert False, "should raise"
    except ValueError:
        pass
    print("PDR_P3 PASS")

main()
""",
            },
            {
                "id": "PDR_P4_retry",
                "label": "Retry decorator with max attempts",
                "lang": "python",
                "fn_name": "retry",
                "prompt": "Write a Python decorator factory retry(max_attempts: int) that retries the decorated function up to max_attempts times on exception, raising the last exception if all attempts fail.",
                "test_harness": """
# <<STUDENT_CODE>>

attempt = 0
@retry(max_attempts=3)
def flaky():
    global attempt
    attempt += 1
    if attempt < 3:
        raise RuntimeError("not yet")
    return "ok"

def main():
    global attempt
    result = flaky()
    assert result == "ok", f"got {result}"
    assert attempt == 3, f"expected 3 attempts, got {attempt}"

    @retry(max_attempts=2)
    def always_fail():
        raise ValueError("always")
    try:
        always_fail()
        assert False, "should raise"
    except ValueError:
        pass
    print("PDR_P4 PASS")

main()
""",
            },
            {
                "id": "PDR_P5_timing",
                "label": "Timing decorator that stores elapsed time",
                "lang": "python",
                "fn_name": "timed",
                "prompt": "Write a Python decorator timed that after each call stores the elapsed wall-clock time (in seconds) in a last_elapsed attribute on the wrapped function.",
                "test_harness": """
import time, functools
# <<STUDENT_CODE>>

@timed
def slow_add(a, b):
    time.sleep(0.01)
    return a + b

def main():
    result = slow_add(1, 2)
    assert result == 3
    assert hasattr(slow_add, 'last_elapsed'), "missing last_elapsed"
    assert slow_add.last_elapsed >= 0.005, f"too fast: {slow_add.last_elapsed}"
    print("PDR_P5 PASS")

main()
""",
            },
        ],
    },
    "py_regex": {
        "lang": "python",
        "description": "re module: search, findall, sub, groups",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "PRX_P1_extract",
                "label": "Extract all numbers from string",
                "lang": "python",
                "fn_name": "extract_numbers",
                "prompt": "Write a Python function extract_numbers(text: str) -> list[int] that extracts all integers (including negative) from text.",
                "test_harness": """
import re
# <<STUDENT_CODE>>

def main():
    assert extract_numbers("I have 3 cats and -2 dogs") == [3, -2]
    assert extract_numbers("no numbers here") == []
    assert extract_numbers("42") == [42]
    print("PRX_P1 PASS")

main()
""",
            },
            {
                "id": "PRX_P2_validate_email",
                "label": "Validate email format",
                "lang": "python",
                "fn_name": "is_valid_email",
                "prompt": "Write a Python function is_valid_email(email: str) -> bool that returns True if email matches a basic pattern: non-empty local part, @, non-empty domain with at least one dot.",
                "test_harness": """
import re
# <<STUDENT_CODE>>

def main():
    assert is_valid_email("user@example.com")
    assert is_valid_email("a.b+c@sub.domain.org")
    assert not is_valid_email("notanemail")
    assert not is_valid_email("@nodomain.com")
    assert not is_valid_email("noat.com")
    print("PRX_P2 PASS")

main()
""",
            },
            {
                "id": "PRX_P3_replace",
                "label": "Replace pattern with transformed match",
                "lang": "python",
                "fn_name": "redact_ssn",
                "prompt": "Write a Python function redact_ssn(text: str) -> str that replaces all SSN patterns (NNN-NN-NNNN) with 'XXX-XX-XXXX'.",
                "test_harness": """
import re
# <<STUDENT_CODE>>

def main():
    assert redact_ssn("SSN: 123-45-6789") == "SSN: XXX-XX-XXXX"
    assert redact_ssn("no ssn here") == "no ssn here"
    assert redact_ssn("a: 111-22-3333 b: 444-55-6666") == "a: XXX-XX-XXXX b: XXX-XX-XXXX"
    print("PRX_P3 PASS")

main()
""",
            },
            {
                "id": "PRX_P4_groups",
                "label": "Named capture groups",
                "lang": "python",
                "fn_name": "parse_date",
                "prompt": "Write a Python function parse_date(text: str) -> dict | None that parses a date in 'YYYY-MM-DD' format using named groups, returning {'year': str, 'month': str, 'day': str} or None if no match.",
                "test_harness": """
import re
# <<STUDENT_CODE>>

def main():
    r = parse_date("Today is 2024-03-15.")
    assert r == {"year": "2024", "month": "03", "day": "15"}, f"got {r}"
    assert parse_date("no date here") is None
    print("PRX_P4 PASS")

main()
""",
            },
            {
                "id": "PRX_P5_split",
                "label": "Split on multiple delimiters",
                "lang": "python",
                "fn_name": "tokenize",
                "prompt": "Write a Python function tokenize(text: str) -> list[str] that splits text on whitespace, commas, semicolons, or pipes, removing empty strings.",
                "test_harness": """
import re
# <<STUDENT_CODE>>

def main():
    assert tokenize("a,b;c|d e") == ["a","b","c","d","e"]
    assert tokenize("  hello   world  ") == ["hello","world"]
    assert tokenize("") == []
    print("PRX_P5 PASS")

main()
""",
            },
        ],
    },
    # ── TYPESCRIPT ───────────────────────────────────────────────────────────
    "ts_async_await": {
        "lang": "typescript",
        "description": "async/await with Promise, error handling",
        "system": (
            "You are an expert TypeScript programmer. Write strict, idiomatic TypeScript. "
            "Output ONLY the TypeScript function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "TSA_P1_basic",
                "label": "async function returning Promise<number>",
                "lang": "typescript",
                "fn_name": "delayedDouble",
                "prompt": "Write a TypeScript async function delayedDouble(n: number): Promise<number> that resolves with n * 2 after a 0ms delay (use Promise resolve directly, no actual sleep needed).",
                "test_harness": """
// <<STUDENT_CODE>>

async function main() {
    const result = await delayedDouble(5);
    if (result !== 10) throw new Error(`expected 10, got ${result}`);
    const r2 = await delayedDouble(0);
    if (r2 !== 0) throw new Error(`expected 0, got ${r2}`);
    console.log("TSA_P1 PASS");
}
main();
""",
            },
            {
                "id": "TSA_P2_catch",
                "label": "async error handling with try/catch",
                "lang": "typescript",
                "fn_name": "safeParseJson",
                "prompt": "Write a TypeScript async function safeParseJson<T>(json: string): Promise<T | null> that resolves with the parsed object, or null if JSON.parse throws.",
                "test_harness": """
// <<STUDENT_CODE>>

async function main() {
    const r1 = await safeParseJson<{a: number}>('{"a": 1}');
    if (!r1 || r1.a !== 1) throw new Error("parse failed");
    const r2 = await safeParseJson("bad json{{{");
    if (r2 !== null) throw new Error("should return null");
    console.log("TSA_P2 PASS");
}
main();
""",
            },
            {
                "id": "TSA_P3_all",
                "label": "Promise.all to run in parallel",
                "lang": "typescript",
                "fn_name": "fetchAll",
                "prompt": "Write a TypeScript async function fetchAll<T>(fetchers: Array<() => Promise<T>>): Promise<T[]> that runs all fetcher functions in parallel and returns their results in order.",
                "test_harness": """
// <<STUDENT_CODE>>

async function main() {
    const fetchers = [
        () => Promise.resolve(1),
        () => Promise.resolve(2),
        () => Promise.resolve(3),
    ];
    const results = await fetchAll(fetchers);
    if (JSON.stringify(results) !== "[1,2,3]") throw new Error(`wrong: ${results}`);
    const empty = await fetchAll([]);
    if (empty.length !== 0) throw new Error("empty failed");
    console.log("TSA_P3 PASS");
}
main();
""",
            },
            {
                "id": "TSA_P4_race",
                "label": "Promise.race for first-to-resolve",
                "lang": "typescript",
                "fn_name": "firstResolved",
                "prompt": "Write a TypeScript async function firstResolved<T>(promises: Promise<T>[]): Promise<T> that returns the value of whichever promise resolves first.",
                "test_harness": """
// <<STUDENT_CODE>>

async function main() {
    const fast = Promise.resolve(42);
    const slow = new Promise<number>(resolve => setTimeout(() => resolve(99), 1000));
    const result = await firstResolved([slow, fast]);
    if (result !== 42) throw new Error(`expected 42, got ${result}`);
    console.log("TSA_P4 PASS");
}
main();
""",
            },
            {
                "id": "TSA_P5_retry",
                "label": "Async retry on failure",
                "lang": "typescript",
                "fn_name": "retryAsync",
                "prompt": "Write a TypeScript async function retryAsync<T>(fn: () => Promise<T>, maxAttempts: number): Promise<T> that retries fn up to maxAttempts times, returning the result on success or throwing the last error.",
                "test_harness": """
// <<STUDENT_CODE>>

async function main() {
    let attempts = 0;
    const result = await retryAsync(async () => {
        attempts++;
        if (attempts < 3) throw new Error("not yet");
        return "ok";
    }, 5);
    if (result !== "ok") throw new Error("wrong result");
    if (attempts !== 3) throw new Error(`expected 3 attempts, got ${attempts}`);

    let didThrow = false;
    try {
        await retryAsync(async () => { throw new Error("always"); }, 2);
    } catch { didThrow = true; }
    if (!didThrow) throw new Error("should have thrown");
    console.log("TSA_P5 PASS");
}
main();
""",
            },
        ],
    },
    "ts_type_guard": {
        "lang": "typescript",
        "description": "TypeScript type guards and narrowing",
        "system": (
            "You are an expert TypeScript programmer. Write strict, idiomatic TypeScript. "
            "Output ONLY the TypeScript function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "TTG_P1_is_string",
                "label": "isString type guard",
                "lang": "typescript",
                "fn_name": "isString",
                "prompt": "Write a TypeScript function isString(value: unknown): value is string that returns true if value is a string.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    if (!isString("hello")) throw new Error("string failed");
    if (isString(42)) throw new Error("number should fail");
    if (isString(null)) throw new Error("null should fail");
    if (isString(undefined)) throw new Error("undefined should fail");
    console.log("TTG_P1 PASS");
}
main();
""",
            },
            {
                "id": "TTG_P2_discriminated",
                "label": "Discriminated union narrowing",
                "lang": "typescript",
                "fn_name": "getArea",
                "prompt": "Write TypeScript types: Circle = {kind: 'circle', radius: number} and Square = {kind: 'square', side: number}. Write function getArea(shape: Circle | Square): number using the kind discriminant.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const c: Circle = { kind: 'circle', radius: 1 };
    const s: Square = { kind: 'square', side: 3 };
    if (Math.abs(getArea(c) - Math.PI) > 1e-9) throw new Error("circle area wrong");
    if (getArea(s) !== 9) throw new Error("square area wrong");
    console.log("TTG_P2 PASS");
}
main();
""",
            },
            {
                "id": "TTG_P3_array_guard",
                "label": "Type guard for array items",
                "lang": "typescript",
                "fn_name": "filterStrings",
                "prompt": "Write a TypeScript function filterStrings(items: unknown[]): string[] that returns only the string items from the array.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const mixed = [1, "hello", true, "world", null, "!"];
    const result = filterStrings(mixed);
    if (JSON.stringify(result) !== '["hello","world","!"]') throw new Error(`wrong: ${result}`);
    if (filterStrings([]).length !== 0) throw new Error("empty failed");
    console.log("TTG_P3 PASS");
}
main();
""",
            },
            {
                "id": "TTG_P4_instanceof",
                "label": "instanceof narrowing",
                "lang": "typescript",
                "fn_name": "describeError",
                "prompt": "Write a TypeScript function describeError(err: unknown): string that returns the error message if err is an Error instance, 'string error: {err}' if it's a string, or 'unknown error' otherwise.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    if (describeError(new Error("boom")) !== "boom") throw new Error("Error failed");
    if (describeError("oops") !== "string error: oops") throw new Error("string failed");
    if (describeError(42) !== "unknown error") throw new Error("unknown failed");
    console.log("TTG_P4 PASS");
}
main();
""",
            },
            {
                "id": "TTG_P5_exhaustive",
                "label": "Exhaustive check with never",
                "lang": "typescript",
                "fn_name": "formatStatus",
                "prompt": "Write TypeScript type Status = 'pending' | 'active' | 'closed'. Write function formatStatus(s: Status): string returning 'Pending...', 'Active', or 'Closed' respectively, with an exhaustive never check for future safety.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    if (formatStatus('pending') !== 'Pending...') throw new Error("pending wrong");
    if (formatStatus('active') !== 'Active') throw new Error("active wrong");
    if (formatStatus('closed') !== 'Closed') throw new Error("closed wrong");
    console.log("TTG_P5 PASS");
}
main();
""",
            },
        ],
    },
    "ts_array_ops": {
        "lang": "typescript",
        "description": "TypeScript array methods: reduce, flatMap, find, every, some",
        "system": (
            "You are an expert TypeScript programmer. Write strict, idiomatic TypeScript. "
            "Output ONLY the TypeScript function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "TAO_P1_reduce",
                "label": "reduce to build object from array",
                "lang": "typescript",
                "fn_name": "toRecord",
                "prompt": "Write a TypeScript function toRecord<T>(items: T[], keyFn: (item: T) => string): Record<string, T> that converts an array to a record using keyFn for keys.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const users = [{id: 'a', name: 'Alice'}, {id: 'b', name: 'Bob'}];
    const r = toRecord(users, u => u.id);
    if (r['a'].name !== 'Alice') throw new Error("Alice wrong");
    if (r['b'].name !== 'Bob') throw new Error("Bob wrong");
    const empty = toRecord([], (x: string) => x);
    if (Object.keys(empty).length !== 0) throw new Error("empty failed");
    console.log("TAO_P1 PASS");
}
main();
""",
            },
            {
                "id": "TAO_P2_flatmap",
                "label": "flatMap to expand each element",
                "lang": "typescript",
                "fn_name": "expandRange",
                "prompt": "Write a TypeScript function expandRange(ranges: Array<[number, number]>): number[] that converts each [start, end] pair into all integers from start to end inclusive.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const r = expandRange([[1,3],[5,6]]);
    if (JSON.stringify(r) !== '[1,2,3,5,6]') throw new Error(`wrong: ${r}`);
    if (expandRange([]).length !== 0) throw new Error("empty failed");
    console.log("TAO_P2 PASS");
}
main();
""",
            },
            {
                "id": "TAO_P3_find_index",
                "label": "find and findIndex",
                "lang": "typescript",
                "fn_name": "firstOver",
                "prompt": "Write a TypeScript function firstOver(nums: number[], threshold: number): {value: number, index: number} | null that returns the first number exceeding threshold with its index, or null.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const r = firstOver([1, 5, 3, 8, 2], 4);
    if (!r || r.value !== 5 || r.index !== 1) throw new Error(`wrong: ${JSON.stringify(r)}`);
    if (firstOver([1,2,3], 10) !== null) throw new Error("should be null");
    console.log("TAO_P3 PASS");
}
main();
""",
            },
            {
                "id": "TAO_P4_every_some",
                "label": "every and some for validation",
                "lang": "typescript",
                "fn_name": "validateScores",
                "prompt": "Write a TypeScript function validateScores(scores: number[]): {allValid: boolean, anyPassing: boolean} where allValid means all scores are 0-100 inclusive, and anyPassing means any score >= 60.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const r1 = validateScores([80, 90, 55, 70]);
    if (!r1.allValid || !r1.anyPassing) throw new Error(`wrong: ${JSON.stringify(r1)}`);
    const r2 = validateScores([101, 80]);
    if (r2.allValid) throw new Error("101 is invalid");
    const r3 = validateScores([10, 20, 30]);
    if (r3.anyPassing) throw new Error("none passing");
    console.log("TAO_P4 PASS");
}
main();
""",
            },
            {
                "id": "TAO_P5_zip",
                "label": "Zip two arrays into pairs",
                "lang": "typescript",
                "fn_name": "zip",
                "prompt": "Write a TypeScript function zip<A, B>(a: A[], b: B[]): Array<[A, B]> that pairs elements by index, stopping at the shorter array's length.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const r = zip([1,2,3], ['a','b','c']);
    if (JSON.stringify(r) !== '[[1,"a"],[2,"b"],[3,"c"]]') throw new Error(`wrong: ${r}`);
    const r2 = zip([1,2,3], ['a']);
    if (r2.length !== 1) throw new Error("length mismatch");
    if (zip([],[]).length !== 0) throw new Error("empty failed");
    console.log("TAO_P5 PASS");
}
main();
""",
            },
        ],
    },
    "ts_utility_types": {
        "lang": "typescript",
        "description": "TypeScript utility types: Partial, Pick, Omit, Record",
        "system": (
            "You are an expert TypeScript programmer. Write strict, idiomatic TypeScript. "
            "Output ONLY the TypeScript function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "TUT_P1_partial_update",
                "label": "Update function using Partial<T>",
                "lang": "typescript",
                "fn_name": "updateUser",
                "prompt": "Write a TypeScript type User = {id: string, name: string, email: string}. Write function updateUser(user: User, updates: Partial<User>): User that returns a new User with updates applied.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const u: User = {id: '1', name: 'Alice', email: 'a@b.com'};
    const updated = updateUser(u, {name: 'Bob'});
    if (updated.name !== 'Bob') throw new Error("name not updated");
    if (updated.email !== 'a@b.com') throw new Error("email changed");
    if (updated.id !== '1') throw new Error("id changed");
    console.log("TUT_P1 PASS");
}
main();
""",
            },
            {
                "id": "TUT_P2_pick",
                "label": "Pick to create subset type",
                "lang": "typescript",
                "fn_name": "toPublicUser",
                "prompt": "Write a TypeScript type FullUser = {id: string, name: string, email: string, passwordHash: string}. Write function toPublicUser(user: FullUser): Pick<FullUser, 'id' | 'name'> that returns only id and name.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const full: FullUser = {id:'1',name:'Alice',email:'a@b.com',passwordHash:'abc'};
    const pub = toPublicUser(full);
    if (pub.id !== '1' || pub.name !== 'Alice') throw new Error("pick failed");
    if ((pub as any).passwordHash !== undefined) throw new Error("hash leaked");
    console.log("TUT_P2 PASS");
}
main();
""",
            },
            {
                "id": "TUT_P3_record",
                "label": "Record type for lookup table",
                "lang": "typescript",
                "fn_name": "buildIndex",
                "prompt": "Write a TypeScript function buildIndex(items: string[]): Record<string, number> that maps each string to its first-occurrence index.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const idx = buildIndex(['a','b','c','b']);
    if (idx['a'] !== 0) throw new Error("a wrong");
    if (idx['b'] !== 1) throw new Error("b should be first occurrence");
    if (idx['c'] !== 2) throw new Error("c wrong");
    console.log("TUT_P3 PASS");
}
main();
""",
            },
            {
                "id": "TUT_P4_required",
                "label": "Required<T> vs Partial in function sig",
                "lang": "typescript",
                "fn_name": "applyDefaults",
                "prompt": "Write TypeScript type Config = {host?: string, port?: number, ssl?: boolean}. Write function applyDefaults(cfg: Config): Required<Config> that fills in defaults: host='localhost', port=8080, ssl=false.",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const r = applyDefaults({});
    if (r.host !== 'localhost' || r.port !== 8080 || r.ssl !== false) throw new Error(`wrong defaults: ${JSON.stringify(r)}`);
    const r2 = applyDefaults({port: 443, ssl: true});
    if (r2.host !== 'localhost' || r2.port !== 443 || r2.ssl !== true) throw new Error(`overrides wrong: ${JSON.stringify(r2)}`);
    console.log("TUT_P4 PASS");
}
main();
""",
            },
            {
                "id": "TUT_P5_mapped",
                "label": "Custom mapped type",
                "lang": "typescript",
                "fn_name": "makeNullable",
                "prompt": "Write a TypeScript generic function makeNullable<T extends object>(obj: T): {[K in keyof T]: T[K] | null} that returns the same object typed with all values nullable (at runtime just return the object as-is).",
                "test_harness": """
// <<STUDENT_CODE>>

function main() {
    const obj = {a: 1, b: 'hello'};
    const r = makeNullable(obj);
    if (r.a !== 1 || r.b !== 'hello') throw new Error("values changed");
    console.log("TUT_P5 PASS");
}
main();
""",
            },
        ],
    },
}
