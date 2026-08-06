#!/usr/bin/env node

import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

const endpoint = process.env.KLINTCODE_ENDPOINT
  ?? "https://token-plan-cn.xiaomimimo.com/v1";
const model = process.env.KLINTCODE_MODEL ?? "mimo-v2.5-pro";
const apiKey = process.env.MIMO_API_KEY;
const timeoutMs = Number(process.env.KLINTCODE_MODEL_TIMEOUT_MS ?? 120_000);
const dryRun = process.argv.includes("--dry-run");
const withTools = process.argv.includes("--with-tools");
const outputIndex = process.argv.indexOf("--output");
const outputPath = outputIndex >= 0 ? process.argv[outputIndex + 1] : undefined;

if (outputIndex >= 0 && !outputPath) {
  throw new Error("--output requires a file path");
}
if (!dryRun && !apiKey) {
  throw new Error("MIMO_API_KEY is required unless --dry-run is used");
}

const apiBase = endpoint.replace(/\/+$/, "");
const chatUrl = apiBase.endsWith("/v1")
  ? `${apiBase}/chat/completions`
  : `${apiBase}/v1/chat/completions`;

const task = {
  id: "system-platform-update",
  phase: "business-coding",
  goal: "Implement and compiler-check the update service business code for the System Platform entity in an existing generated TeaQL Rust workspace.",
  inputs: {
    workspace: "/isolated/workspace",
    entity: "System Platform",
    operation: "update",
    target_path: "src/system_platform/update.rs",
  },
  acceptance_criteria: [
    {
      id: "rules-resolved",
      text: "Resolve the effective nested AGENTS.md instructions for the target file.",
    },
    {
      id: "api-grounded",
      text: "Obtain exact object-and-operation-specific update API evidence before writing code.",
    },
    {
      id: "source-written",
      text: "Write the Rust update implementation to the requested target path.",
    },
    {
      id: "build-checked",
      text: "Run cargo check and retain its result as completion evidence.",
    },
  ],
  allowed_permissions: [
    "read_workspace",
    "edit_workspace",
    "run_process",
  ],
};

const skills = [
  {
    id: "resolve-workspace-instructions",
    description: "Resolve root-to-target nested AGENTS.md files and return the effective rules for one target path.",
    phases: ["business-coding", "repair"],
    inputs: ["target_path"],
    outputs: ["effective_rules"],
    permissions: ["read_workspace"],
  },
  {
    id: "resolve-operation-assist",
    description: "Run local object assist for an exact entity and operation and preserve the authoritative API evidence.",
    phases: ["business-coding", "repair"],
    inputs: ["workspace", "entity", "operation"],
    outputs: ["api_evidence"],
    permissions: ["read_workspace", "run_process"],
  },
  {
    id: "implement-teaql-update",
    description: "Generate TeaQL Rust update source using effective workspace rules and exact operation evidence.",
    phases: ["business-coding", "repair"],
    inputs: ["entity", "operation", "effective_rules", "api_evidence"],
    outputs: ["rust_source"],
    permissions: [],
  },
  {
    id: "edit-rust-source",
    description: "Write complete Rust source to a workspace-relative target file.",
    phases: ["business-coding", "repair", "generic-rust"],
    inputs: ["target_path", "rust_source"],
    outputs: ["modified_files"],
    permissions: ["edit_workspace"],
  },
  {
    id: "cargo-check",
    description: "Run cargo check in the isolated workspace and return structured build evidence.",
    phases: ["business-coding", "repair", "generic-rust"],
    inputs: ["workspace", "modified_files"],
    outputs: ["build_result"],
    permissions: ["run_process"],
  },
  {
    id: "compile-repair",
    description: "Repair Rust source from compiler diagnostics while remaining grounded in workspace rules and API evidence.",
    phases: ["repair"],
    inputs: ["effective_rules", "api_evidence", "build_result"],
    outputs: ["rust_source"],
    permissions: [],
  },
  {
    id: "bootstrap-domain-model",
    description: "Create an initial TeaQL domain model before a generated workspace exists.",
    phases: ["modeling"],
    inputs: ["requirements"],
    outputs: ["domain_model"],
    permissions: [],
  },
  {
    id: "external-framework-search",
    description: "Search public websites for framework examples.",
    phases: ["business-coding", "generic-rust"],
    inputs: ["entity"],
    outputs: ["web_examples"],
    permissions: ["external_network"],
  },
];

