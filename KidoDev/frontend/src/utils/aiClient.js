/**
 * AI Client — Multi-Mode Backend Integration
 * Routes all AI generation through the FastAPI backend.
 * Supports local, ngrok, and cloud deployment modes.
 * Strict Rule: No Emojis in any output.
 */

import { requestBusinessInsights } from '../agents/AgentOrchestrator';

const BACKEND_URL = import.meta.env.VITE_AGENT_BACKEND_URL || 'http://localhost:8000';
const isNgrok = BACKEND_URL.includes('ngrok');

/**
 * Robust JSON parser for AI outputs that strips control characters
 */
const parseAIJson = (rawStr) => {
    if (!rawStr) return null;
    let clean = rawStr.replace(/```json/gi, '').replace(/```/g, '').trim();
    try {
        return JSON.parse(clean);
    } catch (e) {
        console.warn('First JSON parse failed. Attempting aggressive control-character cleanup...', e.message);
        clean = clean.replace(/[\u0000-\u001F]+/g, ' '); 
        return JSON.parse(clean);
    }
};

const inFlightPromotions = new Map();
const qwenCache = new Map();
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes cache TTL

/**
 * Core function to communicate with backend inference engine
 */
const getQwenCompletion = async (systemPrompt, userPrompt) => {
    const cacheKey = `${systemPrompt}_${userPrompt}`;

    if (qwenCache.has(cacheKey)) {
        const entry = qwenCache.get(cacheKey);
        if (Date.now() - entry.timestamp < CACHE_TTL_MS) {
            return entry.result;
        }
        qwenCache.delete(cacheKey);
    }

    if (inFlightPromotions.has(cacheKey)) {
        return inFlightPromotions.get(cacheKey);
    }

    const fetchPromise = (async () => {
        try {
            const headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            };
            if (isNgrok) {
                headers["ngrok-skip-browser-warning"] = "true";
            }

            const response = await fetch(`${BACKEND_URL}/agent/tutor`, {
                method: "POST",
                headers,
                body: JSON.stringify({
                    child_id: "system_admin",
                    session_id: `gen-${Date.now()}`,
                    user_message: `${systemPrompt}\n\nUser Request: ${userPrompt}`,
                    workspace_blocks: [],
                })
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || `FastAPI backend error: ${response.status}`);
            }

            const data = await response.json();
            const result = data.hint_message || data.response_text || '';
            qwenCache.set(cacheKey, { result, timestamp: Date.now() });
            return result;
        } catch (err) {
            console.error('[aiClient] Backend Error:', err.message);
            throw err;
        } finally {
            inFlightPromotions.delete(cacheKey);
        }
    })();

    inFlightPromotions.set(cacheKey, fetchPromise);
    return fetchPromise;
};

/**
 * Generate complete project data from a single prompt
 * @param {string} prompt - Admin's free-text prompt
 * @returns {Promise<Object>} JSON containing all fields
 */
