const PptxGenJS = require('pptxgenjs');
const path = require('path');

const pptx = new PptxGenJS();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Stefano Rigante · Physics-First AI';
pptx.subject = 'AMD AI DevMaster Hackathon 2026 · Track 2';
pptx.title = 'NuclidePath — Private Physics-First Agent';
pptx.company = 'Physics-First AI';
pptx.lang = 'en-US';
pptx.theme = {
  headFontFace: 'Liberation Sans', bodyFontFace: 'Liberation Sans', lang: 'en-US'
};
pptx.defineLayout({ name: 'WIDE', width: 13.333, height: 7.5 });
pptx.layout = 'WIDE';
pptx.margin = 0;

const C = { bg:'08090B', layer:'15171A', layer2:'202328', line:'363A40', text:'F5F7FA', muted:'A7ADB5', orange:'FF6B00', orange2:'FF9B57', green:'42BE65', blue:'78A9FF', purple:'BE95FF', yellow:'F1C21B', red:'FA4D56', white:'FFFFFF', black:'000000' };
const root = path.resolve(__dirname, '..');
const asset = name => path.join(root, 'docs', 'assets', name);
const out = path.join(root, 'submission', 'NuclidePath_Track2_Deck.pptx');

function bg(slide, color=C.bg){ slide.background={color}; }
function rect(slide,x,y,w,h,fill=C.layer,line=C.line,trans=0){ slide.addShape(pptx.ShapeType.rect,{x,y,w,h,fill:{color:fill,transparency:trans},line:{color:line,width:1}}); }
function text(slide,value,x,y,w,h,size=18,color=C.text,opts={}){ slide.addText(value,{x,y,w,h,fontFace:opts.fontFace||'Liberation Sans',fontSize:size,color,bold:!!opts.bold,margin:opts.margin===undefined?0:opts.margin,align:opts.align||'left',valign:opts.valign||'mid',breakLine:false,fit:'shrink',...opts}); }
function title(slide,kicker,heading,subtitle){ text(slide,kicker.toUpperCase(),0.62,0.35,5.8,0.28,10,C.orange,{bold:true,charSpacing:1.8}); text(slide,heading,0.62,0.68,12.0,0.58,30,C.text,{bold:false}); if(subtitle) text(slide,subtitle,0.64,1.25,11.8,0.38,13,C.muted); }
function footer(slide,n){ text(slide,'PHYSICS-FIRST AI  ·  AMD AI DEVMASTER 2026  ·  TRACK 2',0.62,7.16,8.2,0.18,8,C.muted,{charSpacing:1}); text(slide,String(n).padStart(2,'0'),12.16,7.13,0.55,0.22,9,C.orange,{fontFace:'Liberation Mono',align:'right'}); }
function card(slide,x,y,w,h,label,body,color=C.orange){ rect(slide,x,y,w,h,C.layer,C.line); slide.addShape(pptx.ShapeType.rect,{x,y,w:0.08,h,fill:{color},line:{color}}); text(slide,label,x+0.24,y+0.18,w-0.38,0.28,14,C.text,{bold:true}); if(body) text(slide,body,x+0.24,y+0.55,w-0.38,h-0.7,11.5,C.muted,{valign:'top',breakLine:true}); }
function stat(slide,x,y,w,value,label,color=C.orange){ text(slide,value,x,y,w,0.72,36,color,{fontFace:'Liberation Mono',bold:true}); text(slide,label,x,y+0.72,w,0.34,11,C.muted,{valign:'top'}); }
function pill(slide,x,y,w,label,color=C.green){ slide.addShape(pptx.ShapeType.roundRect,{x,y,w,h:0.32,rectRadius:0.08,fill:{color,transparency:78},line:{color,width:1}}); text(slide,label,x+0.08,y+0.02,w-0.16,0.24,9,color,{bold:true,align:'center'}); }
function notes(slide,body){ slide.addNotes(body); }

