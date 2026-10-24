// ReconAI SpacetimeDB module. Owner: C.
//
// Mirrors backend/store/sqlite.py: one table per kind, rows hold contract JSON blobs
// (strings) plus the indexed key columns the Store protocol queries by.
// Python talks to it over HTTP (backend/store/spacetime.py); the UI subscribes over WS.
//
// Publish:  spacetime publish reconai -s local --module-path spacetime/spacetimedb [--delete-data]
import { schema, table, t, SenderError } from 'spacetimedb/server';

const spacetimedb = schema({
  cases: table(
    { public: true },
    {
      id: t.string().primaryKey(),
      vendor_id: t.string().index('btree'),
      status: t.string(),
      body: t.string(),
    }
  ),
  steps: table(
    { public: true },
    {
      id: t.string().primaryKey(),
      case_id: t.string().index('btree'),
      run_id: t.string(),
      seq: t.u32(),
      ord: t.u64(), // global insertion order (first write); latest run = max ord
      status: t.string(),
      body: t.string(),
    }
  ),
  fingerprints: table(
    { public: true },
    {
      fp: t.string().primaryKey(),
      case_id: t.string(),
    }
  ),
  documents: table(
    { public: true },
    {
      key: t.string().primaryKey(), // case_id + '|' + doc_id
      sha256: t.string().index('btree'),
      case_id: t.string(),
      doc_id: t.string(),
      body: t.string(),
    }
  ),
  world: table(
    { public: true },
    {
      key: t.string().primaryKey(), // kind + '|' + key
      kind: t.string().index('btree'),
      idx: t.string(),
      body: t.string(),
    }
  ),
  vendors: table(
    { public: true },
    {
      id: t.string().primaryKey(),
      body: t.string(),
    }
  ),
  memory: table(
    { public: true },
    {
      id: t.string().primaryKey(),
      subject: t.string().index('btree'),
      body: t.string(),
    }
  ),
  scoreboards: table(
    { public: true },
    {
      run_id: t.string().primaryKey(),
      at: t.string(),
      body: t.string(),
    }
  ),
  counters: table(
    { public: false },
    {
      name: t.string().primaryKey(),
      value: t.u64(),
    }
  ),
});
export default spacetimedb;

const nextOrd = (ctx: any): bigint => {
  const row = ctx.db.counters.name.find('steps');
  const value = row ? row.value + 1n : 1n;
  if (row) ctx.db.counters.name.update({ name: 'steps', value });
  else ctx.db.counters.insert({ name: 'steps', value });
  return value;
};

// docs: JSON array of {sha256, doc_id, body}
export const save_case = spacetimedb.reducer(
  { id: t.string(), vendor_id: t.string(), status: t.string(), body: t.string(), docs: t.string() },
  (ctx, { id, vendor_id, status, body, docs }) => {
    const row = { id, vendor_id, status, body };
    if (ctx.db.cases.id.find(id)) ctx.db.cases.id.update(row);
    else ctx.db.cases.insert(row);
    let parsed: Array<{ sha256: string; doc_id: string; body: string }>;
    try {
      parsed = JSON.parse(docs);
    } catch {
      throw new SenderError('docs must be a JSON array');
    }
    for (const d of parsed) {
      const key = `${id}|${d.doc_id}`;
      const drow = { key, sha256: d.sha256, case_id: id, doc_id: d.doc_id, body: d.body };
      if (ctx.db.documents.key.find(key)) ctx.db.documents.key.update(drow);
      else ctx.db.documents.insert(drow);
    }
  }
);

// Upsert by step id (called on start and on finish). ord is fixed at first write.
export const append_step = spacetimedb.reducer(
  { id: t.string(), case_id: t.string(), run_id: t.string(), seq: t.u32(), status: t.string(), body: t.string() },
  (ctx, { id, case_id, run_id, seq, status, body }) => {
    const prev = ctx.db.steps.id.find(id);
    if (prev) ctx.db.steps.id.update({ ...prev, status, body });
    else ctx.db.steps.insert({ id, case_id, run_id, seq, ord: nextOrd(ctx), status, body });
  }
);

// Atomic insert-or-get: the first claimant owns the fingerprint. Read the owner back with SQL.
export const claim_fingerprint = spacetimedb.reducer(
  { fp: t.string(), case_id: t.string() },
  (ctx, { fp, case_id }) => {
    if (!ctx.db.fingerprints.fp.find(fp)) ctx.db.fingerprints.insert({ fp, case_id });
  }
);

// rows: JSON array of {kind, key, idx, body}
export const put_world = spacetimedb.reducer({ rows: t.string() }, (ctx, { rows }) => {
  for (const r of JSON.parse(rows) as Array<{ kind: string; key: string; idx: string; body: string }>) {
    const row = { key: `${r.kind}|${r.key}`, kind: r.kind, idx: r.idx, body: r.body };
    if (ctx.db.world.key.find(row.key)) ctx.db.world.key.update(row);
    else ctx.db.world.insert(row);
  }
});

export const put_vendor = spacetimedb.reducer({ id: t.string(), body: t.string() }, (ctx, row) => {
  if (ctx.db.vendors.id.find(row.id)) ctx.db.vendors.id.update(row);
  else ctx.db.vendors.insert(row);
});

export const put_memory = spacetimedb.reducer(
  { id: t.string(), subject: t.string(), body: t.string() },
  (ctx, row) => {
    if (ctx.db.memory.id.find(row.id)) ctx.db.memory.id.update(row);
    else ctx.db.memory.insert(row);
  }
);

export const delete_memory = spacetimedb.reducer({ id: t.string() }, (ctx, { id }) => {
  ctx.db.memory.id.delete(id);
});

export const put_scoreboard = spacetimedb.reducer(
  { run_id: t.string(), at: t.string(), body: t.string() },
  (ctx, row) => {
    if (ctx.db.scoreboards.run_id.find(row.run_id)) ctx.db.scoreboards.run_id.update(row);
    else ctx.db.scoreboards.insert(row);
  }
);

// Wipe run state (and seeded world/vendors/memory, which are re-seeded from data/).
export const reset = spacetimedb.reducer({ keep_scoreboards: t.bool() }, (ctx, { keep_scoreboards }) => {
  for (const r of [...ctx.db.cases.iter()]) ctx.db.cases.id.delete(r.id);
  for (const r of [...ctx.db.steps.iter()]) ctx.db.steps.id.delete(r.id);
  for (const r of [...ctx.db.fingerprints.iter()]) ctx.db.fingerprints.fp.delete(r.fp);
  for (const r of [...ctx.db.documents.iter()]) ctx.db.documents.key.delete(r.key);
  for (const r of [...ctx.db.world.iter()]) ctx.db.world.key.delete(r.key);
  for (const r of [...ctx.db.vendors.iter()]) ctx.db.vendors.id.delete(r.id);
  for (const r of [...ctx.db.memory.iter()]) ctx.db.memory.id.delete(r.id);
  if (!keep_scoreboards) for (const r of [...ctx.db.scoreboards.iter()]) ctx.db.scoreboards.run_id.delete(r.run_id);
});