const tools = [
  {
    id: "discover_instruction_chain",
    description: "Find the root-to-target AGENTS.md instruction chain without reading unrelated files.",
    inputs: ["target_path"],
    outputs: ["instruction_paths"],
    permissions: ["read_workspace"],
  },
  {
    id: "read_files",
    description: "Read an explicit bounded list of workspace files.",
    inputs: ["paths"],
    outputs: ["documents"],
    permissions: ["read_workspace"],
  },
  {
    id: "merge_workspace_instructions",
    description: "Resolve nested instruction precedence for one target path.",
    inputs: ["target_path", "documents"],
    outputs: ["effective_rules"],
    permissions: [],
  },
  {
    id: "cargo_teaql_operation_assist",
    description: "Run the local cargo-teaql object-and-operation assist command with the required --input model.",
    inputs: ["workspace", "entity", "operation"],
    outputs: ["api_evidence"],
    permissions: ["read_workspace", "run_process"],
  },
  {
    id: "generate_rust_source",
    description: "Generate Rust source from exact rules, API evidence, entity, and operation.",
    inputs: ["entity", "operation", "effective_rules", "api_evidence"],
    outputs: ["rust_source"],
    permissions: [],
  },
  {
    id: "write_file",
    description: "Write complete content to one workspace-relative path.",
    inputs: ["target_path", "content"],
    outputs: ["modified_files"],
    permissions: ["edit_workspace"],
  },
  {
    id: "cargo_check",
    description: "Run cargo check in the selected workspace.",
    inputs: ["workspace", "modified_files"],
    outputs: ["build_result"],
    permissions: ["run_process"],
  },
];

const allowedToolsBySkill = {
  "resolve-workspace-instructions": [
    "discover_instruction_chain",
    "read_files",
    "merge_workspace_instructions",
  ],
  "resolve-operation-assist": ["cargo_teaql_operation_assist"],
  "implement-teaql-update": ["generate_rust_source"],
  "edit-rust-source": ["write_file"],
  "cargo-check": ["cargo_check"],
  "compile-repair": ["generate_rust_source"],
  "bootstrap-domain-model": [],
  "external-framework-search": [],
};

const responseContract = {
  task_id: "Copy task.id exactly",
  goal: "Copy task.goal exactly without narrowing it",
  steps: [
    {
      id: "Unique stable step id",
      title: "Short user-visible action",
      skill: "One exact candidate skill id",
      depends_on: ["Earlier step ids required by this step"],
      inputs: [
        {
          name: "One declared skill input",
          source: "task.inputs.<name> or steps.<step-id>.<output-name>",
        },
      ],
      expected_outputs: ["Copy the selected skill outputs exactly"],
      reason: "Why this skill is needed for the original goal",
    },
  ],
  acceptance_mapping: {
    "<acceptance-criterion-id>": ["Plan step ids that satisfy it"],
  },
  capability_gaps: [],
  questions: [],
};

const toolExpansionContract = {
  task_id: "Copy task.id exactly",
  graphs: [
    {
      task_step_id: "One exact TaskGraph step id",
      skill_id: "The exact skill selected by that TaskGraph step",
      nodes: [
        {
          id: "Unique tool node id within this graph",
          tool: "One exact tool id allowed by the skill",
          depends_on: ["Earlier tool node ids in this graph"],
          inputs: [
            {
              name: "One declared tool input",
              source: "skill.inputs.<name> or tools.<tool-node-id>.<output-name>",
            },
          ],
        },
      ],
      exports: [
        {
          name: "One exact selected-skill output",
          source: "tools.<tool-node-id>.<output-name>",
        },
      ],
    },
  ],
};

const messages = [
  {
    role: "system",
    content: `You are a bounded skill-composition planner for a coding agent.
Create an executable dependency plan using only the candidate skills supplied by the user.

Rules:
- Preserve the task id and goal exactly.
- Use only skills whose phases include the task phase.
- Use only skills whose permissions are all present in allowed_permissions.
- Never invent a skill, input, output, permission, or task input.
- Bind every selected skill input to task.inputs.<name> or a declared output of a dependency step.
- Every step-output binding must have the producing step in depends_on.
- Copy every selected skill's outputs into expected_outputs exactly.
- Cover every acceptance criterion in acceptance_mapping.
- Do not select distractors merely because they are available.
- Report a capability gap instead of changing the goal to fit the candidates.
- Do not execute anything and do not claim work has completed.
- Return one JSON object only, without markdown fences or commentary.

Output contract:
${JSON.stringify(responseContract, null, 2)}`,
  },
  {
    role: "user",
    content: JSON.stringify({ task, candidate_skills: skills }, null, 2),
  },
];

