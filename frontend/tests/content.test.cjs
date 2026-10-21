const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToString } = require('react-dom/server');

test('the Markdown math pipeline renders with the patched KaTeX version', async () => {
  const [{ default: Markdown }, { default: math }, { default: katex }] = await Promise.all([
    import('react-markdown'), import('remark-math'), import('rehype-katex'),
  ]);
  const html = renderToString(React.createElement(Markdown,
    { remarkPlugins: [math], rehypePlugins: [katex] }, '$x_i + \\frac{1}{2}$'));
  assert.ok(html.includes('katex-mathml'));
  assert.ok(!html.includes('katex-error'));
});
