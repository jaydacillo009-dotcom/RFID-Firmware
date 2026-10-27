// Actual API preview/commit methods with an in-memory transaction adapter.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { createHash } from 'node:crypto';
const source = readFileSync(process.argv[2], 'utf8');
const methods = stripTypeScriptTypes(source.slice(source.indexOf('async function preview('), source.indexOf('async function getState(')));
class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
let students = new Map(), items = new Map(), previous, loanOwner = null, recorded = 0;
async function sql(parts, ...values) {
  const query = parts.join('?').replace(/\s+/g, ' ').trim();
  assert(!query.includes('select name from public.students'), 'student registration must not be queried');
  assert(!(query.includes('from public.items') && query.includes('active = true')), 'item status must not gate a scan');
  if (query.includes('pg_advisory_xact_lock')) return [];
  if (query.startsWith('select body_hash, response')) return previous ? [previous] : [];
  if (query.startsWith('select name from public.items')) return items.has(values[0]) ? [items.get(values[0])] : [];
  if (query.includes('from public.loans')) return loanOwner ? [{ id: 1, student_uid: loanOwner }] : [];
  if (query.startsWith('insert into public.students')) {
    if (!students.has(values[0])) students.set(values[0], { name: values[1], active: true });
    return [];
  }
  if (query.startsWith('insert into public.items')) {
    if (!items.has(values[0])) items.set(values[0], { name: values[1], active: true });
    return [];
  }
  if (query.startsWith('insert into public.loans') || query.startsWith('update public.loans')) { recorded++; return []; }
  if (query.startsWith('insert into public.requests')) {
    previous = { body_hash: values[2], response: JSON.parse(values[3]) }; return [];
  }
  throw new Error(`Unexpected SQL: ${query}`);
}
sql.begin = async fn => {
  const beforeStudents = new Map(students), beforeItems = new Map(items);
  try { return await fn(sql); } catch (error) { students = beforeStudents; items = beforeItems; throw error; }
};
const sha256 = async value => createHash('sha256').update(value).digest('hex');
const { preview, commit } = new Function('sql', 'ApiError', 'sha256', 'encoder', methods + '\nreturn { preview, commit };')(sql, ApiError, sha256, new TextEncoder());
const body = { mode: 'borrow', student_uid: 'FFFFFFFF', item_uid: 'AABBCCDD', request_id: 'ab'.repeat(16) };
assert.equal((await preview({ ...body, item_uid: null })).next, 'scan_item');
assert.equal((await preview(body)).next, 'confirm');
assert.equal(students.size + items.size, 0, 'previews must not write registrations');
const first = await commit('scanner-1', body);
assert.equal(first.student_name, 'FFFFFFFF');
assert.equal(first.item_name, 'AABBCCDD');
assert(students.has('FFFFFFFF') && items.has('AABBCCDD'), 'new scans must satisfy both loan foreign keys');
assert.equal(recorded, 1);
assert.equal((await commit('scanner-1', body)).ok, true);
assert.equal(recorded, 1, 'retry must not duplicate a loan');
previous = undefined;
students.set('FFFFFFFF', { name: 'Existing student', active: false });
items.set('AABBCCDD', { name: 'Existing item', active: false });
assert.equal((await commit('scanner-1', { ...body, request_id: 'cd'.repeat(16) })).item_name, 'Existing item');
assert.deepEqual(students.get('FFFFFFFF'), { name: 'Existing student', active: false });
assert.deepEqual(items.get('AABBCCDD'), { name: 'Existing item', active: false });
previous = undefined;
assert.equal((await commit('scanner-1', { ...body, student_uid: '01020304', item_uid: '11223344' })).ok, true);
assert(items.has('11223344') && students.has('01020304'));
previous = undefined; loanOwner = 'FFFFFFFF';
await assert.rejects(commit('scanner-1', { ...body, mode: 'return', student_uid: '12345678', item_uid: '55667788' }), e => e.code === 'wrong_borrower');
assert(!students.has('12345678') && !items.has('55667788'), 'failed transactions roll back newly created IDs');
assert.equal((await commit('scanner-1', { ...body, mode: 'return' })).mode, 'return');
previous = undefined;
await assert.rejects(commit('scanner-1', body), e => e.code === 'already_borrowed');
console.log('Backend checks passed: new/inactive student and item UIDs, rollback, tracking and duplicate-safe retries');