// 1 — Title
{
 const s=pptx.addSlide(); bg(s);
 slide=s; // eslint-disable-line no-undef
 s.addShape(pptx.ShapeType.rect,{x:0,y:0,w:0.18,h:7.5,fill:{color:C.orange},line:{color:C.orange}});
 text(s,'AMD AI DEVMASTER 2026 · TRACK 2',0.7,0.52,4.4,0.28,11,C.orange,{bold:true,charSpacing:1.6});
 text(s,'NuclidePath',0.7,1.12,5.0,0.82,42,C.text,{bold:true});
 text(s,'Private agents.\nDeterministic physics.',0.72,2.03,4.65,1.25,29,C.text,{bold:false,valign:'top'});
 text(s,'A local AI workflow for traceable Cs-137 groundwater screening — with cited evidence, uncertainty and zero LLM-generated physics.',0.72,3.55,4.65,1.02,15,C.muted,{valign:'top'});
 pill(s,0.72,4.85,1.48,'LOCAL ONLY',C.green); pill(s,2.35,4.85,1.42,'AMD ROCm',C.orange);
 text(s,'PHYSICS-FIRST AI',0.72,6.55,3.4,0.28,12,C.text,{bold:true}); text(s,'Stefano Rigante · Nuclear engineer',0.72,6.86,3.8,0.24,10,C.muted);
 s.addImage({path:asset('dashboard.png'),x:5.48,y:0.62,w:7.35,h:4.60,altText:'NuclidePath verified local dashboard'});
 rect(s,5.48,5.25,7.35,1.27,C.layer,C.line);
 stat(s,5.77,5.46,2.0,'5/5','Track 2 capabilities',C.green); stat(s,8.15,5.46,2.0,'231','AMD core snapshot',C.blue); stat(s,10.45,5.46,2.0,'377/15','latest CI gate',C.orange);
 notes(s,'Open with the core promise: AI coordinates the workflow, but deterministic code owns every physical number.');
}

// 2 — Problem
{
 const s=pptx.addSlide(); bg(s); title(s,'The trust gap','Technical AI fails when language becomes calculation','NuclidePath makes the responsibility boundary explicit and testable.');
 card(s,0.65,1.95,3.62,3.75,'01 · The failure mode','A general-purpose LLM can invent parameters, equations, units or reassuring conclusions — all unacceptable in emergency-analysis workflows.',C.red);
 card(s,4.85,1.95,3.62,3.75,'02 · The boundary','The model returns only a six-step allow-listed plan. Strict schemas feed deterministic physics, retrieval and uncertainty tools.',C.orange);
 card(s,9.05,1.95,3.62,3.75,'03 · The outcome','Every value is versioned, reproducible and tied to inputs, assumptions, sources, warnings and SHA-256 artifacts.',C.green);
 text(s,'PLAN',1.65,6.02,1.0,0.35,18,C.red,{fontFace:'Liberation Mono',bold:true,align:'center'});
 s.addShape(pptx.ShapeType.line,{x:2.72,y:6.2,w:2.5,h:0,line:{color:C.muted,width:2,beginArrowType:'none',endArrowType:'triangle'}});
 text(s,'TOOLS',5.28,6.02,1.15,0.35,18,C.orange,{fontFace:'Liberation Mono',bold:true,align:'center'});
 s.addShape(pptx.ShapeType.line,{x:6.55,y:6.2,w:2.5,h:0,line:{color:C.muted,width:2,endArrowType:'triangle'}});
 text(s,'EVIDENCE',9.17,6.02,1.6,0.35,18,C.green,{fontFace:'Liberation Mono',bold:true,align:'center'});
 footer(s,2); notes(s,'Explain the failure mode, then the boundary and auditable result. Avoid claiming operational validation.');
}

// 3 — Architecture
{
 const s=pptx.addSlide(); bg(s); title(s,'System design','A private workflow with an immutable physics boundary','The AMD-local model plans. Five deterministic subsystems execute and report.');
 s.addImage({path:asset('architecture.svg'),x:0.72,y:1.64,w:11.9,h:4.98,altText:'NuclidePath architecture diagram'});
 footer(s,3); notes(s,'Walk left-to-right. Emphasize localhost, permission gate, local RAG, deterministic transport and checksummed outputs.');
}

