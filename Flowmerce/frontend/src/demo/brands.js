/**
 * Demo identity: the two brands, the users and the permission list. Shared by every demo module.
 * Brand ids match the real ones ('ridhi', 'cpc') so pages, colours and URLs behave as they will with real data;
 * all addresses and identifiers below are placeholders and none of them connects to anything.
 */
export const BRAND_IDS = ['ridhi', 'cpc'];

export const ALL_PERMISSIONS = [
  'view', 'article:write', 'article:submit', 'article:review', 'publish:request', 'publish:authorize', 'shopify:draft',
  'topic:write', 'topic:decide', 'workflow:run', 'analytics:sync', 'data:import', 'integrations:manage', 'audit:view', 'demo:manage',
];

export const USERS = [
  { id: 1, name: 'Demo Admin', email: 'admin@demo.flowmerce.invalid', role: 'admin', roleLabel: 'Admin' },
  { id: 2, name: 'Asha Verma', email: 'asha@demo.flowmerce.invalid', role: 'seo_manager', roleLabel: 'SEO Manager' },
  { id: 3, name: 'Rohan Mehta', email: 'rohan@demo.flowmerce.invalid', role: 'reviewer', roleLabel: 'Reviewer / Approver' },
];

export const brandsPublic = () => [
  {
    id: 'ridhi', name: 'Ridhi Block Print', short: 'Ridhi', storefrontUrl: 'https://ridhi.demo.invalid', blogUrl: 'https://ridhi.demo.invalid/blogs/news',
    shopDomain: 'ridhi-demo.myshopify.invalid', blogHandle: 'news', gscProperty: 'sc-domain:ridhi.demo.invalid', ga4PropertyId: '…0001',
    configured: { shopifyAdmin: true, gsc: false, ga4: false },
    settings: {
      voice: 'Warm, knowledgeable and craft-proud; explains hand block printing plainly; practical styling and care advice.',
      audience: 'Home decor shoppers in the US and UK looking for handmade cotton table linen, bedding and cushions.',
      avoid: 'Hype, invented statistics, competitor names, unverified eco claims.', defaultAuthor: 'Ridhi Block Print',
      researchFocus: 'Table linen, bedding and seasonal hosting with block-print textiles.', topicsPerRun: 5, draftsPerRun: 1,
    },
  },
  {
    id: 'cpc', name: 'Cotton Print Club', short: 'CPC', storefrontUrl: 'https://cpc.demo.invalid', blogUrl: 'https://cpc.demo.invalid/blogs/journal',
    shopDomain: 'cpc-demo.myshopify.invalid', blogHandle: 'journal', gscProperty: 'sc-domain:cpc.demo.invalid', ga4PropertyId: '…0002',
    configured: { shopifyAdmin: true, gsc: false, ga4: false },
    settings: {
      voice: 'Elegant, inviting and seasonal; focuses on tablescapes, gatherings and gifting with block-printed cotton.',
      audience: 'Hosts and home decor shoppers in the US who buy tablecloths, napkins, placemats and cushions.',
      avoid: 'Hype, invented statistics, competitor names, discount claims not given by the team.', defaultAuthor: 'Cotton Print Club',
      researchFocus: 'Holiday and seasonal tablescapes, formal table settings, bundles and gifting.', topicsPerRun: 5, draftsPerRun: 1,
    },
  },
];
