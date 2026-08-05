// pdu (parallel-disk-usage) reimplementation — Claude-tier, native Rust, no crates.
// Reverse-engineered black-box from the reference (Determinex oracle). FIRST ATTEMPT — baseline to
// iterate via csview_iterate harness. Algorithm notes captured in corpus build_knowledge.
//
// Output (default, bottom-up): per node, columns:
//   <size right-aligned> <tree-connectors+name left-aligned> │<bar>│ <pct right-aligned>%
// size: --quantity block-size (blocks*512, default) | apparent-size | block-count;
//       --bytes-format metric (/1000, default) | plain | binary (/1024).
// traversal: post-order, siblings ascending by size; root last (top-down reverses).
// bar: width = --total-width minus columns; self=█, ancestor at depth d shaded (depth1=░,
//      depth2=▒, deeper=▓); bands are cumulative size proportions; spaces fill to 100%.
use std::io::{self, Read, Write};

const VERSION: &str = "0.21.1";
const HELP: &str = r#"Summarize disk usage of the set of files, recursively for directories.

Copyright: Apache-2.0 © 2021 Hoàng Văn Khải <https://github.com/KSXGitHub/>
Sponsor: https://github.com/sponsors/KSXGitHub

Usage: executable [OPTIONS] [FILES]...

Arguments:
  [FILES]...
          List of files and/or directories

Options:
      --json-input
          Read JSON data from stdin

      --json-output
          Print JSON data instead of an ASCII chart

  -b, --bytes-format <BYTES_FORMAT>
          How to display the numbers of bytes

          Possible values:
          - plain:  Display plain number of bytes without units
          - metric: Use metric scale, i.e. 1K = 1000B, 1M = 1000K, and so on
          - binary: Use binary scale, i.e. 1K = 1024B, 1M = 1024K, and so on

          [default: metric]

  -H, --deduplicate-hardlinks
          Detect and subtract the sizes of hardlinks from their parent directory totals

          [aliases: --detect-links, --dedupe-links]

      --top-down
          Print the tree top-down instead of bottom-up

      --align-right
          Set the root of the bars to the right

  -q, --quantity <QUANTITY>
          Aspect of the files/directories to be measured

          Possible values:
          - apparent-size: Measure apparent sizes
          - block-size:    Measure block sizes (block-count * 512B)
          - block-count:   Count numbers of blocks

          [default: block-size]

  -d, --max-depth <MAX_DEPTH>
          Maximum depth to display the data. Could be either "inf" or a positive integer

          [default: 10]
          [aliases: --depth]

  -w, --total-width <TOTAL_WIDTH>
          Width of the visualization

          [aliases: --width]

      --column-width <TREE_WIDTH> <BAR_WIDTH>
          Maximum widths of the tree column and width of the bar column

  -m, --min-ratio <MIN_RATIO>
          Minimal size proportion required to appear

          [default: 0.01]

      --no-sort
          Do not sort the branches in the tree

  -s, --silent-errors
          Prevent filesystem error messages from appearing in stderr

          [aliases: --no-errors]

  -p, --progress
          Report progress being made at the expense of performance

      --threads <THREADS>
          Set the maximum number of threads to spawn. Could be either "auto", "max", or a positive integer

          [default: auto]

      --omit-json-shared-details
          Do not output `.shared.details` in the JSON output

      --omit-json-shared-summary
          Do not output `.shared.summary` in the JSON output

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version

Examples:
    Show disk usage chart of current working directory
    $ pdu

    Show disk usage chart of a single file or directory
    $ pdu path/to/file/or/directory

    Compare disk usages of multiple files and/or directories
    $ pdu file.txt dir/

    Show chart in apparent sizes instead of block sizes
    $ pdu --quantity=apparent-size

    Detect and subtract the sizes of hardlinks from their parent nodes
    $ pdu --deduplicate-hardlinks

    Show sizes in plain numbers instead of metric units
    $ pdu --bytes-format=plain

    Show sizes in base 2¹⁰ units (binary) instead of base 10³ units (metric)
    $ pdu --bytes-format=binary

    Show disk usage chart of all entries regardless of size
    $ pdu --min-ratio=0

    Only show disk usage chart of entries whose size is at least 5% of total
    $ pdu --min-ratio=0.05

    Show disk usage data as JSON instead of chart
    $ pdu --min-ratio=0 --max-depth=inf --json-output | jq

    Visualize existing JSON representation of disk usage data
    $ pdu --json-input < disk-usage.json
"#;
const HELP_SHORT: &str = r#"Summarize disk usage of the set of files, recursively for directories.

Usage: executable [OPTIONS] [FILES]...

Arguments:
  [FILES]...  List of files and/or directories

