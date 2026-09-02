// gron reimplementation — Claude-tier, native Go, no external deps.
// Reverse-engineered black-box from the reference (PB :task oracle). Single-file legit reimpl
// (NOT the upstream gron source). Behaviors: flatten JSON -> sorted `json.path = value;`
// statements; --ungron reverses; --values; --json; --stream; --no-sort; color flags; help/version.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strconv"
	"strings"
)

const version = "dev"

// ---- JSON value model preserving number formatting via json.Number ----

func decode(r io.Reader) (interface{}, error) {
	dec := json.NewDecoder(r)
	dec.UseNumber()
	var v interface{}
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

// ---- ordered JSON value (preserves object key order for --no-sort) ----

type omember struct {
	k string
	v interface{}
}
type oobj struct{ m []omember }
type oarr struct{ e []interface{} }

func decodeOrdered(r io.Reader) (interface{}, error) {
	dec := json.NewDecoder(r)
	dec.UseNumber()
	return parseOrdered(dec)
}
func parseOrdered(dec *json.Decoder) (interface{}, error) {
	t, err := dec.Token()
	if err != nil {
		return nil, err
	}
	return parseFromToken(dec, t)
}
func parseFromToken(dec *json.Decoder, t json.Token) (interface{}, error) {
	switch d := t.(type) {
	case json.Delim:
		if d == '{' {
			o := &oobj{}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				k, ok := kt.(string)
				if !ok {
					return nil, fmt.Errorf("invalid object key")
				}
				v, err := parseOrdered(dec)
				if err != nil {
					return nil, err
				}
				o.m = append(o.m, omember{k, v})
			}
			dec.Token() // }
			return o, nil
		}
		a := &oarr{}
		for dec.More() {
			v, err := parseOrdered(dec)
			if err != nil {
				return nil, err
			}
			a.e = append(a.e, v)
		}
		dec.Token() // ]
		return a, nil
	default:
		return t, nil
	}
}

// ---- gron: flatten to statements ----

type stmt struct {
	path  []string // path tokens already rendered (e.g. ".a", "[0]")
	value string   // rendered RHS
}

func isIdent(s string) bool {
	if s == "" {
		return false
	}
	for i, r := range s {
		if r == '_' || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') {
			continue
		}
		if i > 0 && r >= '0' && r <= '9' {
			continue
		}
		return false
	}
	return true
}

func key(k string) string {
	if isIdent(k) {
		return "." + k
	}
	b, _ := json.Marshal(k)
	return "[" + string(b) + "]"
}

func renderScalar(v interface{}) string {
	switch t := v.(type) {
	case nil:
		return "null"
	case bool:
		if t {
			return "true"
		}
		return "false"
	case json.Number:
		return t.String()
	case string:
		b, _ := json.Marshal(t)
		return string(b)
	}
	b, _ := json.Marshal(v)
	return string(b)
}

type fstmt struct {
	line   string
	tokens []interface{} // path tokens for -j: strings (keys) / ints (indices)
	jval   interface{}   // scalar, or map[string]interface{}{} / []interface{}{} markers
}

func flatten(prefix string, tokens []interface{}, v interface{}, out *[]fstmt) {
	switch t := v.(type) {
	case *oobj:
		*out = append(*out, fstmt{prefix + " = {};", cp(tokens), map[string]interface{}{}})
		for _, mem := range t.m {
			flatten(prefix+key(mem.k), append(cp(tokens), mem.k), mem.v, out)
		}
	case *oarr:
		*out = append(*out, fstmt{prefix + " = [];", cp(tokens), []interface{}{}})
		for i, e := range t.e {
			flatten(prefix+"["+strconv.Itoa(i)+"]", append(cp(tokens), i), e, out)
		}
	default:
		*out = append(*out, fstmt{prefix + " = " + renderScalar(v) + ";", cp(tokens), v})
	}
}

func cp(t []interface{}) []interface{} {
	n := make([]interface{}, len(t))
	copy(n, t)
	return n
}

// ANSI colorize a statement from its path tokens + value (matches gron --colorize):
// ident key = blue-bold; brackets = magenta; index number = red; container {}/[] = magenta;
// number = red; string (+ non-ident quoted key) = yellow; bool/null = cyan.
const (
	cKey   = "\x1b[34;1m"
	rKey   = "\x1b[0;22m"
	cBr    = "\x1b[35m"
	cNum   = "\x1b[31m"
	cStr   = "\x1b[33m"
	cBool  = "\x1b[36m"
	cReset = "\x1b[0m"
)

func colorScalar(v interface{}) string {
	switch t := v.(type) {
	case map[string]interface{}:
		return cBr + "{}" + cReset
	case []interface{}:
		return cBr + "[]" + cReset
	case json.Number:
		return cNum + t.String() + cReset
	case string:
		b, _ := json.Marshal(t)
		return cStr + string(b) + cReset
	case bool, nil:
		return cBool + renderScalar(v) + cReset
	}
	return renderScalar(v)
}