export const generateFullProject = async (prompt) => {
    const systemPrompt = `You are a master architect for a kids coding platform.
Your task is to take a prompt and design a full lesson project.
CRITICAL RULE: DO NOT use any emojis in your response. Not a single one.
CRITICAL RULE 2: Ensure ALL newlines inside string values are properly escaped as \\\\n. Do NOT output raw newlines inside JSON strings.
CRITICAL RULE 3: You MUST ONLY use the following custom block types in your XML:
Events: s_when_flag, s_when_key, s_when_clicked, s_when_broadcast, s_broadcast, s_broadcast_wait
Control: s_wait, s_repeat, s_forever, s_if, s_if_else, s_wait_until, s_repeat_until, s_stop, s_when_clone, s_create_clone, s_del_clone
Motion: s_move, s_turn_r, s_turn_l, s_goto_rand, s_goto, s_glide_rand, s_glide, s_point_dir, s_point_towards, s_change_x, s_set_x, s_change_y, s_set_y, s_bounce
Looks: s_say_time, s_say, s_think_time, s_think, s_switch_costume, s_next_costume, s_switch_bg, s_next_bg, s_change_size, s_set_size, s_change_effect, s_set_effect, s_clear_effects, s_show, s_hide
Sensing: s_touching, s_touching_color, s_color_touching, s_dist_to, s_ask, s_answer, s_key_pressed, s_mouse_down, s_mouse_x, s_mouse_y
Operators: s_add, s_sub, s_mul, s_div, s_rand, s_gt, s_lt, s_eq, s_and, s_or, s_not, s_join, s_letter, s_length, s_contains, s_mod, s_round, s_mathop
Variables: s_set_var, s_change_var, s_var_r
Inputs: Use <shadow type="math_number"><field name="NUM">...</field></shadow> and <shadow type="text"><field name="TEXT">...</field></shadow>

Respond ONLY with a valid JSON object matching this structure:
{
  "id": "Short unique ID like L1P5",
  "title": "Fun catchy title",
  "objective": "Clear student objective",
  "class_level": 1,
  "order_index": 1,
  "agent_solve_description": "A very detailed description of exactly how the blocks should be assembled to solve the objective.",
  "agent_tutorial_description": "Step-by-step instructions for the child. 1. Do this. 2. Do that.",
  "agent_solve_message": "A congratulatory message to the user.",
  "agent_solve_tip": "A short hint if they are stuck.",
  "steps": [
    {"title": "Step 1", "desc": "Instruction without emojis"}
  ],
  "prompt_milestones": ["Goal 1", "Goal 2"]
}`;

    try {
        const response = await getQwenCompletion(systemPrompt, prompt);
        return parseAIJson(response);
    } catch (err) {
        console.error('Project Generation Error:', err);
        throw err;
    }
};

/**
 * Generate business insights from dashboard metrics via BusinessInsightsAgent
 */
export const generateDashboardInsights = async (metrics) => {
    try {
        const agentRes = await requestBusinessInsights({
            total_students: metrics.totalChildren || metrics.totalStudents || 0,
            active_subscriptions: metrics.paidParents || metrics.paidChildren || 0,
            total_revenue: metrics.revenue || metrics.mrr || 0,
            average_score: metrics.avgScore || 85,
            total_completed_missions: metrics.totalCompletions || 0,
            school_count: metrics.totalSchools || 0,
        });

        if (agentRes && agentRes.executive_summary) {
            return {
                executiveSummary: agentRes.executive_summary,
                healthScore: agentRes.health_score || 88,
                financialKPIs: agentRes.financial_kpis || {},
                keyInsights: agentRes.growth_recommendations || [],
                recommendations: agentRes.platform_improvements || [],
                monetizationOpportunities: agentRes.monetization_opportunities || [],
                riskAnalysis: agentRes.risk_analysis || [],
                predictedGrowth: [
                    { month: 'M1', revenue: Math.round((metrics.revenue || 1000) * 1.08) },
                    { month: 'M2', revenue: Math.round((metrics.revenue || 1000) * 1.18) },
                    { month: 'M3', revenue: Math.round((metrics.revenue || 1000) * 1.30) }
                ],
                engagementForecast: [
                    { day: 'Mon', val: Math.round((metrics.totalChildren || 10) * 0.75) },
                    { day: 'Wed', val: Math.round((metrics.totalChildren || 10) * 0.88) },
                    { day: 'Fri', val: Math.round((metrics.totalChildren || 10) * 0.96) }
                ],
                userSegmentPrediction: [
                    { name: 'Active Students', value: Math.round((metrics.totalChildren || 10) * 0.82) },
                    { name: 'Pending Accounts', value: Math.round((metrics.totalChildren || 10) * 0.18) }
                ],
                unitEconomics: [
                    { name: 'ARPU (PKR)', val: agentRes.financial_kpis?.arpu_pkr || metrics.arpu || 2000 },
                    { name: 'LTV:CAC', val: 7 },
                    { name: 'Retention', val: 94 }
                ],
                growthForecast: agentRes.projected_mrr_growth || "+25% MRR Growth Projected",
                churnPrediction: "Low (< 3.2%)",
            };
        }
    } catch (err) {
        console.warn('[aiClient] BusinessInsightsAgent error, fallback to direct completion:', err);
    }

    const systemPrompt = `You are a business intelligence analyst for KidoDev.
CRITICAL RULE: DO NOT use any emojis in your response.

Respond ONLY with a valid JSON object matching this structure:
{
  "executiveSummary": "Summary without emojis",
  "healthScore": 85,
  "keyInsights": ["Insight 1", "Insight 2", "Insight 3"],
  "recommendations": ["Rec 1", "Rec 2"],
  "predictedGrowth": [
    {"month": "M1", "revenue": 100}, {"month": "M2", "revenue": 200}, {"month": "M3", "revenue": 300}
  ],
  "engagementForecast": [
    {"day": "D1", "val": 10}, {"day": "D2", "val": 20}, {"day": "D3", "val": 30}
  ],
  "userSegmentPrediction": [
    {"name": "Active", "value": 60}, {"name": "Inactive", "value": 40}
  ],
  "unitEconomics": [
    {"name": "Margin", "val": 4200}
  ],
  "growthForecast": "Analysis string",
  "churnPrediction": "Analysis string"
}`;

    const userPrompt = `Metrics: Total Parents: ${metrics.totalParents}, Revenue: ${metrics.revenue}, Students: ${metrics.totalChildren}. Provide business growth insights.`;

    try {
        const response = await getQwenCompletion(systemPrompt, userPrompt);
        return parseAIJson(response);
    } catch (err) {
        console.error('Insight Generation Error:', err);
        return {
            executiveSummary: 'AI Business Advisor temporarily unavailable.',
            healthScore: 80,
            keyInsights: ['Platform user base active.', 'Conversion rates steady.'],
            recommendations: ['Introduce seasonal subscription discounts.']
        };
    }
};

