import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
import { micromark } from 'micromark';
import { math, mathHtml } from 'micromark-extension-math';
import { lint } from 'markdownlint/promise';

// Resolve through the actual parent so a duplicate root KaTeX cannot mask an
// unpatched version in micromark-extension-math's dependency graph.
const parentRequire = createRequire(import.meta.resolve('micromark-extension-math'));
const katex = parentRequire('katex');

test('the math extension resolves the patched KaTeX release', () => {
  assert.equal(katex.version, '0.18.2');
});

for (const [label, source, className] of [
  ['inline', '$a^2 + b^2 = c^2$', 'math-inline'],
  ['block', '$$\n\\frac{1}{2}\n$$', 'math-display'],
]) {
  test(`the parent renders ${label} math with the patched API`, () => {
    const html = micromark(source, {
      extensions: [math()],
      htmlExtensions: [mathHtml()],
    });
    assert.ok(html.includes(className));
    assert.ok(html.includes('class="katex"'));
    assert.ok(html.includes('<math'));
  });
}

test('malformed math retains strict and tolerant error behavior', () => {
  assert.throws(() => katex.renderToString('\\frac{'), /ParseError|parse/i);
  const html = micromark('$\\frac{$', {
    extensions: [math()],
    htmlExtensions: [mathHtml({ throwOnError: false })],
  });
  assert.ok(html.includes('katex-error'));
});

test('untrusted HTML and URL commands remain inert', () => {
  const html = micromark('$\\href{javascript:alert(1)}{click}$', {
    extensions: [math()],
    htmlExtensions: [mathHtml({ trust: false, throwOnError: false })],
  });
  assert.doesNotMatch(html, /<a\b|<script\b|href\s*=/i);
  assert.throws(() => katex.renderToString('\\repeat', {
    macros: { '\\repeat': '\\repeat' }, maxExpand: 20,
  }), /expansion|infinite/i);
});

test('markdownlint still distinguishes math from reversed Markdown links', async () => {
  const results = await lint({
    strings: { math: '$ (text)[target] $\n\n$$\n(text)[target]\n$$\n', plain: '(text)[target]\n' },
    config: { default: false, MD011: true },
  });
  assert.equal(results.math.length, 0);
  assert.equal(results.plain.length, 1);
});