Options:
      --json-input
          Read JSON data from stdin
      --json-output
          Print JSON data instead of an ASCII chart
  -b, --bytes-format <BYTES_FORMAT>
          How to display the numbers of bytes [default: metric] [possible values: plain, metric, binary]
  -H, --deduplicate-hardlinks
          Detect and subtract the sizes of hardlinks from their parent directory totals [aliases: --detect-links, --dedupe-links]
      --top-down
          Print the tree top-down instead of bottom-up
      --align-right
          Set the root of the bars to the right
  -q, --quantity <QUANTITY>
          Aspect of the files/directories to be measured [default: block-size] [possible values: apparent-size, block-size, block-count]
  -d, --max-depth <MAX_DEPTH>
          Maximum depth to display the data. Could be either "inf" or a positive integer [default: 10] [aliases: --depth]
  -w, --total-width <TOTAL_WIDTH>
          Width of the visualization [aliases: --width]
      --column-width <TREE_WIDTH> <BAR_WIDTH>
          Maximum widths of the tree column and width of the bar column
  -m, --min-ratio <MIN_RATIO>
          Minimal size proportion required to appear [default: 0.01]
      --no-sort
          Do not sort the branches in the tree
  -s, --silent-errors
          Prevent filesystem error messages from appearing in stderr [aliases: --no-errors]
  -p, --progress
          Report progress being made at the expense of performance
      --threads <THREADS>
          Set the maximum number of threads to spawn. Could be either "auto", "max", or a positive integer [default: auto]
      --omit-json-shared-details
          Do not output `.shared.details` in the JSON output
      --omit-json-shared-summary
          Do not output `.shared.summary` in the JSON output
  -h, --help
          Print help (see more with '--help')
  -V, --version
          Print version

Examples:
    $ pdu
    $ pdu path/to/file/or/directory
    $ pdu file.txt dir/
    $ pdu --quantity=apparent-size
    $ pdu --deduplicate-hardlinks
    $ pdu --bytes-format=plain
    $ pdu --bytes-format=binary
    $ pdu --min-ratio=0
    $ pdu --min-ratio=0.05
    $ pdu --min-ratio=0 --max-depth=inf --json-output | jq
    $ pdu --json-input < disk-usage.json
"#;

struct Node {
    name: String,
    size: u64,
    depth: usize,
    children: Vec<Node>,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    // clap rejects a non-repeatable flag given more than once (exit 2).
    if let Some(disp) = find_duplicate(&args) {
        eprint!(
            "error: the argument '{}' cannot be used multiple times\n\nUsage: executable [OPTIONS] [FILES]...\n\nFor more information, try '--help'.\n",
            disp
        );
        std::process::exit(2);
    }
    let mut files: Vec<String> = Vec::new();
    let mut bytes_format = String::from("metric");
    let mut quantity = String::from("block-size");
    let mut quantity_set = false;
    let mut top_down = false;
    let mut json_output = false;
    let mut json_input = false;
    let mut min_ratio: f64 = 0.01;
    let mut no_sort = false;
    let mut silent = false;
    let mut align_right = false;
    let mut max_depth: usize = 10;
    let mut dedup = false;
    let mut omit_details = false;
    let mut omit_summary = false;
    let mut total_width: Option<usize> = None; // None => auto (default 150 when non-tty)
    let mut col_widths: Option<(usize, usize)> = None; // explicit (tree_width, bar_width)
    let mut i = 1;
    while i < args.len() {
        let a = args[i].clone();
        let mut take = |i: &mut usize| -> String {
            *i += 1;
            args.get(*i).cloned().unwrap_or_default()
        };
        match a.as_str() {
            "--help" => { print!("{}", HELP); return; }
            "-h" => { print!("{}", HELP_SHORT); return; }
            "-V" | "--version" => { println!("pdu {}", VERSION); return; }
            "-m" | "--min-ratio" => min_ratio = parse_min_ratio(&take(&mut i)),
            s if s.starts_with("--min-ratio=") => min_ratio = parse_min_ratio(&s[12..]),
            "--no-sort" => no_sort = true,
            "--json-output" => json_output = true,
            "--json-input" => json_input = true,
            "--top-down" => top_down = true,
            "--align-right" => align_right = true,
            "-H" | "--deduplicate-hardlinks" | "--detect-links" | "--dedupe-links" => dedup = true,
            "--omit-json-shared-details" => omit_details = true,
            "--omit-json-shared-summary" => omit_summary = true,
            "-s" | "--silent-errors" | "--no-errors" => silent = true,
            "-p" | "--progress" => {}
            "--threads" => { parse_threads(&take(&mut i)); }
            s if s.starts_with("--threads=") => { parse_threads(&s[10..]); }
            "--" => {
                // everything after `--` is a positional file, even if it starts with `-`
                i += 1;
                while i < args.len() {
                    files.push(args[i].clone());
                    i += 1;
                }
                break;
            }
            "-b" | "--bytes-format" => bytes_format = take(&mut i),
            "-q" | "--quantity" => { quantity = take(&mut i); quantity_set = true; }
            "-d" | "--max-depth" | "--depth" => max_depth = parse_max_depth(&take(&mut i)),
            "-w" | "--total-width" | "--width" => {
                total_width = Some(parse_uint(&take(&mut i), "--total-width <TOTAL_WIDTH>"))
            }
            "--column-width" => {
                let a = parse_uint(&take(&mut i), "--column-width <TREE_WIDTH> <BAR_WIDTH>");
                let b = parse_uint(&take(&mut i), "--column-width <TREE_WIDTH> <BAR_WIDTH>");
                col_widths = Some((a, b));
            }
            s if s.starts_with("--bytes-format=") => bytes_format = s[15..].to_string(),
            s if s.starts_with("--quantity=") => { quantity = s[11..].to_string(); quantity_set = true; }
            s if s.starts_with("--total-width=") => {
                total_width = Some(parse_uint(&s[14..], "--total-width <TOTAL_WIDTH>"))
            }
            s if s.starts_with("--width=") => {
                total_width = Some(parse_uint(&s[8..], "--total-width <TOTAL_WIDTH>"))
            }
            s if s.starts_with("--max-depth=") => max_depth = parse_max_depth(&s[12..]),
            s if s.starts_with("--depth=") => max_depth = parse_max_depth(&s[8..]),
            s if s == "-" || !s.starts_with('-') => files.push(s.to_string()),
            s => unknown_arg(s),
        }
        i += 1;
    }
    // conflict: --total-width cannot be used with --column-width
    if total_width.is_some() && col_widths.is_some() {
        eprint!(
            "error: the argument '--total-width <TOTAL_WIDTH>' cannot be used with '--column-width <TREE_WIDTH> <BAR_WIDTH>'\n\nUsage: executable --total-width <TOTAL_WIDTH> <FILES>...\n\nFor more information, try '--help'.\n"
        );
        std::process::exit(2);
    }
    // conflict: --json-input cannot be used with --quantity
    if json_input && quantity_set {
        eprint!(
            "error: the argument '--json-input' cannot be used with '--quantity <QUANTITY>'\n\nUsage: executable --json-input [FILES]...\n\nFor more information, try '--help'.\n"
        );
        std::process::exit(2);
    }
    // clap-style enum-value validation (exit 2). Reusable clap recipe (byte-identical to clap 4):
    // accepts canonical values + hidden aliases; on invalid, emits the [possible values] line and a
    // Jaro-Winkler>=0.8 "tip: a similar value exists" suggestion drawn only from the visible values.
    // --bytes-format: plain|metric|binary (no aliases)
    clap_enum_check(
        "--bytes-format <BYTES_FORMAT>",
        &bytes_format,
        &["plain", "metric", "binary"],
        &[],
    );
    // --quantity: apparent-size|block-size|block-count (+ aliases blocks->block-count, len->apparent-size)
    clap_enum_check(
        "--quantity <QUANTITY>",
        &quantity,
        &["apparent-size", "block-size", "block-count"],
        &["blocks", "len"],
    );
    // --omit-json-shared-{details,summary} require --json-output AND --deduplicate-hardlinks
    if omit_details || omit_summary {
        let mut missing: Vec<&str> = Vec::new();
        if !json_output {
            missing.push("--json-output");
        }
        if !dedup {
            missing.push("--deduplicate-hardlinks");
        }
        if !missing.is_empty() {
            let flag = if omit_details {
                "--omit-json-shared-details"
            } else {
                "--omit-json-shared-summary"
            };
            let mut msg = String::from("error: the following required arguments were not provided:\n");
            for m in &missing {
                msg.push_str(&format!("  {}\n", m));
            }
            msg.push_str(&format!(
                "\nUsage: executable {} {} <FILES>...\n\nFor more information, try '--help'.\n",
                missing.join(" "),
                flag
            ));
            eprint!("{}", msg);
            std::process::exit(2);
        }
    }
    // normalize quantity aliases to canonical
    let quantity = match quantity.as_str() {
        "blocks" => "block-count".to_string(),
        "len" => "apparent-size".to_string(),
        _ => quantity,
    };
    // --json-input conflicts with positional file args -> exit 4
    if json_input && !files.is_empty() {
        eprintln!("[error] JsonInputArgConflict: Arguments exist alongside --json-input");
        std::process::exit(4);
    }
    let eff_width = total_width.unwrap_or(150);

