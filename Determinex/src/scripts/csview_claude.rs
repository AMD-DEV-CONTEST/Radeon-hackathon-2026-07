// csview reimplementation (Claude-tier, native Rust, no external crates).
// Reverse-engineered black-box from the reference binary via Determinex's oracle diffs.
use std::io::{self, Read};

const VERSION: &str = "csview 1.3.4";
const USAGE: &str = "Usage: executable [OPTIONS] [FILE]\n";
const TRY: &str = "\nFor more information, try '--help'.\n";

fn arg_err(msg: String) -> ! {
    eprint!("{}", msg);
    std::process::exit(2);
}
fn unexpected(arg: &str, tip: bool) -> ! {
    let mut m = format!("error: unexpected argument '{}' found\n\n", arg);
    if tip {
        m += &format!("  tip: to pass '{}' as a value, use '-- {}'\n\n", arg, arg);
    }
    m += USAGE;
    m += TRY;
    arg_err(m)
}
fn conflict(first: &str, second: &str) -> ! {
    arg_err(format!(
        "error: the argument '{}' cannot be used with '{}'\n\nUsage: executable {} [FILE]\n{}",
        first, second, first, TRY
    ))
}
fn missing_value(spec: &str) -> ! {
    arg_err(format!(
        "error: a value is required for '{}' but none was supplied\n{}",
        spec, TRY
    ))
}
fn invalid_enum(v: &str, spec: &str, vals: &str) -> ! {
    arg_err(format!(
        "error: invalid value '{}' for '{}'\n  [possible values: {}]\n{}",
        v, spec, vals, TRY
    ))
}
fn invalid_parse(v: &str, spec: &str, reason: &str) -> ! {
    arg_err(format!(
        "error: invalid value '{}' for '{}': {}\n{}",
        v, spec, reason, TRY
    ))
}
fn parse_char(v: &str, spec: &str) -> char {
    let mut it = v.chars();
    match (it.next(), it.next()) {
        (None, _) => invalid_parse(v, spec, "cannot parse char from empty string"),
        (Some(c), None) => c,
        (Some(_), Some(_)) => invalid_parse(v, spec, "too many characters in string"),
    }
}
fn parse_uint(v: &str, spec: &str) -> usize {
    if v.is_empty() {
        invalid_parse(v, spec, "cannot parse integer from empty string");
    }
    match v.parse::<usize>() {
        Ok(n) => n,
        Err(_) => invalid_parse(v, spec, "invalid digit found in string"),
    }
}
fn parse_style(v: &str) -> String {
    let lv = v.to_lowercase();
    const VALS: [&str; 8] = [
        "none", "ascii", "ascii2", "sharp", "rounded", "reinforced", "markdown", "grid",
    ];
    if VALS.contains(&lv.as_str()) {
        lv
    } else {
        invalid_enum(
            v,
            "--style <STYLE>",
            "none, ascii, ascii2, sharp, rounded, reinforced, markdown, grid",
        )
    }
}
fn parse_align(v: &str, spec: &str) -> String {
    let lv = v.to_lowercase();
    if ["left", "center", "right"].contains(&lv.as_str()) {
        lv
    } else {
        invalid_enum(v, spec, "left, center, right")
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut file: Option<String> = None;
    let mut no_headers = false;
    let mut number = false;
    let mut delimiter = ',';
    let mut style = String::from("sharp");
    let mut padding: usize = 1;
    let mut indent: usize = 0;
    let mut header_align = String::from("center");
    let mut body_align = String::from("left");

    let mut sniff: usize = 1000;
    let mut tsv_set = false;
    let mut delim_set = false;
    let mut positionals: Vec<String> = Vec::new();
    let mut rest_pos = false;
    let mut i = 1;
    while i < args.len() {
        let a = args[i].clone();
        if rest_pos {
            positionals.push(a);
            i += 1;
            continue;
        }
        if a == "--" {
            rest_pos = true;
            i += 1;
            continue;
        }
        if a.starts_with("--") {
            let (key, inline) = match a.find('=') {
                Some(p) => (a[..p].to_string(), Some(a[p + 1..].to_string())),
                None => (a.clone(), None),
            };
            macro_rules! val {
                ($spec:expr) => {{
                    if let Some(v) = inline.clone() {
                        v
                    } else {
                        match args.get(i + 1) {
                            Some(s) if !(s.starts_with('-') && s.len() > 1) => {
                                i += 1;
                                s.clone()
                            }
                            _ => missing_value($spec),
                        }
                    }
                }};
            }
            match key.as_str() {
                "--help" => {
                    print!("{}", help_text());
                    return;
                }
                "--version" => {
                    println!("{}", VERSION);
                    return;
                }
                "--no-headers" => no_headers = true,
                "--number" | "--seq" => number = true,
                "--tsv" => {
                    if delim_set {
                        conflict("--delimiter <DELIMITER>", "--tsv");
                    }
                    tsv_set = true;
                    delimiter = '\t';
                }
                "--disable-pager" => {}
                "--delimiter" => {
                    if tsv_set {
                        conflict("--tsv", "--delimiter <DELIMITER>");
                    }
                    delim_set = true;
                    delimiter = parse_char(&val!("--delimiter <DELIMITER>"), "--delimiter <DELIMITER>")
                }
                "--style" => style = parse_style(&val!("--style <STYLE>")),
                "--padding" => padding = parse_uint(&val!("--padding <PADDING>"), "--padding <PADDING>"),
                "--indent" => indent = parse_uint(&val!("--indent <INDENT>"), "--indent <INDENT>"),
                "--sniff" => sniff = parse_uint(&val!("--sniff <LIMIT>"), "--sniff <LIMIT>"),
                "--header-align" => {
                    header_align = parse_align(&val!("--header-align <HEADER_ALIGN>"),
                                               "--header-align <HEADER_ALIGN>")
                }
                "--body-align" => {
                    body_align = parse_align(&val!("--body-align <BODY_ALIGN>"),
                                             "--body-align <BODY_ALIGN>")
                }
                _ => unexpected(&a, true),
            }
        } else if a.starts_with('-') && a != "-" {
            let cs: Vec<char> = a[1..].chars().collect();
            let mut k = 0;
            while k < cs.len() {
                let c = cs[k];
                match c {
                    'h' => {
                        print!("{}", help_text());
                        return;
                    }
                    'V' => {
                        println!("{}", VERSION);
                        return;
                    }
                    'H' => no_headers = true,
                    'n' => number = true,
                    't' => {
                        if delim_set {
                            conflict("--delimiter <DELIMITER>", "--tsv");
                        }
                        tsv_set = true;
                        delimiter = '\t';
                    }
                    'P' => {}
                    'd' | 's' | 'p' | 'i' => {
                        let spec = match c {
                            'd' => "--delimiter <DELIMITER>",
                            's' => "--style <STYLE>",
                            'p' => "--padding <PADDING>",
                            _ => "--indent <INDENT>",
                        };
                        let after: String = cs[k + 1..].iter().collect();
                        let v = if !after.is_empty() {
                            // inline value; clap strips a single leading '=' for short flags
                            if let Some(s) = after.strip_prefix('=') {
                                s.to_string()
                            } else {
                                after
                            }
                        } else {
                            match args.get(i + 1) {
                                Some(s) if !(s.starts_with('-') && s.len() > 1) => {
                                    i += 1;
                                    s.clone()
                                }
                                _ => missing_value(spec),
                            }
                        };
                        match c {
                            'd' => {
                                if tsv_set {
                                    conflict("--tsv", "--delimiter <DELIMITER>");
                                }
                                delim_set = true;
                                delimiter = parse_char(&v, spec);
                            }
                            's' => style = parse_style(&v),
                            'p' => padding = parse_uint(&v, spec),
                            _ => indent = parse_uint(&v, spec),
                        }
                        break;
                    }
                    _ => unexpected(&format!("-{}", c), true),
                }
                k += 1;
            }
        } else {
            positionals.push(a);
        }
        i += 1;
    }
    if positionals.len() > 1 {
        unexpected(&positionals[1], false);
    }
    file = positionals.into_iter().next();

    let bytes: Vec<u8> = match &file {
        Some(f) if f != "-" => match std::fs::read(f) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("csview: {}", e);
                std::process::exit(1);
            }
        },
        _ => {
            let mut b = Vec::new();
            io::stdin().read_to_end(&mut b).ok();
            b
        }
    };
    // csview parses via the csv crate -> non-UTF-8 input is a hard error (exit 1).
    let input = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("{}", utf8_error_msg(e.as_bytes(), delimiter));
            std::process::exit(1);
        }
    };

    let (mut records, starts) = parse_csv(&input, delimiter);
    // csv crate default: every record must have the SAME field count as the first; a ragged
    // record is a hard error (exit 1, no stdout) with the offending record's line/byte.
    if let Some(first) = records.first() {
        let expected = first.len();
        for (i, r) in records.iter().enumerate().skip(1) {
            if r.len() != expected {
                let (b, l) = starts[i];
                eprintln!(
                    "csview: CSV error: record {} (line: {}, byte: {}): found record with {} fields, but the previous record has {} fields",
                    i, l, b, r.len(), expected
                );
                std::process::exit(1);
            }
        }
    }

    // header vs body
    let has_header = !no_headers;
    let mut header: Vec<String> = Vec::new();
    let mut body: Vec<Vec<String>> = Vec::new();
    if has_header {
        if !records.is_empty() {
            header = records.remove(0);
        }
        body = records;
    } else {
        body = records;
    }

    // number column
    if number {
        if has_header {
            header.insert(0, "#".to_string());
        }
        for (idx, row) in body.iter_mut().enumerate() {
            row.insert(0, (idx + 1).to_string());
        }
    }

    let out = render(
        &header,
        &body,
        has_header,
        &style,
        padding,
        indent,
        &header_align,
        &body_align,
        sniff,
    );
    print!("{}", out);
}

