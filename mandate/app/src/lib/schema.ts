import { z } from "zod";

const UnknownRecord = z.record(z.string(), z.unknown());

export const JournalEntrySchema = z.object({
  at: z.string(),
  action: z.string(),
  outcome: z.string(),
  rationale: z.string(),
  details: UnknownRecord.optional().default({}),
});

const MandateStateSchema = z.object({
  mandate: UnknownRecord,
  as_of: z.string().nullable().optional(),
  market_is_open: z.boolean().optional().default(false),
  usage: UnknownRecord.optional().default({}),
  headroom: UnknownRecord.optional().default({}),
  wake_triggers: z.array(z.unknown()).optional().default([]),
  active_predecisions: z.array(z.unknown()).optional().default([]),
});

const SessionStateSchema = z.object({
  as_of: z.string().nullable().optional(),
  account: UnknownRecord.optional().default({}),
  market: UnknownRecord.optional().default({}),
  positions: z.record(z.string(), UnknownRecord).optional().default({}),
  orders_today: z.number().optional().default(0),
  pending_orders: z.array(UnknownRecord).optional().default([]),
  journal: z
    .array(z.unknown())
    .optional()
    .default([])
    .transform((entries) =>
      entries
        .map((entry) => JournalEntrySchema.safeParse(entry))
        .filter((result) => result.success)
        .map((result) => result.data),
    ),
});

const AutonomySchema = z
  .object({
    trajectory: UnknownRecord.optional().default({}),
    runtime: UnknownRecord.optional().default({}),
    alerts: z.array(UnknownRecord).optional().default([]),
    market: UnknownRecord.optional().default({}),
    outcomes: UnknownRecord.optional().default({}),
  })
  .optional()
  .default({ trajectory: {}, runtime: {}, alerts: [], market: {}, outcomes: {} });

const ApprovalsSchema = z
  .object({
    count: z.number().optional().default(0),
    items: z.array(UnknownRecord).optional().default([]),
    error: z.string().optional(),
  })
  .optional()
  .default({ count: 0, items: [] });

export const SnapshotSchema = z.object({
  generated_at: z.string(),
  source: z.enum(["live", "degraded"]),
  paper_only: z.literal(true),
  agent_url: z.string(),
  services: z.array(
    z.object({ name: z.string(), url: z.string(), ok: z.boolean() }),
  ),
  errors: z.array(z.string()),
  mandate: MandateStateSchema,
  session: SessionStateSchema,
  autonomy: AutonomySchema,
  approvals: ApprovalsSchema,
});

export type Snapshot = z.infer<typeof SnapshotSchema>;
export type Journal = z.infer<typeof JournalEntrySchema>;
export type ServiceStatus = Snapshot["services"][number];