    // --json-input: read a JSON disk-usage tree from stdin and visualize it (sizes from JSON).
    if json_input {
        let mut buf = String::new();
        let _ = io::Read::read_to_string(&mut io::stdin(), &mut buf);
        match parse_json_tree(&buf) {
            Ok(root) => {
                render_root(root, top_down, min_ratio, max_depth, no_sort, &bytes_format, eff_width, col_widths, align_right);
                return;
            }
            Err(msg) => {
                eprintln!("[error] DeserializationFailure: {}", msg);
                std::process::exit(3);
            }
        }
    }

    if files.is_empty() {
        files.push(".".to_string());
    }
    let mut roots: Vec<Node> = Vec::new();
    for f in &files {
        let mut node = build_node(f, 0, &quantity, silent);
        node.name = f.clone(); // root node keeps the path exactly as given on the cmdline
        roots.push(node);
    }
    // single root common case
    if json_output {
        let out = json_tree(&roots[0]);
        print!("{}", out);
        return;
    }
    let mut root = roots.remove(0);
    render_root(root_take(&mut root), top_down, min_ratio, max_depth, no_sort, &bytes_format, eff_width, col_widths, align_right);
}

fn root_take(n: &mut Node) -> Node {
    std::mem::replace(n, Node { name: String::new(), size: 0, depth: 0, children: Vec::new() })
}

#[allow(clippy::too_many_arguments)]
fn render_root(
    mut root: Node,
    top_down: bool,
    min_ratio: f64,
    max_depth: usize,
    no_sort: bool,
    bytes_format: &str,
    eff_width: usize,
    col_widths: Option<(usize, usize)>,
    align_right: bool,
) {
    if !no_sort {
        sort_tree(&mut root);
    }
    let total = root.size.max(1);
    let mut rows: Vec<(String, String, Vec<(usize, f64)>, usize)> = Vec::new();
    let mut chain: Vec<(usize, f64)> = Vec::new();
    let mut ancestors: Vec<bool> = Vec::new();
    collect_rows(&root, total, max_depth, top_down, min_ratio, true, bytes_format, "", &mut ancestors, &mut chain, &mut rows);
    render(rows, eff_width, col_widths, align_right);
}

