export type ViewId = "overview" | "factors" | "council" | "filings" | "portfolio";

export interface FactorMetrics {
  rankIc: number | null;
  rankIcIr: number | null;
  coverage: number | null;
  turnover: number | null;
  correlation: number | null;
  observations: number | null;
}

export interface Factor {
  id: string;
  name: string;
  group: string;
  family: string;
  origin: string;
  status: string;
  researchEligible: boolean;
  demoEligible: boolean;
  pitCompliant: boolean;
  expression: string;
  description: string;
  hypothesis: string;
  mechanism: string;
  expectedDirection: string;
  descriptionZh?: string;
  hypothesisZh?: string;
  mechanismZh?: string;
  expectedDirectionZh?: string;
  falsificationCriteria: string[];
  falsificationCriteriaZh?: string[];
  mechanismSource: string;
  tags: string[];
  version: string;
  statusReason: string;
  metrics: FactorMetrics;
  yearlyRankIc: Record<string, number>;
  artifact: {
    rows: number;
    instruments: number;
    firstDate: string | null;
    lastDate: string | null;
    digest: string;
  };
}

export interface Vote {
  group_id: string;
  action: "enable" | "disable" | "abstain";
  confidence: number;
  rationale: string;
  rationale_zh?: string;
  evidence_ids: string[];
  risks: string[];
  risks_zh?: string[];
}

export interface Snapshot {
  meta: {
    schema: string;
    generatedAt: string;
    asOf: string;
    catalogDigest: string;
    mode: string;
    showcaseDisclosure: string;
  };
  pipeline: Array<{
    id: string;
    label: string;
    detail: string;
    state: "complete" | "running" | "attention" | "pending";
    view: ViewId;
  }>;
  jobs: Array<Record<string, unknown> & { name: string }>;
  factors: Factor[];
  factorCouncil: {
    packet: {
      version: string;
      decisionAt: string;
      inputCutoff: string;
      digest: string;
      groups: Array<{
        id: string;
        factorIds: string[];
        rankIc: number;
        rankIcIr: number;
        turnover: number;
        correlation: number;
        mechanisms: Array<{
          factorId: string;
          hypothesis: string;
          hypothesisZh?: string;
          mechanism: string;
          mechanismZh?: string;
          expectedDirection: string;
          expectedDirectionZh?: string;
          falsificationCriteria: string[];
  falsificationCriteriaZh?: string[];
        }>;
      }>;
    };
    decision: {
      decisionAt: string;
      status: string;
      selectedGroups: string[];
      disabledGroups: string[];
      rationale: string;
      rationaleZh?: string | null;
      confidence: number | null;
      fallbackUsed: boolean;
      fallbackReason: string | null;
      promptVersion: string;
      dissent: string[];
      isHistorical: boolean;
      mode: string;
      usesHindsight: boolean;
      disclosure: string | null;
    };
    ballots: Array<{
      role: string;
      summary: string;
      summaryZh?: string;
      votes: Vote[];
      mechanismReviews: Array<Record<string, unknown>>;
      dissentConditions: string[];
      dissentConditionsZh?: string[];
    }>;
    mechanismReviewPending: boolean;
  };
  portfolio: {
    runs: Array<{
      id: string;
      label: string;
      metrics: Record<string, number>;
      report?: {
        decisionAt?: string;
        effectiveTo?: string;
        profile?: string;
        targetBeta?: number;
        memo?: string;
        memoEn?: string;
        confidence?: number;
      } | null;
      council: {
        selectedProfile: string | null;
        overweights: string[];
        underweights: string[];
        activeTilt: number;
        effectiveStart: string | null;
        effectiveEnd: string | null;
        usesHindsight: boolean;
        industryOverrideSignals: number;
      };
      curve: Array<{
        date: string;
        nav: number;
        drawdown: number;
        beta: number;
        profile: string;
        benchmarkNav?: number | null;
      }>;
    }>;
  };
  filings: Record<string, unknown> & {
    name: string;
    state?: string;
    score_completed?: number;
    score_total?: number;
    parse_completed?: number;
    documents_total?: number;
    factor_rows?: number;
    parse_failures?: number;
    score_failures?: number;
    needs_ocr?: number;
    updated_at?: string;
    token_usage?: { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number };
    year_start?: number;
    year_end?: number;
    years?: Array<{
      name: string;
      year: number;
      state?: string;
      score_completed?: number;
      score_total?: number;
      documents_total?: number;
      factor_rows?: number;
      needs_ocr?: number;
      updated_at?: string;
    }>;
  };
}

export interface ReplayRound {
  round_id: string;
  previous_round_id: string | null;
  origin: "saved_council_decision" | "quarterly_automatic_proposal" | "human_reconsideration";
  created_at: string;
  human_instruction: string | null;
  selected_groups: string[];
  disabled_groups: string[];
  rationale: string;
  evidence_ids: string[];
  dissent: string[];
  confidence: number;
  valid: boolean;
  validation_errors: string[];
  model: string;
  prompt_hash: string;
  token_usage: { input: number | null; output: number | null } | null;
  web_evidence_digest?: string | null;
  web_evidence_ids?: string[];
}

export interface ReplayPortfolioRound {
  round_id: string;
  factor_round_id: string;
  origin: string;
  created_at: string;
  selected_profile_id: "defensive" | "balanced" | "opportunistic";
  stock_target: number;
  target_beta: number;
  beta_tolerance: number;
  industry_overweights: string[];
  industry_underweights: string[];
  industry_active_tilt: number;
  rationale: string;
  evidence_ids: string[];
  dissent: string[];
  confidence: number;
  fallback_used: boolean;
  fallback_reason: string | null;
  valid: boolean;
  validation_errors: string[];
  model: string;
  prompt_hash: string;
  prompt_version?: string;
  token_usage: { input: number | null; output: number | null } | null;
  packet_digest: string | null;
  web_evidence_digest?: string | null;
}

export interface ReplayNode {
  node_id: string;
  decision_at: string;
  input_cutoff: string;
  evidence_as_of: string;
  evidence_status: "current" | "carry_forward";
  frequency: "quarterly";
  segment_start: string;
  segment_end: string;
  mode: string;
  uses_hindsight: boolean;
  disclosure: string | null;
  packet_digest: string;
  candidate_groups: string[];
  constraints: Record<string, unknown>;
  status: string;
  accepted_round_id: string | null;
  accepted_at?: string;
  web_evidence?: {
    provider: string;
    captured_at: string;
    evidence_digest: string;
    accepted: Array<{
      evidence_id: string;
      title: string;
      url: string;
      site_name: string | null;
      published_at: string | null;
      snippet: string;
      pit_eligible: boolean;
    }>;
    rejected: Array<Record<string, unknown>>;
    errors: string[];
    disclosure: string | null;
  };
  rounds: ReplayRound[];
  portfolio_rounds: ReplayPortfolioRound[];
  run: {
    state: "idle" | "computing" | "ready" | "failed";
    error: string | null;
    metrics: Record<string, number>;
    curve: Array<{ date: string; nav: number; drawdown: number; beta: number; profile: string }>;
    completed_at?: string;
  };
}

export interface ReplaySession {
  schema: string;
  session_id: string;
  created_at: string;
  updated_at: string;
  version: string;
  max_reconsideration_rounds: number;
  decision_frequency: "quarterly";
  automation_mode: "interactive" | "automatic";
  automation_state: "manual" | "deciding" | "backtesting" | "ready" | "failed";
  current_node_index: number;
  playback: { state: "playing" | "paused"; node_id: string | null; changed_at?: string };
  nodes: ReplayNode[];
}
