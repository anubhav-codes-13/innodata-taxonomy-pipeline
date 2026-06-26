import type {
  BeforeAfter,
  DocumentDetail,
  DocumentListItem,
  Domain,
  EnrichedChunk,
  KeywordStat,
} from "../lib/types";

// Two realistic, domain-appropriate enrichment results. The mock assigns one
// of these to each completed file (by domain), substituting the real filename.
// Matches the content shown in the Figma Explorer frame.

function kaDocument(docId: string, filename: string): DocumentDetail {
  return {
    doc_id: docId,
    filename,
    doc_type: "commentary",
    domain: "KA",
    container_title: "Journal of International Arbitration",
    publ_year: 2025,
    chunk_count: 4,
    case_metadata: {
      court: "Singapore Court of Appeal",
      case_name: "DJP and others v. DJO [2024] SGHC(I) 24",
      case_number: "Court of Appeal / Civil Appeal No 6 of 2024",
      decision_date: "20250408",
      parties: [
        { role: "Appellant", name: "DJP" },
        { role: "Respondent", name: "DJO" },
      ],
    },
    provenance: {
      summary: "Mixed: 50% Anchored, 50% Expanded",
      anchored_pct: 50,
      expanded_pct: 50,
    },
    taxonomy_tree: [
      {
        level: "L1",
        label: "International Arbitration",
        children: [
          {
            level: "L2",
            label: "Arbitrator Independence",
            source: "anchor",
            similarity: 0.81,
            children: [
              {
                level: "L3",
                label: "Arbitrator Issue Conflict",
                children: [
                  {
                    level: "L4",
                    kind: "cases",
                    values: ["DJP v. DJO", "Halliburton Company v. Chubb Bermuda"],
                  },
                  {
                    level: "L4",
                    kind: "statutes",
                    values: ["International Arbitration Act s.16"],
                  },
                  {
                    level: "L4",
                    kind: "keywords",
                    values: ["Arbitrator Bias", "Prejudgment", "Issue Conflict"],
                  },
                ],
              },
            ],
          },
          {
            level: "L2",
            label: "Arbitrator Bias Standards",
            source: "generator",
            similarity: 0.7,
            children: [
              {
                level: "L3",
                label: "General Arbitrator Bias Standards",
                children: [
                  {
                    level: "L4",
                    kind: "keywords",
                    values: ["Apparent Bias", "Repeat Appointments"],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
    entities: {
      case_names: ["DJP v. DJO", "Halliburton Company v. Chubb Bermuda"],
      statutes_and_regulations: ["International Arbitration Act s.16"],
      organizations: ["Singapore Court of Appeal"],
    },
    keywords: {
      all: ["Arbitrator Bias", "Issue Conflict", "Prejudgment", "Apparent Bias", "Repeat Appointments"],
      matched_from_dictionary: ["Arbitrator Bias", "Issue Conflict"],
      newly_extracted: ["Prejudgment", "Apparent Bias", "Repeat Appointments"],
    },
  };
}

function kclDocument(docId: string, filename: string): DocumentDetail {
  return {
    doc_id: docId,
    filename,
    doc_type: "commentary",
    domain: "KCL",
    container_title: "Common Market Law Review",
    publ_year: 2024,
    chunk_count: 6,
    case_metadata: null,
    provenance: {
      summary: "100% Anchored",
      anchored_pct: 100,
      expanded_pct: 0,
    },
    taxonomy_tree: [
      {
        level: "L1",
        label: "Competition Law",
        children: [
          {
            level: "L2",
            label: "Merger Control",
            source: "anchor",
            similarity: 0.83,
            children: [
              {
                level: "L3",
                label: "Transaction Notification Scope",
                children: [
                  {
                    level: "L4",
                    kind: "statutes",
                    values: ["Article 22 EUMR", "Council Regulation (EC) No. 139/2004"],
                  },
                  {
                    level: "L4",
                    kind: "keywords",
                    values: ["Turnover Threshold", "Below-Threshold Mergers"],
                  },
                ],
              },
              {
                level: "L3",
                label: "Call-In Power",
                children: [
                  {
                    level: "L4",
                    kind: "cases",
                    values: ["Illumina/GRAIL"],
                  },
                  {
                    level: "L4",
                    kind: "organizations",
                    values: ["European Commission"],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
    entities: {
      case_names: ["Illumina/GRAIL"],
      statutes_and_regulations: [
        "Article 22 EUMR",
        "Council Regulation (EC) No. 139/2004",
      ],
      organizations: ["European Commission", "Court of Justice of the EU"],
    },
    keywords: {
      all: ["Merger Control", "Turnover Threshold", "Below-Threshold Mergers", "Call-In Power"],
      matched_from_dictionary: ["Merger Control"],
      newly_extracted: ["Turnover Threshold", "Below-Threshold Mergers", "Call-In Power"],
    },
  };
}

export function buildDocument(docId: string, filename: string, domain: Domain): DocumentDetail {
  return domain === "KA" ? kaDocument(docId, filename) : kclDocument(docId, filename);
}

export function buildBeforeAfter(domain: Domain): BeforeAfter {
  if (domain === "KA") {
    return {
      before: {
        topics: [],
        keywords: ["Arbitrator Bias", "Issue Conflict"],
        cases: [],
        statutes: [],
        organizations: [],
      },
      uplift: { levels_before: 1, levels_after: 4 },
    };
  }
  return {
    before: {
      topics: ["Mergers"],
      keywords: [],
      cases: [],
      statutes: [],
      organizations: [],
    },
    uplift: { levels_before: 1, levels_after: 4 },
  };
}

export function topTopicFor(domain: Domain): string {
  return domain === "KA" ? "Arbitrator Independence" : "Merger Control";
}

// Canned source passages behind the taxonomy — consistent with buildDocument's
// tree so clicking a topic/entity surfaces matching passages in the demo.
export function buildEnrichedChunks(domain: Domain, filename: string): EnrichedChunk[] {
  const container = domain === "KA" ? "Journal of International Arbitration" : "Common Market Law Review";
  const crumb = (section: string, title: string) =>
    `[Container: ${container} │ Document: ${filename} │ Section: ${section} - ${title}]\n\n`;

  if (domain === "KA") {
    return [
      {
        chunk_id: "S0001_chunk_1",
        section_id: "S0001",
        fused_text:
          crumb("S0001", "Background") +
          "The Singapore Court of Appeal in DJP v. DJO addressed arbitrator bias arising from an issue conflict, drawing on Halliburton Company v. Chubb Bermuda. The court applied the International Arbitration Act s.16 standard and warned against prejudgment by the tribunal.",
        L1_Domain: "International Arbitration",
        L2_Topic: "Arbitrator Independence",
        L2_Source: "anchor",
        L2_Similarity: 0.81,
        L3_Sub_Topic: "Arbitrator Issue Conflict",
        L4_metadata: {
          entities: {
            case_names: ["DJP v. DJO", "Halliburton Company v. Chubb Bermuda"],
            statutes_and_regulations: ["International Arbitration Act s.16"],
            organizations: ["Singapore Court of Appeal"],
          },
          keywords: {
            existing_matched_keywords: ["Arbitrator Bias", "Issue Conflict"],
            new_extracted_keywords: ["Prejudgment"],
          },
        },
      },
      {
        chunk_id: "S0002_chunk_1",
        section_id: "S0002",
        fused_text:
          crumb("S0002", "Legal Standard") +
          "On the standard for apparent bias, the commentary notes that repeat appointments of the same arbitrator can, in aggregate, give rise to justifiable doubts as to impartiality.",
        L1_Domain: "International Arbitration",
        L2_Topic: "Arbitrator Bias Standards",
        L2_Source: "generator",
        L2_Similarity: 0.7,
        L3_Sub_Topic: "General Arbitrator Bias Standards",
        L4_metadata: {
          entities: { case_names: [], statutes_and_regulations: [], organizations: [] },
          keywords: { existing_matched_keywords: [], new_extracted_keywords: ["Apparent Bias", "Repeat Appointments"] },
        },
      },
    ];
  }

  return [
    {
      chunk_id: "a0001_chunk_1",
      section_id: "a0001",
      fused_text:
        crumb("a0001", "Notification Scope") +
        "The Commission reinterpreted Article 22 EUMR, read with Council Regulation (EC) No. 139/2004, to review concentrations below the turnover threshold — so-called below-threshold mergers — expanding the notification scope.",
      L1_Domain: "Competition Law",
      L2_Topic: "Merger Control",
      L2_Source: "anchor",
      L2_Similarity: 0.83,
      L3_Sub_Topic: "Transaction Notification Scope",
      L4_metadata: {
        entities: {
          case_names: [],
          statutes_and_regulations: ["Article 22 EUMR", "Council Regulation (EC) No. 139/2004"],
          organizations: [],
        },
        keywords: {
          existing_matched_keywords: ["Merger Control"],
          new_extracted_keywords: ["Turnover Threshold", "Below-Threshold Mergers"],
        },
      },
    },
    {
      chunk_id: "a0002_chunk_1",
      section_id: "a0002",
      fused_text:
        crumb("a0002", "Call-In Power") +
        "Following Illumina/GRAIL, the European Commission asserted a call-in power over transactions that fall under no national merger-control regime.",
      L1_Domain: "Competition Law",
      L2_Topic: "Merger Control",
      L2_Source: "anchor",
      L2_Similarity: 0.83,
      L3_Sub_Topic: "Call-In Power",
      L4_metadata: {
        entities: { case_names: ["Illumina/GRAIL"], statutes_and_regulations: [], organizations: ["European Commission"] },
        keywords: { existing_matched_keywords: [], new_extracted_keywords: [] },
      },
    },
  ];
}

// Canned cross-document keyword frequencies for the dashboard (mock mode).
const MOCK_KEYWORDS: { keyword: string; frequency: number; domain: Domain }[] = [
  { keyword: "Arbitrator Bias", frequency: 6, domain: "KA" },
  { keyword: "State Immunity", frequency: 5, domain: "KA" },
  { keyword: "Award Enforcement", frequency: 4, domain: "KA" },
  { keyword: "Issue Conflict", frequency: 4, domain: "KA" },
  { keyword: "Apparent Bias", frequency: 3, domain: "KA" },
  { keyword: "ICSID Procedure", frequency: 3, domain: "KA" },
  { keyword: "Repeat Appointments", frequency: 2, domain: "KA" },
  { keyword: "Prejudgment", frequency: 2, domain: "KA" },
  { keyword: "Public Policy", frequency: 2, domain: "KA" },
  { keyword: "Merger Control", frequency: 7, domain: "KCL" },
  { keyword: "Abuse of Dominance", frequency: 5, domain: "KCL" },
  { keyword: "State Aid", frequency: 4, domain: "KCL" },
  { keyword: "Market Definition", frequency: 3, domain: "KCL" },
  { keyword: "Turnover Threshold", frequency: 3, domain: "KCL" },
  { keyword: "Vertical Restraints", frequency: 2, domain: "KCL" },
  { keyword: "Gatekeeper Regulation", frequency: 2, domain: "KCL" },
  { keyword: "Below-Threshold Mergers", frequency: 2, domain: "KCL" },
];

export function buildKeywordStats(domain?: Domain, search?: string): KeywordStat[] {
  const rows = domain ? MOCK_KEYWORDS.filter((r) => r.domain === domain) : MOCK_KEYWORDS;
  const merged = new Map<string, number>();
  for (const r of rows) merged.set(r.keyword, (merged.get(r.keyword) ?? 0) + r.frequency);
  let out: KeywordStat[] = [...merged].map(([keyword, frequency]) => ({ keyword, frequency }));
  if (search) {
    const q = search.toLowerCase();
    out = out.filter((o) => o.keyword.toLowerCase().includes(q));
  }
  out.sort((a, b) => b.frequency - a.frequency || a.keyword.localeCompare(b.keyword));
  return out;
}

const MOCK_TOPICS: { keyword: string; frequency: number; domain: Domain; level: "L1" | "L2" | "L3" }[] = [
  // L1
  { keyword: "International Arbitration", frequency: 7, domain: "KA", level: "L1" },
  { keyword: "Competition Law", frequency: 5, domain: "KCL", level: "L1" },
  // L2
  { keyword: "Award Enforcement", frequency: 7, domain: "KA", level: "L2" },
  { keyword: "State Immunity", frequency: 6, domain: "KA", level: "L2" },
  { keyword: "Arbitrator Challenges", frequency: 5, domain: "KA", level: "L2" },
  { keyword: "Jurisdiction", frequency: 5, domain: "KA", level: "L2" },
  { keyword: "AI in Arbitration", frequency: 4, domain: "KA", level: "L2" },
  { keyword: "Public Policy", frequency: 4, domain: "KA", level: "L2" },
  { keyword: "Merger Control", frequency: 5, domain: "KCL", level: "L2" },
  { keyword: "Abuse of Dominance", frequency: 4, domain: "KCL", level: "L2" },
  { keyword: "Cartel Enforcement", frequency: 3, domain: "KCL", level: "L2" },
  { keyword: "Market Definition", frequency: 3, domain: "KCL", level: "L2" },
  // L3
  { keyword: "ICSID Waiver Requirements", frequency: 6, domain: "KA", level: "L3" },
  { keyword: "State Immunity Act", frequency: 5, domain: "KA", level: "L3" },
  { keyword: "Independence Standards", frequency: 4, domain: "KA", level: "L3" },
  { keyword: "AI Arbitration Guidelines", frequency: 4, domain: "KA", level: "L3" },
  { keyword: "Due Process in AI", frequency: 3, domain: "KA", level: "L3" },
  { keyword: "New York Convention", frequency: 3, domain: "KA", level: "L3" },
  { keyword: "Turnover Thresholds", frequency: 4, domain: "KCL", level: "L3" },
  { keyword: "Below-Threshold Mergers", frequency: 3, domain: "KCL", level: "L3" },
  { keyword: "Predatory Pricing", frequency: 2, domain: "KCL", level: "L3" },
];

export function buildTopicStats(level: "L1" | "L2" | "L3", domain?: Domain, search?: string): KeywordStat[] {
  const rows = MOCK_TOPICS.filter((r) => r.level === level && (!domain || r.domain === domain));
  let out: KeywordStat[] = rows.map(({ keyword, frequency }) => ({ keyword, frequency }));
  if (search) {
    const q = search.toLowerCase();
    out = out.filter((o) => o.keyword.toLowerCase().includes(q));
  }
  out.sort((a, b) => b.frequency - a.frequency || a.keyword.localeCompare(b.keyword));
  return out;
}

// Pre-seeded history so the History screen isn't empty on first load.
export const SEED_DOCUMENTS: DocumentListItem[] = [
  {
    document_id: "doc-seed-1",
    filename: "KLI-KCL-Roy-2024-Ch04.xml",
    domain: "KCL",
    doc_type: "essay",
    top_topic: "Vertical Restraints",
    levels: "L1-L4",
    processed_at: "2026-06-13T10:20:00Z",
    batch_id: "batch-seed-a",
  },
  {
    document_id: "doc-seed-2",
    filename: "KLI-KCL-610504.xml",
    domain: "KCL",
    doc_type: "commentary",
    top_topic: "State Aid",
    levels: "L1-L4",
    processed_at: "2026-06-13T10:20:00Z",
    batch_id: "batch-seed-a",
  },
  {
    document_id: "doc-seed-3",
    filename: "KLI-JOIA-420501.xml",
    domain: "KA",
    doc_type: "essay",
    top_topic: "Investment Arbitration",
    levels: "L1-L4",
    processed_at: "2026-06-11T14:02:00Z",
    batch_id: "batch-seed-b",
  },
];