fn block_size(meta_len: u64, blocks_512: u64, quantity: &str) -> u64 {
    match quantity {
        "apparent-size" => meta_len,
        "block-count" => blocks_512,       // st_blocks: number of 512B blocks (8 for a 4K file)
        _ => blocks_512 * 512,             // block-size = block-count * 512
    }
}

fn build_node(path: &str, depth: usize, quantity: &str, silent: bool) -> Node {
    use std::os::unix::fs::MetadataExt;
    let name = std::path::Path::new(path)
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| path.to_string());
    let meta = match std::fs::symlink_metadata(path) {
        Ok(m) => Some(m),
        Err(e) => {
            if !silent {
                eprintln!("[error] symlink_metadata {:?}: {}", path, e);
            }
            None
        }
    };
    let mut children = Vec::new();
    let mut size: u64 = 0;
    if let Some(m) = &meta {
        // A directory contributes only the sum of its children -- NOT its own inode block/size.
        // PB goldens are generated on tmpfs (dir st_blocks=0), so children-only reproduces them
        // deterministically on ANY filesystem. Files use their own st_blocks/len.
        if !m.is_dir() {
            size = block_size(m.len(), m.blocks(), quantity);
        }
        if m.is_dir() {
            match std::fs::read_dir(path) {
                Ok(rd) => {
                    let mut entries: Vec<_> = rd.filter_map(|e| e.ok()).collect();
                    entries.sort_by_key(|e| e.file_name());
                    for e in entries {
                        let cp = e.path();
                        let child = build_node(&cp.to_string_lossy(), depth + 1, quantity, silent);
                        size += child.size;
                        children.push(child);
                    }
                }
                Err(e) => {
                    if !silent {
                        eprintln!("[error] read_dir {:?}: {}", path, e);
                    }
                }
            }
        }
    }
    Node { name, size, depth, children }
}

fn sort_tree(n: &mut Node) {
    for c in n.children.iter_mut() {
        sort_tree(c);
    }
    // siblings ascending by size (smallest first) for bottom-up post-order
    n.children.sort_by(|a, b| a.size.cmp(&b.size).then(a.name.cmp(&b.name)));
}

// --max-depth value parser: "inf" or a positive (non-zero) integer; clap-exact errors via the
// std NonZeroU64 FromStr error strings (zero/invalid-digit/overflow all reproduce byte-for-byte).
fn parse_max_depth(v: &str) -> usize {
    if v == "inf" {
        return usize::MAX;
    }
    match v.parse::<std::num::NonZeroU64>() {
        Ok(n) => n.get() as usize,
        Err(e) => {
            eprint!(
                "error: invalid value '{}' for '--max-depth <MAX_DEPTH>': Value is neither \"inf\" nor a positive integer: {}\n\nFor more information, try '--help'.\n",
                v, e
            );
            std::process::exit(2);
        }
    }
}

// Map an option token to its (canonical key, display name, takes_value, num_values). Positional
// args / values / `--` return None. Used to detect duplicate non-repeatable flags.
fn classify_flag(a: &str) -> Option<(&'static str, &'static str, bool, usize)> {
    let base = a.split('=').next().unwrap_or(a);
    Some(match base {
        "-m" | "--min-ratio" => ("min-ratio", "--min-ratio <MIN_RATIO>", true, 1),
        "--no-sort" => ("no-sort", "--no-sort", false, 0),
        "--json-output" => ("json-output", "--json-output", false, 0),
        "--json-input" => ("json-input", "--json-input", false, 0),
        "--top-down" => ("top-down", "--top-down", false, 0),
        "--align-right" => ("align-right", "--align-right", false, 0),
        "-H" | "--deduplicate-hardlinks" | "--detect-links" | "--dedupe-links" => {
            ("deduplicate-hardlinks", "--deduplicate-hardlinks", false, 0)
        }
        "--omit-json-shared-details" => ("omit-json-shared-details", "--omit-json-shared-details", false, 0),
        "--omit-json-shared-summary" => ("omit-json-shared-summary", "--omit-json-shared-summary", false, 0),
        "-s" | "--silent-errors" | "--no-errors" => ("silent-errors", "--silent-errors", false, 0),
        "-p" | "--progress" => ("progress", "--progress", false, 0),
        "--threads" => ("threads", "--threads <THREADS>", true, 1),
        "-b" | "--bytes-format" => ("bytes-format", "--bytes-format <BYTES_FORMAT>", true, 1),
        "-q" | "--quantity" => ("quantity", "--quantity <QUANTITY>", true, 1),
        "-d" | "--max-depth" | "--depth" => ("max-depth", "--max-depth <MAX_DEPTH>", true, 1),
        "-w" | "--total-width" | "--width" => ("total-width", "--total-width <TOTAL_WIDTH>", true, 1),
        "--column-width" => ("column-width", "--column-width <TREE_WIDTH> <BAR_WIDTH>", true, 2),
        _ => return None,
    })
}