// 4 — Capabilities
{
 const s=pptx.addSlide(); bg(s); title(s,'Track 2','All five private-agent capabilities are implemented','Each capability is exercised in the same end-to-end run and covered by tests.');
 const items=[
  ['01','Local retrieval','Ranked excerpts, local paths, source URLs and transparent scores.',C.purple],
  ['02','Tool invocation','Environment Agent calls a strict, versioned JSON physics contract.',C.orange],
  ['03','Multi-step planning','Deterministic fallback or Qwen3.5-9B returns six safe steps.',C.blue],
  ['04','Multi-turn memory','Session JSONL stays local, mode 0600, with explicit deletion.',C.green],
  ['05','Permissions + privacy','Role allowlist, recursive redaction and denied operational actions.',C.red]
 ];
 items.forEach((it,i)=>{const x=0.66+(i%3)*4.18; const y=1.85+Math.floor(i/3)*2.16; rect(s,x,y,3.72,1.78,C.layer,C.line); text(s,it[0],x+0.2,y+0.15,0.6,0.34,14,it[3],{fontFace:'Liberation Mono',bold:true}); text(s,it[1],x+0.82,y+0.13,2.65,0.38,17,C.text,{bold:true}); text(s,it[2],x+0.2,y+0.68,3.26,0.72,11.5,C.muted,{valign:'top'}); pill(s,x+0.2,y+1.4,0.92,'VERIFIED',it[3]);});
 stat(s,9.55,4.22,2.1,'5/5','capability flags true',C.green);
 text(s,'One workflow. One privacy boundary. No cloud dependency.',9.55,5.32,2.55,0.75,18,C.text,{bold:true,valign:'top'});
 footer(s,4); notes(s,'The official requirement is at least two of five; NuclidePath implements all five.');
}

// 5 — Physics
{
 const s=pptx.addSlide(); bg(s); title(s,'Scientific core','The LLM never calculates transport','Model 0.3 declares PDE, source and boundaries, then uses a verified analytical solution.');
 rect(s,0.68,1.78,6.2,4.72,'0D1014',C.line);
 text(s,'R ∂C/∂t = D ∂²C/∂x² − v ∂C/∂x − λRC\n\nC(x,0)=0 · C(0,t)=C₀ · C(∞,t)=0\n\nA = √(v² + 4λRD)\n\nC/C₀ = ½[exp((v−A)x/2D) erfc(z₋)\n          + exp((v+A)x/2D) erfc(z₊)]',1.05,2.10,5.48,3.5,17,C.orange2,{fontFace:'Liberation Mono',valign:'top'});
 pill(s,1.05,5.92,2.15,'REACTIVE OGATA–BANKS',C.green);
 stat(s,7.48,1.93,2.2,'231','AMD core snapshot',C.blue);
 stat(s,10.05,1.93,2.2,'0','LLM physics values',C.green);
 card(s,7.48,3.18,5.18,1.25,'Independent analytical cases','Ogata–Banks limit · source boundary · reactive steady state · finite rejection',C.blue);
 card(s,7.48,4.68,5.18,1.25,'Explicit limitation','Constant-source 1-D screening — not a dose code, regulatory model or calibrated site prediction.',C.yellow);
 card(s,7.48,6.08,5.18,0.85,'Multicomponent bridge (opt-in)','GCS K/Na competition + NH₄ on FES; extended K/Na/Ca/Mg path is process-qualified, not promoted.',C.purple);
 footer(s,5); notes(s,'Describe the formulas and say validation means software/formula verification, not regulatory validation. The multicomponent K/Na/Ca/Mg bridge is opt-in and process-qualified only; the canonical Cs–K GCS path remains authoritative.');
}

