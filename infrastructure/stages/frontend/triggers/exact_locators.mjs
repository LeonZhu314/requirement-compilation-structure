// Strengthen literal locators only when the original requirement specifies that name.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, sep } from 'node:path';

const [root, relative, encoded] = process.argv.slice(2);
const path = resolve(root, relative);
if (!path.startsWith(resolve(root, 'frontend/tests/e2e/acceptance') + sep)) {
  throw new Error('Only the independent acceptance owner can normalize these locators');
}
const ts = createRequire(resolve(root, 'package.json'))('typescript');
const contracts = JSON.parse(encoded);
const roles = new Set(contracts.roles.map(([name, role]) => JSON.stringify([role, name])));
const labels = new Set(contracts.labels);
const source = readFileSync(path, 'utf8');
const tree = ts.createSourceFile(relative, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
const edits = [];
const literal = node => node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : undefined;
const propertyName = node => node && (ts.isIdentifier(node) || ts.isStringLiteral(node)) ? node.text : undefined;

function addExact(options, call) {
  if (!options) {
    edits.push({ at: call.arguments[0].end, text: ', { exact: true }' });
    return;
  }
  if (!ts.isObjectLiteralExpression(options) || options.properties.some(item =>
      ts.isSpreadAssignment(item) || propertyName(item.name) === 'exact')) return;
  const last = options.properties.at(-1);
  edits.push({ at: last ? last.end : options.getStart(tree) + 1,
    text: (last ? ', ' : '') + 'exact: true' });
}

function visit(node) {
  if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
    const method = node.expression.name.text;
    if (method === 'getByRole' && node.arguments[1] && ts.isObjectLiteralExpression(node.arguments[1])) {
      const name = node.arguments[1].properties.find(item =>
        ts.isPropertyAssignment(item) && propertyName(item.name) === 'name');
      const role = literal(node.arguments[0]);
      if (name && roles.has(JSON.stringify([role, literal(name.initializer)]))) addExact(node.arguments[1], node);
    } else if (method === 'getByLabel' && labels.has(literal(node.arguments[0]))) {
      addExact(node.arguments[1], node);
    }
  }
  ts.forEachChild(node, visit);
}
visit(tree);
let updated = source;
for (const edit of edits.sort((a, b) => b.at - a.at)) updated = updated.slice(0, edit.at) + edit.text + updated.slice(edit.at);
if (updated !== source) writeFileSync(path, updated, 'utf8');
process.stdout.write(JSON.stringify({ changed: updated !== source, edits: edits.length }));