// Return the display name of the first non-repeatable flag that appears more than once.
fn find_duplicate(args: &[String]) -> Option<&'static str> {
    let mut seen: Vec<&'static str> = Vec::new();
    let mut i = 1;
    while i < args.len() {
        let a = &args[i];
        if a == "--" {
            break; // remaining are positional
        }
        if let Some((key, disp, takes_val, nvals)) = classify_flag(a) {
            if seen.contains(&key) {
                return Some(disp);
            }
            seen.push(key);
            // skip space-form values so they aren't misread as flags
            if takes_val && !a.contains('=') {
                i += nvals;
            }
        }
        i += 1;
    }
    None
}

// --threads value parser: "auto" | "max" | positive (non-zero) integer. clap-exact errors.
fn parse_threads(v: &str) {
    if v == "auto" || v == "max" {
        return;
    }
    if let Err(e) = v.parse::<std::num::NonZeroU64>() {
        eprint!(
            "error: invalid value '{}' for '--threads <THREADS>': Value is neither \"auto\", \"max\", nor a number: {}\n\nFor more information, try '--help'.\n",
            v, e
        );
        std::process::exit(2);
    }
}

// Unrecognized argument -> clap "unexpected argument" error (exit 2).
fn unknown_arg(arg: &str) -> ! {
    eprint!(
        "error: unexpected argument '{}' found\n\n  tip: to pass '{}' as a value, use '-- {}'\n\nUsage: executable [OPTIONS] [FILES]...\n\nFor more information, try '--help'.\n",
        arg, arg, arg
    );
    std::process::exit(2);
}

// --min-ratio value parser: a fraction in [0, 1). clap-exact range error.
fn parse_min_ratio(v: &str) -> f64 {
    let bad = |reason: &str| -> ! {
        eprint!(
            "error: invalid value '{}' for '--min-ratio <MIN_RATIO>': {}\n\nFor more information, try '--help'.\n",
            v, reason
        );
        std::process::exit(2);
    };
    match v.parse::<f64>() {
        Ok(r) if r >= 1.0 => bad("greater than or equal to 1"),
        Ok(r) if r < 0.0 => bad("less than 0"),
        Ok(r) => r,
        Err(e) => bad(&e.to_string()),
    }
}

// Generic clap unsigned-int value parser; clap-exact error via std u64 FromStr error string.
fn parse_uint(v: &str, meta: &str) -> usize {
    match v.parse::<u64>() {
        Ok(n) => n as usize,
        Err(e) => {
            eprint!(
                "error: invalid value '{}' for '{}': {}\n\nFor more information, try '--help'.\n",
                v, meta, e
            );
            std::process::exit(2);
        }
    }
}

// clap 4 string similarity (strsim::jaro_winkler) used for "did you mean" value suggestions.
fn jaro(a: &str, b: &str) -> f64 {
    let s1: Vec<char> = a.chars().collect();
    let s2: Vec<char> = b.chars().collect();
    let (l1, l2) = (s1.len(), s2.len());
    if l1 == 0 && l2 == 0 {
        return 1.0;
    }
    if l1 == 0 || l2 == 0 {
        return 0.0;
    }
    let md = (l1.max(l2) / 2).saturating_sub(1);
    let mut m1 = vec![false; l1];
    let mut m2 = vec![false; l2];
    let mut m = 0usize;
    for i in 0..l1 {
        let lo = i.saturating_sub(md);
        let hi = (i + md + 1).min(l2);
        for j in lo..hi {
            if !m2[j] && s1[i] == s2[j] {
                m1[i] = true;
                m2[j] = true;
                m += 1;
                break;
            }
        }
    }
    if m == 0 {
        return 0.0;
    }
    let mut t = 0usize;
    let mut k = 0usize;
    for i in 0..l1 {
        if m1[i] {
            while !m2[k] {
                k += 1;
            }
            if s1[i] != s2[k] {
                t += 1;
            }
            k += 1;
        }
    }
    let m = m as f64;
    let t = (t / 2) as f64;
    (m / l1 as f64 + m / l2 as f64 + (m - t) / m) / 3.0
}

fn jaro_winkler(a: &str, b: &str) -> f64 {
    let j = jaro(a, b);
    let prefix = a
        .chars()
        .zip(b.chars())
        .take(4)
        .take_while(|(x, y)| x == y)
        .count();
    (j + 0.1 * prefix as f64 * (1.0 - j)).clamp(0.0, 1.0)
}

// Validate a clap value-enum arg; exit(2) with a byte-exact clap error (+ optional tip) if invalid.
fn clap_enum_check(meta: &str, value: &str, possible: &[&str], aliases: &[&str]) {
    if possible.contains(&value) || aliases.contains(&value) {
        return;
    }
    let mut best: Option<(f64, &str)> = None;
    for &p in possible {
        let s = jaro_winkler(value, p);
        if s > 0.8 && best.map(|(bs, _)| s > bs).unwrap_or(true) {
            best = Some((s, p));
        }
    }
    let mut msg = format!(
        "error: invalid value '{}' for '{}'\n  [possible values: {}]\n",
        value,
        meta,
        possible.join(", ")
    );
    if let Some((_, sug)) = best {
        msg.push_str(&format!("\n  tip: a similar value exists: '{}'\n", sug));
    }
    msg.push_str("\nFor more information, try '--help'.\n");
    eprint!("{}", msg);
    std::process::exit(2);
}

