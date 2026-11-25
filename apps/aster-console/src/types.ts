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
  falsificationCriteria: string[];
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
  evidence_ids: string[];
  risks: string[];
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
          mechanism: string;
          expectedDirection: string;
          falsificationCriteria: string[];
        }>;
      }>;
    };
    decision: {
      decisionAt: string;
      status: string;
      selectedGroups: string[];
      disabledGroups: string[];
      rationale: string;
      confidence: number | null;
      fallbackUsed: boolean;
      fallbackReason: string | null;
      promptVersion: string;
      dissent: string[];
      isHistorical: boolean;
    };
    ballots: Array<{
      role: string;
      summary: string;
      votes: Vote[];
      mechanismReviews: Array<Record<string, unknown>>;
      dissentConditions: string[];
    }>;
    mechanismReviewPending: boolean;
  };
  portfolio: {
    runs: Array<{
      id: string;
      label: string;
      metrics: Record<string, number>;
      curve: Array<{
        date: string;
        nav: number;
        drawdown: number;
        beta: number;
        profile: string;
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