// ---- CSV parser (replicates the csv crate's default quote quirk) ----
fn utf8_error_msg(orig: &[u8], delim: char) -> String {
    let vu = std::str::from_utf8(orig)
        .err()
        .map(|e| e.valid_up_to())
        .unwrap_or(0);
    let prefix = std::str::from_utf8(&orig[..vu]).unwrap_or("");
    let mut rec_done = 0usize;
    let mut line = 1usize;
    let mut field_idx = 0usize;
    let mut rec_start = 0usize;
    let mut field_start = 0usize;
    let mut fresh = true;
    for (b, c) in prefix.char_indices() {
        if fresh {
            rec_start = b;
            field_start = b;
            fresh = false;
        }
        if c == delim {
            field_idx += 1;
            field_start = b + c.len_utf8();
        } else if c == '\n' {
            rec_done += 1;
            field_idx = 0;
            line += 1;
            fresh = true;
        }
    }
    let within = vu.saturating_sub(field_start);
    format!(
        "csview: CSV parse error: record {} (line {}, field: {}, byte: {}): invalid utf-8: invalid UTF-8 in field {} near byte index {}",
        rec_done, line, field_idx, rec_start, field_idx, within
    )
}

fn parse_csv(input: &str, delim: char) -> (Vec<Vec<String>>, Vec<(usize, usize)>) {
    #[derive(PartialEq)]
    enum St {
        Start,
        Unq,
        Q,
        AfterQ,
    }
    let chars: Vec<(usize, char)> = input.char_indices().collect();
    let mut records: Vec<Vec<String>> = Vec::new();
    let mut starts: Vec<(usize, usize)> = Vec::new(); // (byte, line) per record
    let mut rec: Vec<String> = Vec::new();
    let mut field = String::new();
    let mut st = St::Start;
    let mut line = 1usize;
    let mut need_start = true;
    let mut cur_start = (0usize, 1usize);

    macro_rules! end_field {
        () => {{
            rec.push(std::mem::take(&mut field));
        }};
    }
    macro_rules! end_record {
        () => {{
            end_field!();
            records.push(std::mem::take(&mut rec));
            starts.push(cur_start);
            need_start = true;
        }};
    }

    let mut idx = 0;
    while idx < chars.len() {
        let (bpos, ch) = chars[idx];
        if need_start {
            cur_start = (bpos, line);
            need_start = false;
        }
        match st {
            St::Start => {
                if ch == '"' {
                    st = St::Q;
                } else if ch == delim {
                    end_field!();
                } else if ch == '\n' || ch == '\r' {
                    if rec.is_empty() && field.is_empty() {
                        need_start = true; // blank line -> skipped (csv crate)
                    } else {
                        end_record!();
                    }
                } else {
                    field.push(ch);
                    st = St::Unq;
                }
            }
            St::Unq => {
                if ch == delim {
                    end_field!();
                    st = St::Start;
                } else if ch == '\n' || ch == '\r' {
                    end_record!();
                    st = St::Start;
                } else {
                    field.push(ch);
                }
            }
            St::Q => {
                if ch == '"' {
                    if chars.get(idx + 1).map(|x| x.1) == Some('"') {
                        field.push('"');
                        idx += 1;
                    } else {
                        st = St::AfterQ;
                    }
                } else {
                    field.push(ch);
                }
            }
            St::AfterQ => {
                if ch == delim {
                    end_field!();
                    st = St::Start;
                } else if ch == '\n' || ch == '\r' {
                    end_record!();
                    st = St::Start;
                } else {
                    field.push(ch);
                    st = St::Unq;
                }
            }
        }
        if ch == '\n' {
            line += 1;
        }
        idx += 1;
    }
    if st != St::Start || !field.is_empty() || !rec.is_empty() {
        rec.push(field);
        records.push(rec);
        starts.push(cur_start);
    }
    (records, starts)
}