// Visible children of `n`: pass max-depth + min-ratio filters. Returned in DISPLAY order
// (bottom-up: ascending by size; top-down: descending). Sort already applied to n.children
// ascending, so we just reverse for top-down.
fn visible_children<'a>(
    n: &'a Node,
    total: u64,
    max_depth: usize,
    min_ratio: f64,
    top_down: bool,
) -> Vec<&'a Node> {
    // pdu depth is 1-based (root = depth 1); our root is depth 0, so a child at our-depth d is
    // shown iff d < max_depth (e.g. --max-depth 1 => root only; --max-depth 2 => root + children).
    let mut v: Vec<&Node> = n
        .children
        .iter()
        .filter(|c| c.depth < max_depth && (c.size as f64 / total as f64) >= min_ratio)
        .collect();
    if top_down {
        v.reverse();
    }
    v
}

// Recursive tree renderer. `ancestors[k]` = whether the spine of the ancestor at depth k is drawn
// (│) at this node's rows -- true iff that ancestor is NOT the "corner" node of its sibling group.
// `is_corner` = this node is drawn at the open corner of its group: bottom-up that's the FIRST
// (topmost/smallest) child -> ┌; top-down that's the LAST (bottommost/smallest) child -> └. Root
// is always a corner. Non-corner siblings get ├.
#[allow(clippy::too_many_arguments)]
fn collect_rows(
    n: &Node,
    total: u64,
    max_depth: usize,
    top_down: bool,
    min_ratio: f64,
    is_corner: bool,
    bf: &str,
    _q: &str,
    ancestors: &mut Vec<bool>,
    chain: &mut Vec<(usize, f64)>,
    out: &mut Vec<(String, String, Vec<(usize, f64)>, usize)>,
) {
    let vis = visible_children(n, total, max_depth, min_ratio, top_down);
    let has_kids = !vis.is_empty();

    // prefix: one 2-char segment per ancestor (│ if its spine is drawn, else blank)
    let mut cell = String::new();
    for &a in ancestors.iter() {
        cell.push_str(if a { "│ " } else { "  " });
    }
    // own connector
    cell.push(if is_corner {
        if top_down { '└' } else { '┌' }
    } else {
        '├'
    });
    cell.push_str(if !has_kids {
        "──"
    } else if top_down {
        "─┬"
    } else {
        "─┴"
    });
    cell.push_str(&n.name);
    let row = (fmt_size(n.size, bf), cell, chain.clone(), n.depth);

    let n_vis = vis.len();
    let mut recurse = |out: &mut Vec<(String, String, Vec<(usize, f64)>, usize)>,
                       ancestors: &mut Vec<bool>,
                       chain: &mut Vec<(usize, f64)>| {
        for (idx, c) in vis.iter().enumerate() {
            // corner child: first-drawn (bottom-up) or last-drawn (top-down)
            let c_corner = if top_down { idx == n_vis - 1 } else { idx == 0 };
            ancestors.push(!is_corner); // this node's spine, as seen by its descendants
            chain.push((c.depth, c.size as f64 / total as f64));
            collect_rows(
                c, total, max_depth, top_down, min_ratio, c_corner, bf, _q, ancestors, chain, out,
            );
            chain.pop();
            ancestors.pop();
        }
    };

    if top_down {
        out.push(row);
        recurse(out, ancestors, chain);
    } else {
        recurse(out, ancestors, chain);
        out.push(row);
    }
}

fn fmt_size(sz: u64, bf: &str) -> String {
    match bf {
        "plain" => format!("{}", sz),
        "binary" => fmt_scaled(sz, 1024),
        _ => fmt_scaled(sz, 1000),
    }
}

fn fmt_scaled(sz: u64, base: u64) -> String {
    let units = ["", "K", "M", "G", "T", "P"];
    let mut v = sz as f64;
    let mut u = 0;
    while v >= base as f64 && u < units.len() - 1 {
        v /= base as f64;
        u += 1;
    }
    if u == 0 {
        format!("{}", sz)
    } else {
        format!("{:.1}{}", v, units[u])
    }
}

fn dwidth(s: &str) -> usize {
    s.chars().count()
}

fn render(
    rows: Vec<(String, String, Vec<(usize, f64)>, usize)>,
    total_width: usize,
    col_widths: Option<(usize, usize)>,
    align_right: bool,
) {
    let sizew = rows.iter().map(|r| r.0.chars().count()).max().unwrap_or(1);
    let namew = rows.iter().map(|r| dwidth(&r.1)).max().unwrap_or(1);
    // bar width: explicit via --column-width, else derived from total-width; floored at 3.
    let barw = match col_widths {
        Some((_, b)) => b.max(1),
        None => total_width
            .saturating_sub(sizew + 1 + namew + 1 + 1 + 4)
            .max(3),
    };
    let so = io::stdout();
    let mut o = so.lock();
    for (sz, cell, chain, _depth) in &rows {
        let pad = namew.saturating_sub(dwidth(cell));
        let mut bar = make_bar(chain, barw);
        if align_right {
            // --align-right roots the bar on the right: mirror the band string
            bar = bar.chars().rev().collect();
        }
        let self_ratio = chain.last().map(|c| c.1).unwrap_or(1.0);
        let pct = (self_ratio * 100.0).round() as i64;
        let _ = write!(
            o,
            "{:>sw$} {}{}│{}│{:>3}%\n",
            sz, cell, " ".repeat(pad), bar, pct, sw = sizew
        );
    }
}