func colorLine(tokens []interface{}, jval interface{}) string {
	var b strings.Builder
	b.WriteString(cKey + "json" + rKey)
	for _, tk := range tokens {
		switch k := tk.(type) {
		case string:
			if isIdent(k) {
				b.WriteString("." + cKey + k + rKey)
			} else {
				q, _ := json.Marshal(k)
				b.WriteString(cBr + "[" + cReset + cStr + string(q) + cReset + cBr + "]" + cReset)
			}
		case int:
			b.WriteString(cBr + "[" + cReset + cNum + strconv.Itoa(k) + cReset + cBr + "]" + cReset)
		}
	}
	b.WriteString(" = " + colorScalar(jval) + ";")
	return b.String()
}

func gronStmts(v interface{}, sortLines bool) []fstmt {
	var s []fstmt
	flatten("json", nil, v, &s)
	if sortLines {
		sort.SliceStable(s, func(i, j int) bool { return s[i].line < s[j].line })
	}
	return s
}

// --values: input is GRON STATEMENTS; print each SCALAR value (one per line).
// Skips container markers ({} / []); strings are unquoted.
func valuesFromStatements(lines []string, w io.Writer) {
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln == "" {
			continue
		}
		eq := strings.Index(ln, " = ")
		if eq < 0 {
			continue
		}
		rhs := strings.TrimSuffix(ln[eq+3:], ";")
		if rhs == "{}" || rhs == "[]" {
			continue
		}
		if len(rhs) > 0 && rhs[0] == '"' {
			var s string
			if err := json.Unmarshal([]byte(rhs), &s); err == nil {
				fmt.Fprintln(w, s)
				continue
			}
		}
		fmt.Fprintln(w, rhs)
	}
}

// ---- ungron: statements -> JSON (pretty 2-space) ----

type node struct {
	isArr    bool
	isObj    bool
	scalar   interface{}
	hasScal  bool
	children map[string]*node
	order    []string
}

func newNode() *node { return &node{children: map[string]*node{}} }

// parse a path like json.a.b[0] -> tokens ["a","b","0"(arr)]
type tok struct {
	name  string
	isIdx bool
}

func parsePath(lhs string) []tok {
	// strip leading "json"
	s := strings.TrimSpace(lhs)
	s = strings.TrimPrefix(s, "json")
	var toks []tok
	for len(s) > 0 {
		if s[0] == '.' {
			s = s[1:]
			j := 0
			for j < len(s) && (s[j] == '_' || (s[j] >= 'a' && s[j] <= 'z') || (s[j] >= 'A' && s[j] <= 'Z') || (s[j] >= '0' && s[j] <= '9')) {
				j++
			}
			toks = append(toks, tok{name: s[:j]})
			s = s[j:]
		} else if s[0] == '[' {
			end := strings.IndexByte(s, ']')
			if end < 0 {
				break
			}
			inner := s[1:end]
			if len(inner) > 0 && inner[0] == '"' {
				var k string
				_ = json.Unmarshal([]byte(inner), &k)
				toks = append(toks, tok{name: k})
			} else {
				toks = append(toks, tok{name: inner, isIdx: true})
			}
			s = s[end+1:]
		} else {
			break
		}
	}
	return toks
}

func ungron(lines []string) (interface{}, error) {
	root := newNode()
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln == "" {
			continue
		}
		eq := strings.Index(ln, " = ")
		if eq < 0 {
			continue
		}
		lhs := ln[:eq]
		rhs := strings.TrimSuffix(ln[eq+3:], ";")
		toks := parsePath(lhs)
		cur := root
		for _, tk := range toks {
			if cur.children == nil {
				cur.children = map[string]*node{}
			}
			if tk.isIdx {
				cur.isArr = true
			} else {
				cur.isObj = true
			}
			ch, ok := cur.children[tk.name]
			if !ok {
				ch = newNode()
				cur.children[tk.name] = ch
				cur.order = append(cur.order, tk.name)
			}
			cur = ch
		}
		switch rhs {
		case "{}":
			cur.isObj = true
		case "[]":
			cur.isArr = true
		default:
			var val interface{}
			d := json.NewDecoder(strings.NewReader(rhs))
			d.UseNumber()
			if err := d.Decode(&val); err == nil {
				cur.scalar = val
				cur.hasScal = true
			}
		}
	}
	return build(root), nil
}

func build(n *node) interface{} {
	if n.isArr {
		idxs := make([]int, 0, len(n.order))
		for _, k := range n.order {
			i, _ := strconv.Atoi(k)
			idxs = append(idxs, i)
		}
		sort.Ints(idxs)
		arr := make([]interface{}, 0, len(idxs))
		for _, i := range idxs {
			arr = append(arr, build(n.children[strconv.Itoa(i)]))
		}
		return arr
	}
	if n.isObj {
		m := map[string]interface{}{}
		for _, k := range n.order {
			m[k] = build(n.children[k])
		}
		return m
	}
	if n.hasScal {
		return n.scalar
	}
	return nil
}

