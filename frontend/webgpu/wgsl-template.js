/**
 * Minimal WGSL specializer, modelled on the approach used by the
 * webml-community/gemma-4-webgpu-kernels demo.
 *
 * Two ideas are worth stealing from that project:
 *
 *   1. Shapes become compile-time constants. Instead of passing HIDDEN in a uniform
 *      and looping to a runtime bound, the value is substituted into the source so
 *      the driver's shader compiler can unroll and bounds-check statically.
 *
 *   2. Resource declarations are generated from the binding table, never hand-written.
 *      A kernel declares *what* it needs; the `@group(0) @binding(n)` block and the
 *      params struct are derived from that, so bindings cannot drift out of sync with
 *      the bind group layout.
 *
 * Template syntax (deliberately tiny — this is not Jinja):
 *   {{ NAME }}                value substitution
 *   {{ NAME | u32 }}          substitution with a `u` suffix for WGSL u32 literals
 *   {% if COND %} ... {% endif %}
 *   {% if COND %} ... {% else %} ... {% endif %}
 *   {{ RESOURCES }}           expands to the generated binding declarations
 */

const IF_BLOCK = /\{%\s*if\s+([A-Za-z0-9_.]+)\s*%\}([\s\S]*?)\{%\s*endif\s*%\}/g;
const SUBST = /\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*(u32|f32))?\s*\}\}/g;

function lookup(scope, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), scope);
}

function formatValue(v, filter) {
  if (filter === "u32") return `${Math.trunc(v)}u`;
  if (filter === "f32") return Number.isInteger(v) ? `${v}.0` : `${v}`;
  if (typeof v === "number" && !Number.isInteger(v)) return `${v}`;
  return `${v}`;
}

/**
 * Expand `{% if %}` / `{% else %}` blocks, innermost first.
 * Conditions are plain truthiness checks against the scope — no expressions.
 */
function expandConditionals(src, scope) {
  let out = src;
  let guard = 0;
  while (IF_BLOCK.test(out)) {
    if (++guard > 32) throw new Error("wgsl-template: conditional nesting too deep");
    IF_BLOCK.lastIndex = 0;
    out = out.replace(IF_BLOCK, (_, cond, body) => {
      const parts = body.split(/\{%\s*else\s*%\}/);
      if (parts.length > 2) throw new Error(`wgsl-template: multiple {% else %} in "${cond}"`);
      const [truthy, falsy = ""] = parts;
      return lookup(scope, cond) ? truthy : falsy;
    });
    IF_BLOCK.lastIndex = 0;
  }
  return out;
}

/**
 * WGSL identifiers that are reserved for future use.
 *
 * These parse as keywords, not names, so declaring a buffer called `meta` or `shared`
 * fails in the driver's compiler with a message about a generated line. The full list
 * in the spec is ~150 entries; this is the subset a person naming a GPU buffer might
 * plausibly reach for. Checked at declaration time so the failure names the binding.
 *
 * https://www.w3.org/TR/WGSL/#reserved-words
 */
const RESERVED_WGSL = new Set([
  "active", "as", "asm", "attribute", "auto", "binding", "buffer", "cast", "class",
  "coherent", "common", "compile", "delete", "demote", "do", "enum", "extern",
  "external", "filter", "final", "friend", "from", "get", "goto", "groupshared",
  "handle", "impl", "inline", "input", "instance", "interface", "layout", "line",
  "macro", "match", "mat", "meta", "mod", "module", "move", "mut", "namespace",
  "new", "null", "operator", "output", "package", "partition", "pass", "patch",
  "pixel", "precision", "premerge", "priv", "protected", "pub", "public", "readonly",
  "ref", "regardless", "register", "resource", "restrict", "self", "set", "shared",
  "signed", "sizeof", "smooth", "snorm", "static", "std", "subroutine", "super",
  "target", "template", "this", "thread", "throw", "trait", "try", "type", "typedef",
  "typeid", "union", "unless", "unorm", "unsafe", "unsized", "use", "using",
  "varying", "virtual", "volatile", "wgsl", "where", "with", "writeonly", "yield",
]);

/**
 * Reject a binding name WGSL will not accept.
 *
 * Exported so a Node test can check a binding table without rendering it: the whole
 * point is that this failure should not need a GPU to surface.
 */
export function assertValidIdentifier(name, what = "identifier") {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
    throw new Error(`wgsl-template: ${what} "${name}" is not a valid WGSL identifier`);
  }
  if (name.startsWith("__")) {
    throw new Error(`wgsl-template: ${what} "${name}" — WGSL reserves the "__" prefix`);
  }
  if (RESERVED_WGSL.has(name)) {
    throw new Error(`wgsl-template: ${what} "${name}" is a WGSL reserved keyword`);
  }
}

/**
 * Build the `@group(0) @binding(n)` declarations plus the params struct.
 *
 * A binding is:
 *   { name, type: "storage" | "read-only-storage" | "uniform", element: "f32"|"i32"|"u32"|"atomic<u32>" }
 * A params binding additionally carries `fields: [{ name, type }]`.
 */