fn shade(depth: usize) -> char {
    match depth {
        1 => '░',
        2 => '▒',
        _ => '▓',
    }
}

// Multi-shade nested bar: chain = [(depth1,r1),..,(self_depth,r_self)] (ratios DESC, self last).
// self band = █ (0..self%); each ancestor band extends to its % with shade(depth); root excluded.
fn make_bar(chain: &[(usize, f64)], width: usize) -> String {
    if chain.is_empty() {
        return std::iter::repeat('█').take(width).collect();
    }
    let mut cells = vec![' '; width];
    let mut pos = 0usize;
    let last = chain.len() - 1;
    for (k, &(d, r)) in chain.iter().enumerate().rev() {
        let boundary = ((r * width as f64).round() as usize).min(width);
        let ch = if k == last { '█' } else { shade(d) };
        let mut c = pos;
        while c < boundary {
            cells[c] = ch;
            c += 1;
        }
        pos = pos.max(boundary);
    }
    cells.into_iter().collect()
}

// ---- minimal JSON parser for --json-input (no crates) -------------------------------------
// Produces serde_json-compatible error text for the common malformed cases (EOF / expected ident
// / invalid top-level type) so the exit-3 path matches the reference where it cheaply can.
enum JVal {
    Str(String),
    Num(f64),
    Bool(bool),
    Null,
    Arr(Vec<JVal>),
    Obj(Vec<(String, JVal)>),
}

struct JParser<'a> {
    c: &'a [char],
    i: usize,
}

impl<'a> JParser<'a> {
    fn col1(&self, idx: usize) -> (usize, usize) {
        let mut line = 1;
        let mut last_nl = 0usize;
        for k in 0..idx.min(self.c.len()) {
            if self.c[k] == '\n' {
                line += 1;
                last_nl = k + 1;
            }
        }
        (line, idx - last_nl + 1)
    }
    fn skip_ws(&mut self) {
        while self.i < self.c.len() && matches!(self.c[self.i], ' ' | '\t' | '\n' | '\r') {
            self.i += 1;
        }
    }
    fn parse_value(&mut self) -> Result<JVal, String> {
        self.skip_ws();
        if self.i >= self.c.len() {
            let (l, _) = self.col1(self.i);
            // serde reports column 0 at end-of-input for an empty document
            return Err(format!("EOF while parsing a value at line {} column {}", l, self.i.saturating_sub(line_start(self.c, self.i))));
        }
        match self.c[self.i] {
            '{' => self.parse_obj(),
            '[' => self.parse_arr(),
            '"' => Ok(JVal::Str(self.parse_str()?)),
            '-' | '0'..='9' => self.parse_num(),
            't' => self.parse_lit("true", JVal::Bool(true)),
            'f' => self.parse_lit("false", JVal::Bool(false)),
            'n' => self.parse_lit("null", JVal::Null),
            _ => {
                let (l, col) = self.col1(self.i);
                Err(format!("expected value at line {} column {}", l, col))
            }
        }
    }
    fn parse_lit(&mut self, word: &str, v: JVal) -> Result<JVal, String> {
        for (k, wc) in word.chars().enumerate() {
            if self.i + k >= self.c.len() || self.c[self.i + k] != wc {
                let (l, col) = self.col1(self.i + k);
                return Err(format!("expected ident at line {} column {}", l, col));
            }
        }
        self.i += word.len();
        Ok(v)
    }
    fn parse_str(&mut self) -> Result<String, String> {
        self.i += 1; // opening quote
        let mut s = String::new();
        while self.i < self.c.len() {
            let ch = self.c[self.i];
            self.i += 1;
            match ch {
                '"' => return Ok(s),
                '\\' => {
                    if self.i >= self.c.len() {
                        break;
                    }
                    let e = self.c[self.i];
                    self.i += 1;
                    s.push(match e {
                        'n' => '\n',
                        't' => '\t',
                        'r' => '\r',
                        '"' => '"',
                        '\\' => '\\',
                        '/' => '/',
                        'b' => '\u{8}',
                        'f' => '\u{c}',
                        'u' => {
                            let mut code = 0u32;
                            for _ in 0..4 {
                                if self.i < self.c.len() {
                                    code = code * 16 + self.c[self.i].to_digit(16).unwrap_or(0);
                                    self.i += 1;
                                }
                            }
                            char::from_u32(code).unwrap_or('\u{fffd}')
                        }
                        other => other,
                    });
                }
                _ => s.push(ch),
            }
        }
        let (l, col) = self.col1(self.i);
        Err(format!("EOF while parsing a string at line {} column {}", l, col))
    }
    fn parse_num(&mut self) -> Result<JVal, String> {
        let start = self.i;
        if self.c[self.i] == '-' {
            self.i += 1;
        }
        while self.i < self.c.len() && matches!(self.c[self.i], '0'..='9' | '.' | 'e' | 'E' | '+' | '-') {
            self.i += 1;
        }
        let s: String = self.c[start..self.i].iter().collect();
        s.parse::<f64>()
            .map(JVal::Num)
            .map_err(|_| format!("invalid number at line {} column {}", self.col1(start).0, self.col1(start).1))
    }
    fn parse_arr(&mut self) -> Result<JVal, String> {
        self.i += 1; // [
        let mut v = Vec::new();
        self.skip_ws();
        if self.i < self.c.len() && self.c[self.i] == ']' {
            self.i += 1;
            return Ok(JVal::Arr(v));
        }
        loop {
            v.push(self.parse_value()?);
            self.skip_ws();
            if self.i >= self.c.len() {
                break;
            }
            match self.c[self.i] {
                ',' => {
                    self.i += 1;
                }
                ']' => {
                    self.i += 1;
                    return Ok(JVal::Arr(v));
                }
                _ => break,
            }
        }
        let (l, col) = self.col1(self.i);
        Err(format!("EOF while parsing a list at line {} column {}", l, col))
    }
    fn parse_obj(&mut self) -> Result<JVal, String> {
        self.i += 1; // {
        let mut fields = Vec::new();
        self.skip_ws();
        if self.i < self.c.len() && self.c[self.i] == '}' {
            self.i += 1;
            return Ok(JVal::Obj(fields));
        }
        loop {
            self.skip_ws();
            if self.i >= self.c.len() || self.c[self.i] != '"' {
                let (l, col) = self.col1(self.i);
                return Err(format!("key must be a string at line {} column {}", l, col));
            }
            let key = self.parse_str()?;
            self.skip_ws();
            if self.i >= self.c.len() || self.c[self.i] != ':' {
                let (l, col) = self.col1(self.i);
                return Err(format!("expected `:` at line {} column {}", l, col));
            }
            self.i += 1;
            let val = self.parse_value()?;
            fields.push((key, val));
            self.skip_ws();
            if self.i >= self.c.len() {
                break;
            }
            match self.c[self.i] {
                ',' => {
                    self.i += 1;
                }
                '}' => {
                    self.i += 1;
                    return Ok(JVal::Obj(fields));
                }
                _ => break,
            }
        }
        let (l, col) = self.col1(self.i);
        Err(format!("EOF while parsing an object at line {} column {}", l, col))
    }
}

