export type SceneType='concert'|'festival'|'lecture'|'competition'|'commercial'|'custom';
export interface UploadedAsset{id:string;name:string;type:string;dataUrl:string;category:'person'|'venue'|'logo'|'qr'|'reference';status:'success'|'error';error?:string}
export type PosterLanguage='en'|'zh';
export interface Participant{id:string;name:string;nameEn?:string;genre:string;genreEn?:string;logo?:UploadedAsset;groupPhoto?:UploadedAsset;keyPhoto?:UploadedAsset}
export interface StylePreset{id:string;name:string;colors:string[];composition:string;tagline:string}
export interface OutputOptions{poster:boolean;teaser:boolean;vj:boolean}
export interface PosterProject{id:string;scene?:SceneType;posterLanguage?:PosterLanguage;title:string;titleEn?:string;theme:string;themeEn?:string;dateTime:string;city:string;cityEn?:string;venue:string;venueEn?:string;subject:string;subjectEn?:string;price:string;ticketInfo:string;ticketInfoEn?:string;bands:Participant[];speakerName:string;speakerBio:string;organizer:string;assets:Partial<Record<'venue'|'qr'|'reference'|'speaker'|'organizerLogo',UploadedAsset>>;styleId:string;outputs:OutputOptions;visualSeed:number;createdAt:string}
export type GenerationStatus='waiting'|'running'|'done';
export interface GenerationMetrics{gpu:string;rocm:string;resolution:string;duration:string;peakVram:string}
export interface GenerationCandidate{
  candidateId:string;
  variantKey:string;
  variantName:string;
  status:string;
  selected:boolean;
  attempt:number;
  seed?:number;
  error?:string;
  imageUrl?:string;
  visualAnalysis?:VisualAnalysis;
  spec?:{motif?:string;composition?:string;camera?:string;materials?:string[];palette?:string[];lighting?:string;visualAnalysis?:VisualAnalysis};
}
export interface NormalizedRegion{x:number;y:number;w:number;h:number}
export interface TextSafeZone extends NormalizedRegion{align?:'left'|'center'|'right';priority?:number}
export interface TypographyProfile{family?:string;weight?:number;fillColor?:string;strokeColor?:string;distress?:number}
export interface VisualAnalysis{palette?:string[];dominantColors?:string[];contrast?:'low'|'medium'|'high'|string;brightness?:number|string;texture?:string;style?:string;typographyProfile?:TypographyProfile;subjectBounds?:NormalizedRegion[];textSafeZones?:TextSafeZone[];logoSafeZone?:NormalizedRegion;hasGeneratedText?:boolean;ocrDetections?:Array<{text?:string;region?:NormalizedRegion}>;analysisStatus?:string;error?:string}
export interface GenerationTask{
  id:string;
  projectId:string;
  step:number;
  progress:number;
  status:'running'|'complete'|'failed';
  startedAt:number;
  metrics:GenerationMetrics;
  outputUrl?:string;
  error?:string;
  source?:'w7900'|'local';
  remoteStatus?:string;
  candidates?:GenerationCandidate[];
  elapsedSeconds?:number;
  etaSeconds?:number;
  selectedCandidateId?:string;
  composerTemplate?:string;
  palette?:string[];
}

export interface ReviewScores{requirementAlignment?:number;composition?:number;typography?:number;readability?:number;visualQuality?:number;brandConsistency?:number}
export interface ReviewFailure{code:string;description:string}
export interface ReviewIssue{code:string;severity:string;layer?:string;description:string;suggestion?:string}
export interface PosterReview{reviewId:string;posterId:string;candidateId?:string;round?:number;totalScore:number;scores?:ReviewScores;hardFailures?:ReviewFailure[];issues?:ReviewIssue[];decision:string;model?:string;promptTokens?:number;completionTokens?:number;latencyMs?:number;result?:{totalScore?:number;scores?:ReviewScores;hardFailures?:ReviewFailure[];issues?:ReviewIssue[];decision?:string};createdAt?:string}
export interface PosterEvidenceMetrics{reviewRounds?:number;promptTokens?:number;completionTokens?:number;totalTokens?:number;reviewLatencyMs?:number;wallClockSeconds?:number}
export interface PosterTimeline{posterId:string;reviews?:PosterReview[];metrics?:PosterEvidenceMetrics}
export interface ImageMetadata{width:number;height:number;format:string;sizeBytes:number;aspectRatio:string}
export interface RuntimeEvidence{status?:string;gpu?:{model?:string;vramTotalGB?:number;vramUsedGB?:number};comfyui?:{status?:string;workflowVersion?:string};vlm?:{status?:string;model?:string;sleeping?:boolean};runtime?:{goVersion?:string}}