export function resourceDeclarations(bindings) {
  const lines = [];
  bindings.forEach((b, i) => {
    assertValidIdentifier(b.name, "binding");
    for (const f of b.fields ?? []) assertValidIdentifier(f.name, "params field");
    if (b.type === "uniform") {
      const fields = (b.fields ?? []).map((f) => `  ${f.name}: ${f.type},`).join("\n");
      lines.push(`struct ${b.struct ?? "Params"} {\n${fields}\n};`);
      lines.push(`@group(0) @binding(${i}) var<uniform> ${b.name}: ${b.struct ?? "Params"};`);
    } else {
      const access = b.type === "storage" ? "read_write" : "read";
      lines.push(
        `@group(0) @binding(${i}) var<storage, ${access}> ${b.name}: array<${b.element ?? "f32"}>;`
      );
    }
  });
  return lines.join("\n");
}

/** Bind group layout entries matching `resourceDeclarations` binding order. */
export function bindGroupLayoutEntries(bindings) {
  return bindings.map((b, i) => ({
    binding: i,
    visibility: GPUShaderStage.COMPUTE,
    buffer: { type: b.type },
  }));
}

/** Specialize a WGSL template against a scope. */
export function render(source, scope = {}) {
  let out = expandConditionals(source, scope);
  out = out.replace(SUBST, (whole, path, filter, offset, whole_src) => {
    const v = lookup(scope, path);
    if (v === undefined) throw new Error(`wgsl-template: unbound value "${path}"`);
    // `{{ WG | u32 }}u` renders as `64uu`, which fails deep inside the shader compiler
    // with a message that points at the generated line, not at the template.
    if (filter === "u32" && /^[uf]/.test(whole_src.slice(offset + whole.length))) {
      throw new Error(
        `wgsl-template: "{{ ${path} | u32 }}" is followed by a suffix character — ` +
          `the u32 filter already appends "u"`
      );
    }
    return formatValue(v, filter);
  });
  return out;
}

/**
 * Negotiate device capabilities up front so kernels can branch at specialization
 * time rather than at runtime. Mirrors the Gemma bundle's handling of subgroups:
 * a subgroup width that is not exactly 32 needs a shuffle butterfly rather than a
 * plain subgroupAdd, and a device without subgroups needs a workgroup-memory path.
 */
export function deviceProfile(adapter, device) {
  const features = device.features;
  const info = adapter?.info ?? {};
  const hasSubgroups = features.has("subgroups");
  const min = info.subgroupMinSize;
  const max = info.subgroupMaxSize;
  return {
    f16: features.has("shader-f16"),
    subgroups: hasSubgroups,
    sgExact32: hasSubgroups && min === 32 && max === 32,
    vendor: info.vendor ?? "unknown",
    architecture: info.architecture ?? "unknown",
    limits: {
      maxComputeWorkgroupSizeX: device.limits.maxComputeWorkgroupSizeX,
      maxComputeInvocationsPerWorkgroup: device.limits.maxComputeInvocationsPerWorkgroup,
      maxStorageBufferBindingSize: Number(device.limits.maxStorageBufferBindingSize),
    },
  };
}

/**
 * Compile a kernel: specialize the source, create the pipeline, and keep the
 * binding table alongside it so the caller cannot mis-order the bind group.
 */
export async function compileKernel(device, { label, source, bindings, scope, entryPoint = "main" }) {
  const code = render(source, { ...scope, RESOURCES: resourceDeclarations(bindings) });

  const module = device.createShaderModule({ code, label });

  // The pipeline error only says "invalid shader module". The actual diagnostic —
  // message, line, column — is on the module, so read it before giving up, and quote
  // the offending line: a specialized shader is generated code, so a bare line number
  // is not something you can look up in the source file.
  const info = await module.getCompilationInfo?.();
  const errors = (info?.messages ?? []).filter((m) => m.type === "error");
  if (errors.length) {
    const lines = code.split("\n");
    const detail = errors
      .map((m) => `  ${m.lineNum}:${m.linePos} ${m.message}\n    | ${lines[m.lineNum - 1] ?? ""}`)
      .join("\n");
    throw new Error(`kernel "${label}" failed to compile:\n${detail}`);
  }

  device.pushErrorScope("validation");
  const layout = device.createBindGroupLayout({
    label: `${label}:layout`,
    entries: bindGroupLayoutEntries(bindings),
  });
  const pipeline = await device.createComputePipelineAsync({
    label,
    layout: device.createPipelineLayout({ bindGroupLayouts: [layout] }),
    compute: { module, entryPoint },
  });
  const err = await device.popErrorScope();
  if (err) throw new Error(`kernel "${label}" failed to build a pipeline: ${err.message}`);

  return { label, pipeline, layout, bindings, code };
}

/** Create a bind group from `{ name: GPUBuffer }`, ordered by the binding table. */
export function makeBindGroup(device, kernel, buffers) {
  return device.createBindGroup({
    label: `${kernel.label}:bg`,
    layout: kernel.layout,
    entries: kernel.bindings.map((b, i) => {
      const buffer = buffers[b.name];
      if (!buffer) throw new Error(`kernel "${kernel.label}": missing buffer "${b.name}"`);
      return { binding: i, resource: { buffer } };
    }),
  });
}
