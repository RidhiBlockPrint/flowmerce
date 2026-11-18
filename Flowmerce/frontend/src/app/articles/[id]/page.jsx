import ArticleEditor from '../../../views/ArticleEditor';

export default function ArticlePage() {
  return <ArticleEditor />;
}

// Static export (GitHub Pages demo) needs every article address known at build time. Demo article ids are small
// numbers, so pre-build 1..500; the normal server build keeps rendering any id on request.
export function generateStaticParams() {
  if (process.env.FLOWMERCE_STATIC_EXPORT !== '1') return [];
  return Array.from({ length: 500 }, (_, i) => ({ id: String(i + 1) }));
}