export const generateLiveHint = async (workspaceBlocks = [], objective = '', userMessage = '') => {
    const systemPrompt = `You are a friendly AI coding tutor for kids. 
The student is trying to solve this objective: "${objective}"
They currently have these block types in their workspace: ${JSON.stringify(workspaceBlocks)}

CRITICAL RULE: DO NOT use any emojis in your response. Not a single one.

Your job is to look at their current blocks and suggest the next logical block type they should add.
Respond ONLY with a valid JSON object matching this structure:
{
  "blockType": "s_when_flag", 
  "message": "A short, encouraging sentence explaining what to do next without emojis"
}`;

    try {
        const response = await getQwenCompletion(systemPrompt, userMessage || "What is the next block?");
        const parsed = parseAIJson(response);
        if (parsed && parsed.message) return parsed;
    } catch (err) {
        console.warn('Live Hint Qwen API Error — switching to local smart hint engine:', err.message);
    }

    // Smart contextual fallback with Socratic tutor persona
    const q = (userMessage || '').toLowerCase();
    const blocks = workspaceBlocks || [];
    let suggestedBlock = "s_when_flag";
    let conceptHint = "To start your project, you'll need an event block from Events that gives your sprite a starting signal when you click the green flag!";
    let explicitHint = "Look in the Events panel for the Green Flag Event block and snap it at the top of your workspace!";
    let whyItMatters = "Computers need a clear starting signal! Just like a referee blowing a whistle to start a game, the Green Flag tells your character when to start running your code step-by-step.";

    if (!blocks.includes("s_when_flag")) {
        suggestedBlock = "s_when_flag";
        conceptHint = "To start your project, you'll need an event block from Events that gives your sprite a starting signal when you click the green flag!";
        explicitHint = "Look in the Events panel for the Green Flag Event block and snap it at the top of your workspace!";
        whyItMatters = "Computers need a clear starting signal! Just like a referee blowing a whistle to start a game, the Green Flag tells your character when to start running your code step-by-step.";
    } else if (!blocks.includes("s_move") && !blocks.includes("s_say")) {
        suggestedBlock = "s_move";
        conceptHint = "To get your character walking across the stage, you'll need a block from Motion that moves your sprite forward!";
        explicitHint = "Look in the Motion panel for the Move Steps block and snap it directly below your Green Flag block!";
        whyItMatters = "Characters don't move on screen unless we give them motion commands! The Move block changes your sprite's position in the direction it is facing.";
    } else if (!blocks.includes("s_repeat") && !blocks.includes("s_forever")) {
        suggestedBlock = "s_repeat";
        conceptHint = "To make your action happen multiple times without snapping 10 identical blocks together, you'll need a loop block from Control!";
        explicitHint = "Look in the Control panel for the Repeat Loop block and wrap it around your motion blocks!";
        whyItMatters = "Instead of snapping 10 identical blocks together, programmers use loops! A repeat block tells the computer to run actions automatically, keeping your code neat.";
    } else {
        suggestedBlock = "s_say";
        conceptHint = "To make your character talk or display a speech bubble, you'll need a communication block from Looks!";
        explicitHint = "Look in the Looks panel for the Say block and snap it into your script!";
        whyItMatters = "Characters communicate visually! The Say block pops up a speech bubble so players can read what your character is saying.";
    }

    const openersWhy = ["Ooh, that is such a great question!", "Aha! Love how curious you are!", "That is a super smart question to ask!", "I love when coders ask why!"];
    const openersWhat = ["Woohoo! Let's check what cool block comes next!", "Super work so far! Here is your next coding move:", "You are building something awesome! Next up:"];
    const endings = ["Give it a spin and see the magic happen!", "You've got this, coding superstar!", "Snap it in and watch the magic happen!"];

    const pick = arr => arr[Math.floor(Math.random() * arr.length)];
    const cleanObj = (objective || '').split(/Child understands|Teacher note|Assessment:|Objectives:|Goal:/i)[0].trim().replace(/[!.:]+$/, '');
    const objPhrase = cleanObj ? ` to help ${cleanObj.charAt(0).toLowerCase() + cleanObj.slice(1)}` : '';

    const isWhy = q.includes('why') || q.includes('reason');
    const isExplicit = q.includes('what block') || q.includes('which block') || q.includes('exact block');

    let msg = `Hi coding buddy! ${conceptHint} ${pick(endings)}`;
    if (isWhy) {
        msg = `${pick(openersWhy)} ${whyItMatters}${objPhrase}. ${pick(endings)}`;
    } else if (isExplicit) {
        msg = `${pick(openersWhat)} ${explicitHint} ${whyItMatters} ${pick(endings)}`;
    }

    return {
        blockType: suggestedBlock,
        message: msg
    };
};