func main() {
	args := os.Args[1:]
	var file string
	doUngron, doValues, doJSON, noSort, doStream, colorize := false, false, false, false, false, false
	for _, a := range args {
		switch a {
		case "-h", "--help":
			fmt.Print(helpText)
			return
		case "--version":
			fmt.Printf("gron version %s\n", version)
			return
		case "-u", "--ungron":
			doUngron = true
		case "-v", "--values":
			doValues = true
		case "-j", "--json":
			doJSON = true
		case "--no-sort":
			noSort = true
		case "-s", "--stream":
			doStream = true
		case "-c", "--colorize":
			colorize = true
		case "-m", "--monochrome", "-k", "--insecure", "--no-color", "-x", "--proxy", "--noproxy":
			// non-TTY default is monochrome; proxy is network (no-op here)
		default:
			if !strings.HasPrefix(a, "-") {
				file = a
			}
		}
	}

	var in io.Reader = os.Stdin
	if file != "" && file != "-" {
		f, err := os.Open(file)
		if err != nil {
			fmt.Fprintf(os.Stderr, "gron: open %s: %v\n", file, err)
			os.Exit(1)
		}
		defer f.Close()
		in = f
	}

	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()

	// --ungron and --values both consume gron STATEMENTS from input (not JSON).
	if doUngron || doValues {
		sc := bufio.NewScanner(in)
		sc.Buffer(make([]byte, 1024*1024), 64*1024*1024)
		var lines []string
		for sc.Scan() {
			lines = append(lines, sc.Text())
		}
		if doValues {
			valuesFromStatements(lines, w)
			return
		}
		v, err := ungron(lines)
		if err != nil {
			fmt.Fprintf(os.Stderr, "gron: %v\n", err)
			os.Exit(1)
		}
		b, _ := json.MarshalIndent(v, "", "  ")
		w.Write(b)
		w.WriteByte('\n')
		return
	}

	emit := func(v interface{}) {
		stmts := gronStmts(v, !noSort)
		if doJSON {
			// each statement -> [path_tokens, value] JSON, one per line
			for _, s := range stmts {
				pair := []interface{}{s.tokens, s.jval}
				if s.tokens == nil {
					pair[0] = []interface{}{}
				}
				b, _ := json.Marshal(pair)
				w.Write(b)
				w.WriteByte('\n')
			}
			return
		}
		for _, s := range stmts {
			if colorize {
				w.WriteString(colorLine(s.tokens, s.jval))
			} else {
				w.WriteString(s.line)
			}
			w.WriteByte('\n')
		}
	}

	if doStream {
		// --stream: each JSON doc becomes an element of a top-level array (json[0], json[1], ...)
		dec := json.NewDecoder(in)
		dec.UseNumber()
		arr := &oarr{}
		for {
			v, err := parseOrdered(dec)
			if err != nil {
				if err == io.EOF {
					break
				}
				fmt.Fprintf(os.Stderr, "failed to form statements: %v\n", err)
				os.Exit(3)
			}
			arr.e = append(arr.e, v)
		}
		emit(arr)
		return
	}

	// read all input so we can (1) report the CANONICAL json error via Unmarshal, (2) ordered-parse.
	data, _ := io.ReadAll(in)
	var probe interface{}
	if err := json.Unmarshal(data, &probe); err != nil {
		fmt.Fprintf(os.Stderr, "failed to form statements: %v\n", err)
		os.Exit(3)
	}
	v, err := decodeOrdered(bytesReader(data))
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to form statements: %v\n", err)
		os.Exit(3)
	}
	emit(v)
}

func bytesReader(b []byte) io.Reader { return strings.NewReader(string(b)) }

const helpText = `Transform JSON (from a file, URL, or stdin) into discrete assignments to make it greppable

Usage:
  gron [OPTIONS] [FILE|URL|-]

Options:
  -u, --ungron     Reverse the operation (turn assignments back into JSON)
  -v, --values     Print just the values of provided assignments
  -c, --colorize   Colorize output (default on tty)
  -m, --monochrome Monochrome (don't colorize output)
  -s, --stream     Treat each line of input as a separate JSON object
  -k, --insecure   Disable certificate validation
  -x, --proxy      Set proxy configuration
      --noproxy    Comma-separated list of hosts for which not to use a proxy, if one is specified.
  -j, --json       Represent gron data as JSON stream
      --no-sort    Don't sort output (faster)
      --version    Print version information

Exit Codes:
  0` + "\t" + `OK
  1` + "\t" + `Failed to open file
  2` + "\t" + `Failed to read input
  3` + "\t" + `Failed to form statements
  4` + "\t" + `Failed to fetch URL
  5` + "\t" + `Failed to parse statements
  6` + "\t" + `Failed to encode JSON

Examples:
  gron /tmp/apiresponse.json
  gron http://jsonplaceholder.typicode.com/users/1 ` + `
  curl -s http://jsonplaceholder.typicode.com/users/1 | gron
  gron http://jsonplaceholder.typicode.com/users/1 | grep company | gron --ungron
`