fn line_start(c: &[char], idx: usize) -> usize {
    let mut ls = 0;
    for k in 0..idx.min(c.len()) {
        if c[k] == '\n' {
            ls = k + 1;
        }
    }
    ls
}

fn jtype_desc(v: &JVal) -> String {
    match v {
        JVal::Str(_) => "string".to_string(),
        JVal::Num(n) => format!("integer `{}`", *n as i64),
        JVal::Bool(b) => format!("boolean `{}`", b),
        JVal::Null => "null".to_string(),
        JVal::Arr(_) => "sequence".to_string(),
        JVal::Obj(_) => "map".to_string(),
    }
}

// Parse the json-output document and build a Node tree from its `.tree` field.
fn parse_json_tree(s: &str) -> Result<Node, String> {
    let chars: Vec<char> = s.chars().collect();
    let mut p = JParser { c: &chars, i: 0 };
    let v = p.parse_value()?;
    match v {
        JVal::Obj(fields) => {
            if let Some((_, tv)) = fields.iter().find(|(k, _)| k == "tree") {
                build_json_node(tv, 0)
            } else {
                Err("missing field `schema-version` at line 1 column 2".to_string())
            }
        }
        other => Err(format!(
            "invalid type: {}, expected struct JsonData at line 1 column 1",
            jtype_desc(&other)
        )),
    }
}

fn build_json_node(v: &JVal, depth: usize) -> Result<Node, String> {
    if let JVal::Obj(fields) = v {
        let name = match fields.iter().find(|(k, _)| k == "name") {
            Some((_, JVal::Str(s))) => s.clone(),
            _ => return Err("missing field `name` at line 1 column 1".to_string()),
        };
        let size = match fields.iter().find(|(k, _)| k == "size") {
            Some((_, JVal::Num(n))) => *n as u64,
            _ => return Err("missing field `size` at line 1 column 1".to_string()),
        };
        let mut children = Vec::new();
        if let Some((_, JVal::Arr(arr))) = fields.iter().find(|(k, _)| k == "children") {
            for c in arr {
                children.push(build_json_node(c, depth + 1)?);
            }
        }
        Ok(Node { name, size, depth, children })
    } else {
        Err("invalid type: expected struct Tree at line 1 column 1".to_string())
    }
}

#[allow(dead_code)]
fn json_tree(n: &Node) -> String {
    fn rec(n: &Node, s: &mut String) {
        s.push_str(&format!("{{\"name\":{},\"size\":{},\"children\":[", json_str(&n.name), n.size));
        for (i, c) in n.children.iter().enumerate() {
            if i > 0 {
                s.push(',');
            }
            rec(c, s);
        }
        s.push_str("]}");
    }
    let mut s = String::from(concat!(
        "{\"schema-version\":\"2024-11-02\",\"pdu\":\""
    ));
    s.push_str(VERSION);
    s.push_str("\",\"unit\":\"bytes\",\"tree\":");
    let mut t = String::new();
    rec(n, &mut t);
    s.push_str(&t);
    s.push('}');
    s
}

fn json_str(x: &str) -> String {
    let mut s = String::from("\"");
    for c in x.chars() {
        match c {
            '"' => s.push_str("\\\""),
            '\\' => s.push_str("\\\\"),
            '\n' => s.push_str("\\n"),
            _ => s.push(c),
        }
    }
    s.push('"');
    s
}

fn _unused(_: &mut dyn Write) {}