// 5.5 — Recent extensions (post-merge work)
{
 const s=pptx.addSlide(); bg(s); title(s,'Recent extensions','Traceable post-merge science','The latest work adds deterministic, auditable layers around the canonical screening path.');
 stat(s,0.72,1.82,3.0,'388/2','AMD post-merge tests',C.green);
 stat(s,4.02,1.82,3.0,'4','ions · K/Na/Ca/Mg',C.blue);
 stat(s,7.32,1.82,2.7,'2×','fixtures · brine/recharge',C.orange);
 stat(s,10.42,1.82,2.1,'0','unqualified claims',C.purple);
 const rows=[
  ['PHREEQC bridge','Opt-in scenario compiler: declared water chemistry, CEC and Cs + K/Na/Ca/Mg into SOLUTION/EXCHANGE/TRANSPORT input'],
  ['Arithmetic oracle','Independent machine-readable checks for units, grid mapping, non-negativity and exchange-site occupancy'],
  ['Calibration gate','Dependency-free traceable Cs calibration/hold-out contract with fail-closed promotion; no data bundled'],
  ['Benchmark registry','Separate EPA/Fuller/Dubus external Cs registry with source digests and calibration_eligible: false']
 ];
 rect(s,0.72,3.30,12.0,2.85,C.layer,C.line);
 rows.forEach((r,i)=>{const y=3.55+i*0.62; text(s,r[0],1.00,y,2.6,0.30,12,C.orange,{bold:true}); text(s,r[1],3.75,y,8.6,0.55,11.5,C.text,{valign:'top',breakLine:true});});
 pill(s,0.72,6.45,3.6,'PROCESS-QUALIFIED ONLY',C.yellow);
 text(s,'Canonical transport-prototype-0.3 remains authoritative; the bridge is opt-in and does not replace it.',0.72,6.85,11.0,0.30,10.5,C.muted);
 footer(s,6); notes(s,'Present the recent work as deterministic, tested and honestly scoped: the PHREEQC bridge is process-qualified, not calibrated chemistry. The canonical screening path is unchanged and authoritative.');
}

// 6 — AMD
{
 const s=pptx.addSlide(); bg(s); title(s,'AMD deployment','Qwen3.5-9B Q8 runs locally on Radeon + ROCm','The measured local model fits in VRAM and produced the verified allow-listed plan.');
 stat(s,0.72,1.82,3.0,'2,877.30','prompt tokens/s · 512 tokens',C.orange);
 stat(s,4.02,1.82,3.0,'67.66','generation tokens/s · 128 tokens',C.blue);
 stat(s,7.32,1.82,2.7,'19.9692 s','AMD v0.3 LLM pipeline',C.green);
 stat(s,10.42,1.82,2.1,'8.86 GiB','Q8 model size',C.purple);
 const rows=[
  ['GPU','AMD Radeon Graphics · gfx1100'],['Stack','ROCm 7.2.1 · llama.cpp HIP Release'],['Offload','-ngl 99 · all model layers'],['Context','8192 tokens · reasoning off'],['Network','127.0.0.1:8000 only'],['Integrity','SHA-256 verified model file']
 ];
 rows.forEach((r,i)=>{const y=3.42+i*0.48; text(s,r[0],0.85,y,1.35,0.32,11,C.muted,{fontFace:'Liberation Mono'}); text(s,r[1],2.25,y,4.65,0.32,12,C.text,{bold:true});});
 rect(s,7.35,3.35,5.2,2.78,C.layer,C.line); text(s,'OFFLINE  ≡  LLM-PLANNED',7.72,3.80,4.45,0.54,24,C.green,{fontFace:'Liberation Mono',bold:true,align:'center'}); text(s,'Identical physical runs\nfor the same scenario',8.02,4.62,3.85,0.82,17,C.text,{align:'center',valign:'top'}); pill(s,9.12,5.50,1.67,'PHYSICS IDENTICAL',C.green);
 footer(s,7); notes(s,'Quote measured numbers only. The dated AMD v0.3 core-platform snapshot is verified; the equality check compares physical runs, not timestamped memory files.');
}

// 7 — Product
{
 const s=pptx.addSlide(); bg(s); title(s,'Product experience','A technical dashboard, not an AI chat box','Inputs, workflow, evidence, uncertainty and artifacts remain visible in one place.');
 s.addImage({path:asset('dashboard.png'),x:0.72,y:1.70,w:8.35,h:5.15,altText:'NuclidePath dashboard overview'});
 card(s,9.42,1.72,3.22,1.35,'Editable physics','Kd, K+, velocity, porosity, distance and C₀.',C.orange);
 card(s,9.42,3.28,3.22,1.35,'Visible agency','Six completed steps and 5/5 capability badges.',C.green);
 card(s,9.42,4.84,3.22,1.35,'Auditable output','Ten downloadable artifacts plus a checksum manifest.',C.blue);
 footer(s,8); notes(s,'Run the live UI in the video. This slide is a fallback visual and repository preview.');
}