// ---- display width: matches csview's unicode-width 0.2.x (default/non-CJK) byte-exact.
// Range tables empirically measured against the reference binary (Determinex oracle).
fn in_ranges(cp: u32, ranges: &[(u32, u32)]) -> bool {
    ranges
        .binary_search_by(|&(lo, hi)| {
            if cp < lo {
                std::cmp::Ordering::Greater
            } else if cp > hi {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

fn cw0(cp: u32) -> bool {
    const Z: &[(u32, u32)] = &[
        (0x00AD, 0x00AD),
        (0x0300, 0x036F),
        (0x0483, 0x0489),
        (0x0591, 0x05BD),
        (0x05BF, 0x05BF),
        (0x05C1, 0x05C2),
        (0x05C4, 0x05C5),
        (0x05C7, 0x05C7),
        (0x0610, 0x061A),
        (0x061C, 0x061C),
        (0x064B, 0x065F),
        (0x0670, 0x0670),
        (0x06D6, 0x06DC),
        (0x06DF, 0x06E4),
        (0x06E7, 0x06E8),
        (0x06EA, 0x06ED),
        (0x0711, 0x0711),
        (0x0730, 0x074A),
        (0x07A6, 0x07B0),
        (0x07EB, 0x07F3),
        (0x07FD, 0x07FD),
        (0x1AB0, 0x1AFF),
        (0x1DC0, 0x1DFF),
        (0x200B, 0x200F),
        (0x202A, 0x202E),
        (0x2060, 0x2064),
        (0x2066, 0x206F),
        (0x20D0, 0x20F0),
        (0xFE00, 0xFE0F),
        (0xFE20, 0xFE2F),
        (0xE0100, 0xE01EF),
    ];
    in_ranges(cp, Z)
}

fn cw2(cp: u32) -> bool {
    const W: &[(u32, u32)] = &[
        (0x00A1, 0x00A1),
        (0x00A4, 0x00A4),
        (0x00A7, 0x00A7),
        (0x00AE, 0x00AE),
        (0x00B0, 0x00B3),
        (0x00B6, 0x00B7),
        (0x00B9, 0x00B9),
        (0x00BC, 0x00BF),
        (0x00D7, 0x00D7),
        (0x00F7, 0x00F7),
        (0x0387, 0x0387),
        (0x1100, 0x115F),
        (0x2010, 0x2010),
        (0x2013, 0x2016),
        (0x2018, 0x2019),
        (0x201C, 0x201D),
        (0x2020, 0x2022),
        (0x2024, 0x2027),
        (0x2030, 0x2030),
        (0x2032, 0x2033),
        (0x2035, 0x2035),
        (0x203B, 0x203B),
        (0x203E, 0x203E),
        (0x2074, 0x2074),
        (0x2081, 0x2084),
        (0x2103, 0x2103),
        (0x2105, 0x2105),
        (0x2109, 0x2109),
        (0x2113, 0x2113),
        (0x2116, 0x2116),
        (0x2121, 0x2122),
        (0x2126, 0x2126),
        (0x212B, 0x212B),
        (0x2153, 0x2154),
        (0x215B, 0x215E),
        (0x2160, 0x216B),
        (0x2170, 0x2179),
        (0x2189, 0x2189),
        (0x2190, 0x219B),
        (0x21AE, 0x21AE),
        (0x21B8, 0x21B9),
        (0x21CE, 0x21CF),
        (0x21D2, 0x21D2),
        (0x21D4, 0x21D4),
        (0x21E7, 0x21E7),
        (0x2200, 0x2200),
        (0x2202, 0x2203),
        (0x2207, 0x2208),
        (0x220B, 0x220B),
        (0x220F, 0x220F),
        (0x2211, 0x2211),
        (0x2215, 0x2215),
        (0x221A, 0x221A),
        (0x221D, 0x2220),
        (0x2223, 0x2223),
        (0x2225, 0x2225),
        (0x2227, 0x222C),
        (0x222E, 0x222E),
        (0x2234, 0x2237),
        (0x223C, 0x223D),
        (0x2248, 0x2248),
        (0x224C, 0x224C),
        (0x2252, 0x2252),
        (0x2260, 0x2261),
        (0x2264, 0x2267),
        (0x226A, 0x226B),
        (0x226E, 0x226F),
        (0x2282, 0x2283),
        (0x2286, 0x2287),
        (0x2295, 0x2295),
        (0x2299, 0x2299),
        (0x22A5, 0x22A5),
        (0x22BF, 0x22BF),
        (0x2312, 0x2312),
        (0x2329, 0x232A),
        (0x2460, 0x24E9),
        (0x24EB, 0x254B),
        (0x2550, 0x2573),
        (0x2580, 0x258F),
        (0x2592, 0x2595),
        (0x25A0, 0x25A1),
        (0x25A3, 0x25A9),
        (0x25B2, 0x25B3),
        (0x25B6, 0x25B7),
        (0x25BC, 0x25BD),
        (0x25C0, 0x25C1),
        (0x25C6, 0x25C8),
        (0x25CB, 0x25CB),
        (0x25CE, 0x25D1),
        (0x25E2, 0x25E5),
        (0x25EF, 0x25EF),
        (0x25FD, 0x25FE),
        (0x2605, 0x2606),
        (0x2609, 0x2609),
        (0x260E, 0x260F),
        (0x2614, 0x2615),
        (0x261C, 0x261C),
        (0x261E, 0x261E),
        (0x2640, 0x2640),
        (0x2642, 0x2642),
        (0x2648, 0x2653),
        (0x2660, 0x2661),
        (0x2663, 0x2665),
        (0x2667, 0x266A),
        (0x266C, 0x266D),
        (0x266F, 0x266F),
        (0x267F, 0x267F),
        (0x2693, 0x2693),
        (0x269E, 0x269F),
        (0x26A1, 0x26A1),
        (0x26AA, 0x26AB),
        (0x26BD, 0x26BF),
        (0x26C4, 0x26E1),
        (0x26E3, 0x26E3),
        (0x26E8, 0x26FF),
        (0x2705, 0x2705),
        (0x270A, 0x270B),
        (0x2728, 0x2728),
        (0x273D, 0x273D),
        (0x274C, 0x274C),
        (0x274E, 0x274E),
        (0x2753, 0x2755),
        (0x2757, 0x2757),
        (0x2776, 0x277F),
        (0x2795, 0x2797),
        (0x27B0, 0x27B0),
        (0x27BF, 0x27BF),
        (0x2B1B, 0x2B1C),
        (0x2B50, 0x2B50),
        (0x2B55, 0x2B55),
        (0x2E80, 0x303E),
        (0x3041, 0x3096),
        (0x3099, 0x30FF),
        (0x3105, 0x312F),
        (0x3131, 0x318E),
        (0x3190, 0x31E3),
        (0x31EF, 0x321E),
        (0x3220, 0x3247),
        (0x3250, 0x4DBF),
        (0x4E00, 0xA48C),
        (0xA490, 0xA4C6),
        (0xA960, 0xA97C),
        (0xAC00, 0xD7A3),
        (0xF900, 0xFAFF),
        (0xFE10, 0xFE19),
        (0xFE30, 0xFE52),
        (0xFE54, 0xFE66),
        (0xFE68, 0xFE6B),
        (0xFF01, 0xFF60),
        (0xFFE0, 0xFFE6),
        (0x16FE0, 0x16FE4),
        (0x17000, 0x18AFF),
        (0x1B000, 0x1B2FB),
        (0x1F004, 0x1F004),
        (0x1F0CF, 0x1F0CF),
        (0x1F18E, 0x1F18E),
        (0x1F191, 0x1F19A),
        (0x1F200, 0x1F202),
        (0x1F210, 0x1F23B),
        (0x1F240, 0x1F248),
        (0x1F250, 0x1F251),
        (0x1F260, 0x1F265),
        (0x1F300, 0x1F320),
        (0x1F32D, 0x1F335),
        (0x1F337, 0x1F37C),
        (0x1F37E, 0x1F393),
        (0x1F3A0, 0x1F3CA),
        (0x1F3CF, 0x1F3D3),
        (0x1F3E0, 0x1F3F0),
        (0x1F3F4, 0x1F3F4),
        (0x1F3F8, 0x1F43E),
        (0x1F440, 0x1F440),
        (0x1F442, 0x1F4FC),
        (0x1F4FF, 0x1F53D),
        (0x1F54B, 0x1F54E),
        (0x1F550, 0x1F567),
        (0x1F57A, 0x1F57A),
        (0x1F595, 0x1F596),
        (0x1F5A4, 0x1F5A4),
        (0x1F5FB, 0x1F64F),
        (0x1F680, 0x1F6C5),
        (0x1F6CC, 0x1F6CC),
        (0x1F6D0, 0x1F6D2),
        (0x1F6D5, 0x1F6D7),
        (0x1F6EB, 0x1F6EC),
        (0x1F6F4, 0x1F6FC),
        (0x1F7E0, 0x1F7EB),
        (0x1F90C, 0x1F93A),
        (0x1F93C, 0x1F945),
        (0x1F947, 0x1F978),
        (0x1F97A, 0x1F9CB),
        (0x1F9CD, 0x1F9FF),
        (0x1FA70, 0x1FA74),
        (0x1FA78, 0x1FA7A),
        (0x1FA80, 0x1FA86),
        (0x1FA90, 0x1FAA8),
        (0x1FAB0, 0x1FAB6),
        (0x1FAC0, 0x1FAC2),
        (0x1FAD0, 0x1FAD6),
        (0x20000, 0x3FFFD),
    ];
    in_ranges(cp, W)
}

fn cw(c: char) -> usize {
    let cp = c as u32;
    // C0/C1 controls + DEL: unicode-width returns None; csview maps them to width 1
    // (so a literal TAB or embedded NEWLINE in a cell reserves one column).
    if cp < 0x20 || (0x7F..=0x9F).contains(&cp) {
        return 1;
    }
    if cw0(cp) {
        return 0;
    }
    if cw2(cp) {
        return 2;
    }
    1
}

fn is_emoji_vs16_base(c: char) -> bool {
    matches!(c as u32,
        0x0023 | 0x002A | 0x0030..=0x0039 |
        0x00A9 | 0x00AE | 0x203C | 0x2049 |
        0x2122 | 0x2139 | 0x2194..=0x21AA |
        0x231A..=0x231B | 0x2328 | 0x23CF | 0x23E9..=0x23F3 |
        0x24C2 | 0x25AA..=0x25AB | 0x25B6 | 0x25C0 | 0x25FB..=0x25FE |
        0x2600..=0x27BF | 0x2934..=0x2935 | 0x2B05..=0x2B07 |
        0x2B1B..=0x2B1C | 0x2B50 | 0x2B55 | 0x3030 | 0x303D |
        0x3297 | 0x3299)
}

// String-level width (matches csview): VS16 (U+FE0F) promotes the preceding emoji base 1->2.
fn dwidth(s: &str) -> usize {
    let mut total = 0usize;
    let mut prev: Option<char> = None;
    for c in s.chars() {
        if c == '\u{FE0F}' {
            if let Some(p) = prev {
                if cw(p) == 1 && is_emoji_vs16_base(p) {
                    total += 1;
                }
            }
            prev = None;
            continue;
        }
        total += cw(c);
        prev = Some(c);
    }
    total
}

fn pad_to(content: &str, width: usize, align: &str) -> String {
    // truncate display-aware to <= width (never split a wide char; no ellipsis), then pad.
    let (s, sw) = if dwidth(content) > width {
        let mut acc = 0;
        let mut t = String::new();
        for c in content.chars() {
            let d = cw(c);
            if acc + d > width {
                break;
            }
            acc += d;
            t.push(c);
        }
        (t, acc)
    } else {
        (content.to_string(), dwidth(content))
    };
    let total = width - sw;
    match align {
        "right" => format!("{}{}", " ".repeat(total), s),
        "center" => {
            let l = total / 2;
            let r = total - l;
            format!("{}{}{}", " ".repeat(l), s, " ".repeat(r))
        }
        _ => format!("{}{}", s, " ".repeat(total)),
    }
}

// ---- style glyphs ----
struct Style {
    // row borders
    rl: &'static str,
    rs: &'static str,
    rr: &'static str,
    // separator lines: corner-left, junction, corner-right, fill, plus header-sep variants
    top: Option<(&'static str, &'static str, &'static str, &'static str)>,
    hsep: Option<(&'static str, &'static str, &'static str, &'static str)>,
    bot: Option<(&'static str, &'static str, &'static str, &'static str)>,
    grid: bool, // rule between every body row
}

fn style_for(name: &str) -> Style {
    match name {
        "none" => Style {
            rl: "",
            rs: "",
            rr: "",
            top: None,
            hsep: None,
            bot: None,
            grid: false,
        },
        "ascii" => Style {
            rl: "|",
            rs: "|",
            rr: "|",
            top: Some(("+", "+", "+", "-")),
            hsep: Some(("+", "+", "+", "-")),
            bot: Some(("+", "+", "+", "-")),
            grid: false,
        },
        "ascii2" => Style {
            rl: " ",
            rs: "|",
            rr: " ",
            top: None,
            hsep: Some((" ", "+", " ", "-")),
            bot: None,
            grid: false,
        },
        "rounded" => Style {
            rl: "│",
            rs: "│",
            rr: "│",
            top: Some(("╭", "┬", "╮", "─")),
            hsep: Some(("├", "┼", "┤", "─")),
            bot: Some(("╰", "┴", "╯", "─")),
            grid: false,
        },
        "reinforced" => Style {
            rl: "│",
            rs: "│",
            rr: "│",
            top: Some(("┏", "┬", "┓", "─")),
            hsep: Some(("├", "┼", "┤", "─")),
            bot: Some(("┗", "┴", "┛", "─")),
            grid: false,
        },
        "markdown" => Style {
            rl: "|",
            rs: "|",
            rr: "|",
            top: None,
            hsep: Some(("|", "|", "|", "-")),
            bot: None,
            grid: false,
        },
        "grid" => Style {
            rl: "│",
            rs: "│",
            rr: "│",
            top: Some(("┌", "┬", "┐", "─")),
            hsep: Some(("├", "┼", "┤", "─")),
            bot: Some(("└", "┴", "┘", "─")),
            grid: true,
        },
        // sharp (default)
        _ => Style {
            rl: "│",
            rs: "│",
            rr: "│",
            top: Some(("┌", "┬", "┐", "─")),
            hsep: Some(("├", "┼", "┤", "─")),
            bot: Some(("└", "┴", "┘", "─")),
            grid: false,
        },
    }
}

fn sep_line(
    parts: (&str, &str, &str, &str),
    widths: &[usize],
    padding: usize,
    indent: usize,
) -> String {
    let (l, j, r, h) = parts;
    let segs: Vec<String> = widths
        .iter()
        .map(|w| h.repeat(w + 2 * padding))
        .collect();
    format!("{}{}{}{}", " ".repeat(indent), l, segs.join(j), r)
}

fn render_row(
    cells: &[String],
    widths: &[usize],
    align: &str,
    st: &Style,
    padding: usize,
    indent: usize,
) -> String {
    let pad = " ".repeat(padding);
    let rendered: Vec<String> = (0..widths.len())
        .map(|i| {
            let c = cells.get(i).map(|s| s.as_str()).unwrap_or("");
            format!("{}{}{}", pad, pad_to(c, widths[i], align), pad)
        })
        .collect();
    format!(
        "{}{}{}{}",
        " ".repeat(indent),
        st.rl,
        rendered.join(st.rs),
        st.rr
    )
}

fn render(
    header: &[String],
    body: &[Vec<String>],
    has_header: bool,
    style: &str,
    padding: usize,
    indent: usize,
    header_align: &str,
    body_align: &str,
    sniff: usize,
) -> String {
    let st = style_for(style);

    // column count = max over header+body
    let mut ncols = if has_header { header.len() } else { 0 };
    for r in body {
        ncols = ncols.max(r.len());
    }

    // column widths: header ALWAYS counted; only the first `sniff` DATA rows are scanned
    // (sniff==0 => all rows). Cells in rows beyond the limit are truncated to these widths.
    let limit = if sniff == 0 { body.len() } else { sniff.min(body.len()) };
    let mut widths = vec![0usize; ncols];
    if has_header {
        for (i, c) in header.iter().enumerate() {
            widths[i] = widths[i].max(dwidth(c));
        }
    }
    for r in &body[..limit] {
        for (i, c) in r.iter().enumerate() {
            widths[i] = widths[i].max(dwidth(c));
        }
    }

    let mut lines: Vec<String> = Vec::new();
    if let Some(t) = st.top {
        lines.push(sep_line(t, &widths, padding, indent));
    }

    // assemble rows in order, tracking which is the header
    let has_body = !body.is_empty();
    if has_header {
        lines.push(render_row(header, &widths, header_align, &st, padding, indent));
        if has_body {
            if let Some(h) = st.hsep {
                lines.push(sep_line(h, &widths, padding, indent));
            }
        }
    }
    for (idx, r) in body.iter().enumerate() {
        lines.push(render_row(r, &widths, body_align, &st, padding, indent));
        let is_last = idx + 1 == body.len();
        if st.grid && !is_last {
            if let Some(h) = st.hsep {
                lines.push(sep_line(h, &widths, padding, indent));
            }
        }
    }
    // empty case: no header row emitted (no_headers) and no body -> still need one empty row?
    if lines.is_empty() || (!has_header && !has_body) {
        // zero content -> a single empty row between borders
        lines.clear();
        if let Some(t) = st.top {
            lines.push(sep_line(t, &widths, padding, indent));
        }
        lines.push(render_row(&[], &widths, body_align, &st, padding, indent));
        if let Some(b) = st.bot {
            lines.push(sep_line(b, &widths, padding, indent));
        }
        return lines.join("\n") + "\n";
    }

    if let Some(b) = st.bot {
        lines.push(sep_line(b, &widths, padding, indent));
    }
    lines.join("\n") + "\n"
}

fn help_text() -> String {
    String::from(
        r#"A high performance csv viewer with cjk/emoji support.

Usage: executable [OPTIONS] [FILE]

Arguments:
  [FILE]
          File to view

Options:
  -H, --no-headers
          Specify that the input has no header row
  -n, --number
          Prepend a column of line numbers to the table
  -t, --tsv
          Use '\t' as delimiter for tsv
  -d, --delimiter <DELIMITER>
          Specify the field delimiter [default: ,]
  -s, --style <STYLE>
          Specify the border style [default: sharp] [possible values: none, ascii, ascii2, sharp,
          rounded, reinforced, markdown, grid]
  -p, --padding <PADDING>
          Specify padding for table cell [default: 1]
  -i, --indent <INDENT>
          Specify global indent for table [default: 0]
      --sniff <LIMIT>
          Limit column widths sniffing to the specified number of rows. Specify "0" to cancel limit
          [default: 1000]
      --header-align <HEADER_ALIGN>
          Specify the alignment of the table header [default: center] [possible values: left,
          center, right]
      --body-align <BODY_ALIGN>
          Specify the alignment of the table body [default: left] [possible values: left, center,
          right]
  -P, --disable-pager
          Disable pager
  -h, --help
          Print help
  -V, --version
          Print version
"#,
    )
}