function parseJsonContent(content) {
  const cleaned = (content ?? "")
    .trim()
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/, "")
    .replace(/\s*```$/, "");
  return JSON.parse(cleaned);
}

function detectCycle(stepsById) {
  const visiting = new Set();
  const visited = new Set();

  function visit(id) {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    for (const dependency of stepsById.get(id)?.depends_on ?? []) {
      if (stepsById.has(dependency) && visit(dependency)) return true;
    }
    visiting.delete(id);
    visited.add(id);
    return false;
  }

  return [...stepsById.keys()].some(visit);
}

function validatePlan(plan) {
  const errors = [];
  const skillsById = new Map(skills.map((skill) => [skill.id, skill]));
  const steps = Array.isArray(plan?.steps) ? plan.steps : [];
  const stepsById = new Map();

  if (plan?.task_id !== task.id) errors.push("task_id was not preserved");
  if (plan?.goal !== task.goal) errors.push("goal was changed or narrowed");
  if (steps.length < 3 || steps.length > 10) {
    errors.push(`expected 3-10 steps, received ${steps.length}`);
  }

  for (const step of steps) {
    if (!step?.id || stepsById.has(step.id)) {
      errors.push(`duplicate or missing step id: ${step?.id ?? "(missing)"}`);
      continue;
    }
    stepsById.set(step.id, step);
  }

  for (const step of steps) {
    const skill = skillsById.get(step?.skill);
    if (!skill) {
      errors.push(`${step?.id ?? "(missing)"} selected unknown skill ${step?.skill}`);
      continue;
    }
    if (!skill.phases.includes(task.phase)) {
      errors.push(`${step.id} selected ${skill.id} outside phase ${task.phase}`);
    }
    for (const permission of skill.permissions) {
      if (!task.allowed_permissions.includes(permission)) {
        errors.push(`${step.id} requires unauthorized permission ${permission}`);
      }
    }

    const dependencies = Array.isArray(step.depends_on) ? step.depends_on : [];
    for (const dependency of dependencies) {
      if (!stepsById.has(dependency)) {
        errors.push(`${step.id} depends on unknown step ${dependency}`);
      }
      if (dependency === step.id) {
        errors.push(`${step.id} depends on itself`);
      }
    }

    const bindings = Array.isArray(step.inputs) ? step.inputs : [];
    const bindingsByName = new Map(bindings.map((binding) => [binding.name, binding]));
    for (const input of skill.inputs) {
      const binding = bindingsByName.get(input);
      if (!binding) {
        errors.push(`${step.id} did not bind required input ${input}`);
        continue;
      }
      const taskMatch = /^task\.inputs\.([^.]+)$/.exec(binding.source ?? "");
      if (taskMatch) {
        if (!(taskMatch[1] in task.inputs)) {
          errors.push(`${step.id} bound ${input} to unknown task input ${binding.source}`);
        }
        continue;
      }
      const stepMatch = /^steps\.([^.]+)\.([^.]+)$/.exec(binding.source ?? "");
      if (!stepMatch) {
        errors.push(`${step.id} used invalid source ${binding.source} for ${input}`);
        continue;
      }
      const [, producerId, outputName] = stepMatch;
      const producer = stepsById.get(producerId);
      const producerSkill = producer ? skillsById.get(producer.skill) : undefined;
      if (!producer || !producerSkill?.outputs.includes(outputName)) {
        errors.push(`${step.id} bound ${input} to unavailable output ${binding.source}`);
      }
      if (!dependencies.includes(producerId)) {
        errors.push(`${step.id} did not depend on output producer ${producerId}`);
      }
    }
    for (const binding of bindings) {
      if (!skill.inputs.includes(binding.name)) {
        errors.push(`${step.id} invented input ${binding.name} for ${skill.id}`);
      }
    }

    if (
      JSON.stringify(step.expected_outputs ?? [])
      !== JSON.stringify(skill.outputs)
    ) {
      errors.push(`${step.id} did not preserve outputs for ${skill.id}`);
    }
  }

  if (detectCycle(stepsById)) errors.push("plan contains a dependency cycle");

  const selectedSkills = new Set(steps.map((step) => step.skill));
  for (const required of [
    "resolve-workspace-instructions",
    "resolve-operation-assist",
    "implement-teaql-update",
    "edit-rust-source",
    "cargo-check",
  ]) {
    if (!selectedSkills.has(required)) {
      errors.push(`required capability was not selected: ${required}`);
    }
  }

  const acceptanceMapping = plan?.acceptance_mapping ?? {};
  for (const criterion of task.acceptance_criteria) {
    const mappedSteps = acceptanceMapping[criterion.id];
    if (!Array.isArray(mappedSteps) || mappedSteps.length === 0) {
      errors.push(`acceptance criterion was not mapped: ${criterion.id}`);
      continue;
    }
    for (const stepId of mappedSteps) {
      if (!stepsById.has(stepId)) {
        errors.push(`acceptance criterion ${criterion.id} maps unknown step ${stepId}`);
      }
    }
  }

  if (!Array.isArray(plan?.capability_gaps)) {
    errors.push("capability_gaps must be an array");
  } else if (plan.capability_gaps.length > 0) {
    errors.push(`unexpected capability gaps: ${plan.capability_gaps.join("; ")}`);
  }
  if (!Array.isArray(plan?.questions)) {
    errors.push("questions must be an array");
  } else if (plan.questions.length > 0) {
    errors.push(`unexpected questions: ${plan.questions.join("; ")}`);
  }

  return {
    passed: errors.length === 0,
    errors,
    selected_skills: [...selectedSkills],
    step_count: steps.length,
  };
}

function validateToolExpansion(plan, expansion) {
  const errors = [];
  const taskSteps = Array.isArray(plan?.steps) ? plan.steps : [];
  const taskStepsById = new Map(taskSteps.map((step) => [step.id, step]));
  const skillsById = new Map(skills.map((skill) => [skill.id, skill]));
  const toolsById = new Map(tools.map((tool) => [tool.id, tool]));
  const graphs = Array.isArray(expansion?.graphs) ? expansion.graphs : [];
  const graphsByStep = new Map();

  if (expansion?.task_id !== task.id) {
    errors.push("tool expansion did not preserve task_id");
  }

  for (const graph of graphs) {
    if (!graph?.task_step_id || graphsByStep.has(graph.task_step_id)) {
      errors.push(`duplicate or missing tool graph: ${graph?.task_step_id ?? "(missing)"}`);
      continue;
    }
    graphsByStep.set(graph.task_step_id, graph);
  }

  for (const taskStep of taskSteps) {
    const graph = graphsByStep.get(taskStep.id);
    const skill = skillsById.get(taskStep.skill);
    if (!graph) {
      errors.push(`missing tool graph for task step ${taskStep.id}`);
      continue;
    }
    if (graph.skill_id !== taskStep.skill) {
      errors.push(`${taskStep.id} tool graph changed skill identity`);
    }

    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const nodesById = new Map();
    if (nodes.length === 0) {
      errors.push(`${taskStep.id} tool graph is empty`);
    }
    for (const node of nodes) {
      if (!node?.id || nodesById.has(node.id)) {
        errors.push(`${taskStep.id} has duplicate or missing tool node id`);
        continue;
      }
      nodesById.set(node.id, node);
    }

    for (const node of nodes) {
      const tool = toolsById.get(node?.tool);
      if (!tool) {
        errors.push(`${taskStep.id}.${node?.id} selected unknown tool ${node?.tool}`);
        continue;
      }
      if (!(allowedToolsBySkill[taskStep.skill] ?? []).includes(tool.id)) {
        errors.push(`${taskStep.id}.${node.id} selected ${tool.id} outside its skill allowlist`);
      }
      for (const permission of tool.permissions) {
        if (!task.allowed_permissions.includes(permission)) {
          errors.push(`${taskStep.id}.${node.id} requires unauthorized permission ${permission}`);
        }
      }

      const dependencies = Array.isArray(node.depends_on) ? node.depends_on : [];
      for (const dependency of dependencies) {
        if (!nodesById.has(dependency)) {
          errors.push(`${taskStep.id}.${node.id} depends on unknown tool node ${dependency}`);
        }
        if (dependency === node.id) {
          errors.push(`${taskStep.id}.${node.id} depends on itself`);
        }
      }

      const bindings = Array.isArray(node.inputs) ? node.inputs : [];
      const bindingsByName = new Map(bindings.map((binding) => [binding.name, binding]));
      for (const input of tool.inputs) {
        const binding = bindingsByName.get(input);
        if (!binding) {
          errors.push(`${taskStep.id}.${node.id} did not bind required input ${input}`);
          continue;
        }
        const skillMatch = /^skill\.inputs\.([^.]+)$/.exec(binding.source ?? "");
        if (skillMatch) {
          if (!skill?.inputs.includes(skillMatch[1])) {
            errors.push(`${taskStep.id}.${node.id} used unavailable skill input ${binding.source}`);
          }
          continue;
        }
        const toolMatch = /^tools\.([^.]+)\.([^.]+)$/.exec(binding.source ?? "");
        if (!toolMatch) {
          errors.push(`${taskStep.id}.${node.id} used invalid source ${binding.source}`);
          continue;
        }
        const [, producerId, outputName] = toolMatch;
        const producer = nodesById.get(producerId);
        const producerTool = producer ? toolsById.get(producer.tool) : undefined;
        if (!producerTool?.outputs.includes(outputName)) {
          errors.push(`${taskStep.id}.${node.id} used unavailable tool output ${binding.source}`);
        }
        if (!dependencies.includes(producerId)) {
          errors.push(`${taskStep.id}.${node.id} did not depend on tool producer ${producerId}`);
        }
      }
      for (const binding of bindings) {
        if (!tool.inputs.includes(binding.name)) {
          errors.push(`${taskStep.id}.${node.id} invented input ${binding.name}`);
        }
      }
    }

    if (detectCycle(nodesById)) {
      errors.push(`${taskStep.id} tool graph contains a dependency cycle`);
    }

    const exports = Array.isArray(graph.exports) ? graph.exports : [];
    const exportsByName = new Map(exports.map((item) => [item.name, item]));
    for (const output of skill?.outputs ?? []) {
      const exported = exportsByName.get(output);
      if (!exported) {
        errors.push(`${taskStep.id} did not export skill output ${output}`);
        continue;
      }
      const match = /^tools\.([^.]+)\.([^.]+)$/.exec(exported.source ?? "");
      const producer = match ? nodesById.get(match[1]) : undefined;
      const producerTool = producer ? toolsById.get(producer.tool) : undefined;
      if (!match || !producerTool?.outputs.includes(match[2])) {
        errors.push(`${taskStep.id} exported unavailable value ${exported.source}`);
      }
    }
    for (const exported of exports) {
      if (!skill?.outputs.includes(exported.name)) {
        errors.push(`${taskStep.id} invented skill output ${exported.name}`);
      }
    }
  }

  for (const graph of graphs) {
    if (!taskStepsById.has(graph.task_step_id)) {
      errors.push(`tool expansion contains unknown task step ${graph.task_step_id}`);
    }
  }

  const executionNodes = [];
  const terminalNodesByStep = new Map();
  for (const graph of graphs) {
    const localDependents = new Set(
      (graph.nodes ?? []).flatMap((node) => node.depends_on ?? []),
    );
    terminalNodesByStep.set(
      graph.task_step_id,
      (graph.nodes ?? [])
        .filter((node) => !localDependents.has(node.id))
        .map((node) => `${graph.task_step_id}.${node.id}`),
    );
  }
  for (const graph of graphs) {
    const taskStep = taskStepsById.get(graph.task_step_id);
    for (const node of graph.nodes ?? []) {
      const localDependencies = (node.depends_on ?? [])
        .map((id) => `${graph.task_step_id}.${id}`);
      const parentDependencies = (node.depends_on ?? []).length === 0
        ? (taskStep?.depends_on ?? []).flatMap(
          (stepId) => terminalNodesByStep.get(stepId) ?? [],
        )
        : [];
      executionNodes.push({
        id: `${graph.task_step_id}.${node.id}`,
        task_step_id: graph.task_step_id,
        skill_id: graph.skill_id,
        tool: node.tool,
        depends_on: [...parentDependencies, ...localDependencies],
      });
    }
  }
  const executionNodesById = new Map(executionNodes.map((node) => [node.id, node]));
  if (detectCycle(executionNodesById)) {
    errors.push("merged ExecutionGraph contains a dependency cycle");
  }

  const waves = [];
  const completed = new Set();
  while (completed.size < executionNodes.length) {
    const ready = executionNodes.filter(
      (node) => !completed.has(node.id)
        && node.depends_on.every((dependency) => completed.has(dependency)),
    );
    if (ready.length === 0) break;
    waves.push(ready.map((node) => node.id));
    for (const node of ready) completed.add(node.id);
  }
  if (completed.size !== executionNodes.length) {
    errors.push("ExecutionGraph could not be topologically scheduled");
  }

  return {
    passed: errors.length === 0,
    errors,
    graph_count: graphs.length,
    node_count: executionNodes.length,
    execution_waves: waves,
    execution_nodes: executionNodes,
  };
}

async function requestJson(requestMessages, maxTokens = 4096) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(chatUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages: requestMessages,
        temperature: 0,
        top_p: 1,
        max_tokens: maxTokens,
        stream: false,
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(
        `Model request failed: HTTP ${response.status} ${await response.text()}`,
      );
    }
    const result = await response.json();
    const message = result.choices?.[0]?.message;
    if (!message) throw new Error("Model response did not contain a message");
    return {
      value: parseJsonContent(message.content),
      usage: result.usage,
      finish_reason: result.choices?.[0]?.finish_reason,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function requestPlan() {
  const result = await requestJson(messages);
  return {
    plan: result.value,
    usage: result.usage,
    finish_reason: result.finish_reason,
  };
}

async function requestToolExpansion(plan) {
  const expansionMessages = [
    {
      role: "system",
      content: `You expand an approved skill-level TaskGraph into bounded tool-level DAGs.

Rules:
- Preserve task_id, task_step_id, and skill_id exactly.
- Return exactly one graph for every TaskGraph step.
- Use only tools listed in allowed_tools_by_skill for that step's selected skill.
- Bind every tool input to skill.inputs.<name> or an output of a dependency tool node in the same graph.
- Every tool-output binding must name its producer in depends_on.
- Export every selected skill output exactly once from a real tool output.
- Never invent a tool, input, output, permission, task step, or skill.
- Do not execute tools and do not claim completion.
- Return one JSON object only, without markdown fences or commentary.

Output contract:
${JSON.stringify(toolExpansionContract, null, 2)}`,
    },
    {
      role: "user",
      content: JSON.stringify({
        task: {
          id: task.id,
          allowed_permissions: task.allowed_permissions,
        },
        approved_task_graph: plan,
        selected_skill_contracts: Object.fromEntries(
          plan.steps.map((step) => [
            step.id,
            skills.find((skill) => skill.id === step.skill),
          ]),
        ),
        tool_catalog: tools,
        allowed_tools_by_skill: allowedToolsBySkill,
      }, null, 2),
    },
  ];
  const result = await requestJson(expansionMessages, 6144);
  return {
    expansion: result.value,
    usage: result.usage,
    finish_reason: result.finish_reason,
    message_characters: expansionMessages.reduce(
      (total, message) => total + message.content.length,
      0,
    ),
  };
}

if (dryRun) {
  const report = {
    dry_run: true,
    with_tools: withTools,
    endpoint,
    model,
    task,
    candidate_skill_count: skills.length,
    candidate_tool_count: tools.length,
    message_characters: messages.reduce(
      (total, message) => total + message.content.length,
      0,
    ),
  };
  console.log(JSON.stringify(report, null, 2));
} else {
  const startedAt = Date.now();
  const result = await requestPlan();
  const validation = validatePlan(result.plan);
  let toolResult;
  let toolValidation;
  if (withTools && validation.passed) {
    toolResult = await requestToolExpansion(result.plan);
    toolValidation = validateToolExpansion(result.plan, toolResult.expansion);
  }
  const report = {
    endpoint,
    model,
    elapsed_ms: Date.now() - startedAt,
    task,
    candidate_skills: skills,
    plan: result.plan,
    validation,
    usage: result.usage,
    finish_reason: result.finish_reason,
    tool_expansion: toolResult?.expansion,
    tool_validation: toolValidation,
    tool_usage: toolResult?.usage,
    tool_finish_reason: toolResult?.finish_reason,
    tool_message_characters: toolResult?.message_characters,
  };

  if (outputPath) {
    writeFileSync(resolve(outputPath), `${JSON.stringify(report, null, 2)}\n`);
  }
  console.log(JSON.stringify(report, null, 2));
  if (!validation.passed || (withTools && !toolValidation?.passed)) {
    process.exitCode = 1;
  }
}