// 8 — Uncertainty & provenance
{
 const s=pptx.addSlide(); bg(s); title(s,'Trust layer','Uncertainty is declared, classified and reproducible','The project distinguishes literature evidence from demonstration inputs.');
 s.addImage({path:asset('uncertainty-dashboard.png'),x:0.72,y:1.68,w:7.65,h:4.79,altText:'NuclidePath uncertainty dashboard'});
 card(s,8.70,1.72,3.95,1.35,'Literature-informed range','Cs Kd: 0.05–5.0 m³/kg · IAEA TECDOC-2095',C.purple);
 card(s,8.70,3.28,3.95,1.35,'Demonstration ranges','Hydraulics, dispersion, K+ and empirical competition are never presented as site truth.',C.yellow);
 card(s,8.70,4.84,3.95,1.35,'Reproducible propagation','Seeded Monte Carlo · P05/P50/P95 · JSON/CSV/SVG',C.green);
 footer(s,9); notes(s,'Stress that reported intervals are input-range propagation, not total predictive uncertainty.');
}

// 9 — Close
{
 const s=pptx.addSlide(); bg(s);
 text(s,'WHY NUCLIDEPATH WINS',0.72,0.55,4.2,0.3,11,C.orange,{bold:true,charSpacing:1.8});
 text(s,'Private AI without\nscientific surrender.',0.72,1.20,6.15,1.52,36,C.text,{bold:true,valign:'top'});
 const claims=[['LOCAL','Qwen3.5-9B + RAG + memory on AMD'],['VERIFIABLE','388 AMD post-merge tests + FP64 parity + SHA-256'],['USEFUL','One-click workflow from case to report'],['HONEST','PHREEQC bridge explicit; no unqualified science']];
 claims.forEach((c,i)=>{const y=3.25+i*0.72; text(s,c[0],0.82,y,1.4,0.34,12,[C.green,C.blue,C.orange,C.yellow][i],{fontFace:'Liberation Mono',bold:true}); text(s,c[1],2.30,y,4.6,0.34,16,C.text,{bold:true});});
 rect(s,7.55,0.72,5.08,5.98,C.layer,C.line);
 text(s,'The proof',7.95,1.10,2.0,0.36,20,C.text,{bold:true});
 stat(s,7.95,1.78,2.0,'5/5','Track 2 capabilities',C.green); stat(s,10.27,1.78,1.85,'388','AMD tests (post-merge)',C.blue);
 stat(s,7.95,3.05,2.0,'132.8×','FP64 platform (post-merge)',C.orange); stat(s,10.27,3.05,1.85,'0','cloud calls',C.purple);
 text(s,'Track 2 · Physics-First AI · NuclidePath',7.95,4.58,4.0,0.35,15,C.text,{bold:true});
 text(s,'Official AMD Track 2 PR package',7.95,5.15,4.0,0.32,12,C.blue,{fontFace:'Liberation Mono'});
 pill(s,7.95,5.80,2.05,'TECHNICAL BUILD VERIFIED',C.green);
 text(s,'THANK YOU',0.72,6.65,2.2,0.32,11,C.muted,{charSpacing:2});
 notes(s,'Close on current evidence: local, tested, reproducible and honest about scope. The 132.8× result is the measured device-resident FP64 primary-GCS to receptor pipeline versus the scalar reference, reproduced in the 5 August post-merge AMD rerun alongside the 388 passing tests (the 28 July core snapshot measured 137.09× on the same pipeline). This is a performance result, not environmental validation.');
}

require('fs').mkdirSync(path.dirname(out),{recursive:true});
(async () => {
  await pptx.writeFile({fileName:out});
  console.log(out);
})().catch(error => {
  console.error(error);
  process.exit(1);
});