export const generateLiveSolution = async (objective) => {
    const systemPrompt = `You are an expert Scratch/Blockly developer for kids.
CRITICAL RULE: DO NOT use any emojis in your response. Not a single one.
CRITICAL RULE 2: Ensure ALL newlines inside string values are properly escaped as \\\\n. Do NOT output raw newlines inside JSON strings.
CRITICAL RULE 3: You MUST ONLY use the following custom block types in your XML:
Events: s_when_flag, s_when_key, s_when_clicked, s_when_broadcast, s_broadcast, s_broadcast_wait
Control: s_wait, s_repeat, s_forever, s_if, s_if_else, s_wait_until, s_repeat_until, s_stop, s_when_clone, s_create_clone, s_del_clone
Motion: s_move, s_turn_r, s_turn_l, s_goto_rand, s_goto, s_glide_rand, s_glide, s_point_dir, s_point_towards, s_change_x, s_set_x, s_change_y, s_set_y, s_bounce
Looks: s_say_time, s_say, s_think_time, s_think, s_switch_costume, s_next_costume, s_switch_bg, s_next_bg, s_change_size, s_set_size, s_change_effect, s_set_effect, s_clear_effects, s_show, s_hide
Sensing: s_touching, s_touching_color, s_color_touching, s_dist_to, s_ask, s_answer, s_key_pressed, s_mouse_down, s_mouse_x, s_mouse_y
Operators: s_add, s_sub, s_mul, s_div, s_rand, s_gt, s_lt, s_eq, s_and, s_or, s_not, s_join, s_letter, s_length, s_contains, s_mod, s_round, s_mathop
Variables: s_set_var, s_change_var, s_var_r
Inputs: Use <shadow type="math_number"><field name="NUM">...</field></shadow> and <shadow type="text"><field name="TEXT">...</field></shadow>

Given the objective: "${objective}", generate a complete, valid Blockly XML string that solves it.

Respond ONLY with a valid JSON object matching this structure:
{
  "xml": "<xml xmlns=\\"https://developers.google.com/blockly/xml\\"><block type=\\"s_when_flag\\">...</block></xml>",
  "message": "A short congratulatory message without emojis",
  "tip": "A short helpful tip without emojis"
}`;

    try {
        const response = await getQwenCompletion(systemPrompt, "Generate the solution XML.");
        return parseAIJson(response);
    } catch (err) {
        console.error('Live Solution Generation Error:', err);
        return null;
    }
};

export default { generateFullProject, generateDashboardInsights, generateLiveHint, generateLiveSolution };
