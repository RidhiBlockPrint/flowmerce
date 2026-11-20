'use client';
/**
 * Write it yourself (SEO & Blog → Advanced): the manual blog tools in the order a person uses them, for anyone who
 * wants to write a blog by hand instead of leaving it to the automatic pipeline. Each step opens the existing page that
 * does it (topic research and approval, drafting with Claude, images and checks in the editor, review, publishing).
 * Nothing here runs by itself; the counts come from GET /api/articles/counts and GET /api/topics.
 */
import Link from 'next/link';
import { qs, useApi } from '../lib/api';
import { useBrandParam } from '../lib/app';
import { fmtInt } from '../lib/format';
import { Card, PageHead } from '../components/ui';
import { Icon } from '../components/Icon';
import { WriteBlog } from '../components/claude';
import { CountUp } from '../components/motion';

const STEPS = [
    { n: 1, icon: 'topics', title: 'Find a topic', text: 'Ask Claude for topic ideas, or add your own with its primary keyword and search intent.',
        links: [['/topics', 'Topics & keywords'], ['/topics?tab=keywords', 'Keyword list']], count: (t) => t.proposed, countLabel: 'proposed' },
    { n: 2, icon: 'checkCircle', title: 'Approve the topic', text: 'Validate and approve the topics worth writing. Only an approved topic can get a draft.',
        links: [['/topics?status=proposed', 'Topics to decide']], count: (t) => t.approved, countLabel: 'approved, not drafted' },
    { n: 3, icon: 'sparkle', title: 'Draft it', text: 'Let Claude write the first draft from an approved topic (every field filled), or start a blank article and write it yourself.',
        links: [['/topics?status=approved', 'Draft an approved topic'], ['/articles', 'New article']], count: (_t, a) => a.draft, countLabel: 'drafts' },
    { n: 4, icon: 'image', title: 'Images, links and checks', text: 'In the article editor: pick the featured image, add product photos and links, and work through the SEO score and Claude’s notes.',
        links: [['/articles?status=draft', 'Open drafts']] },
    { n: 5, icon: 'eye', title: 'Review', text: 'Send it for review. A reviewer approves it or asks for changes.',
        links: [['/articles?status=in_review', 'Waiting for review']], count: (_t, a) => a.in_review, countLabel: 'in review' },
    { n: 6, icon: 'publish', title: 'Publish', text: 'Save it as a hidden Shopify draft, then request publishing. It goes live only when a reviewer authorizes it.',
        links: [['/publishing', 'Publishing'], ['/calendar', 'Content calendar']], count: (_t, a) => a.approved, countLabel: 'approved' },
];

export default function WriteYourself() {
    const brand = useBrandParam();
    const counts = useApi(`/articles/counts${qs({ brand })}`);
    const topics = useApi(`/topics${qs({ brand })}`);
    const t = { proposed: 0, approved: 0 };
    for (const x of topics.data ?? []) {
        if (x.status === 'proposed' || x.status === 'validated') t.proposed += 1;
        if (x.status === 'approved') t.approved += 1;
    }
    const a = Object.fromEntries((Array.isArray(counts.data) ? counts.data : []).map((c) => [c.status, c.n]));
    return (<>
      <PageHead title="Write it yourself" sub="The manual blog tools, step by step." actions={<Link className="btn ghost" href="/automation"><Icon name="automation"/>Run single stages</Link>}/>
      <Card className="mb-16">
        <div className="row" style={{ gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <Icon name="sparkle"/>
          <div style={{ flex: '1 1 260px', minWidth: 0 }}>
            <b>Or let Flowmerce do all of it once.</b>
            <div className="muted small">Research, topic, draft, images and checks in one go, saved as a hidden Shopify draft. Pick one brand at the top first.</div>
          </div>
          <WriteBlog brand={brand}/>
        </div>
      </Card>
      <div className="write-steps stagger">
        {STEPS.map((s) => {
            const n = s.count ? s.count(t, a) : undefined;
            return (<div key={s.n} className="card write-step">
              <span className="write-step-n">{s.n}</span>
              <div className="write-step-body">
                <div className="row" style={{ gap: 8 }}><Icon name={s.icon}/><b>{s.title}</b>
                  {n !== undefined && Number.isFinite(n) && (counts.data || topics.data) ? <span className="pill neutral"><CountUp value={fmtInt(n)}/> {s.countLabel}</span> : null}</div>
                <p className="small muted" style={{ margin: '6px 0 10px' }}>{s.text}</p>
                <div className="row-wrap" style={{ gap: 8 }}>
                  {s.links.map(([to, label]) => <Link key={to} className="btn secondary sm" href={to}>{label}<Icon name="arrowRight" size="sm"/></Link>)}
                </div>
              </div>
            </div>);
        })}
      </div>
    </>);
}
