// "Blog on a day" in the demo (server: services/auto_blog.schedule_topic): a topic and a go-live day become a planned blog.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const inDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

test('a topic put on a day is planned, shown on the overview, and the day cannot be taken twice', async () => {
  resetDemo();
  const day = inDays(40);
  const slot = await demoRequest('POST', '/blog/slots', { brand: 'cpc', publish_on: day, title: 'Napkin rings for a long table' });
  assert.equal(slot.status, 'planned');
  assert.equal(slot.scheduled_topic, true);
  assert.equal(slot.topic_title, 'Napkin rings for a long table');
  const ov = await demoRequest('GET', '/blog/overview?brand=cpc');
  assert.ok(ov.slots.some((s) => s.id === slot.id && s.topic_id));
  await assert.rejects(demoRequest('POST', '/blog/slots', { brand: 'cpc', publish_on: day, title: 'Another topic for that day' }), (e) => e.code === 'day_taken');
  await assert.rejects(demoRequest('POST', '/blog/slots', { brand: 'cpc', publish_on: inDays(0), title: 'Too soon for a blog' }), (e) => e.status === 400);
  await demoRequest('POST', `/blog/slots/${slot.id}/cancel`);
  const again = await demoRequest('POST', '/blog/slots', { brand: 'cpc', publish_on: day, title: 'Another topic for that day' });
  assert.equal(again.id, slot.id);
});

test('the calendar answers for any month and year, with the events and blogs of that month', async () => {
  resetDemo();
  const y = new Date().getFullYear() + 2;
  const slot = await demoRequest('POST', '/blog/slots', { brand: 'ridhi', publish_on: `${y}-03-10`, title: 'Spring table linens' });
  const cal = await demoRequest('GET', `/calendar?brand=ridhi&from=${y}-02-23&to=${y}-04-05`);
  assert.ok(cal.events.some((e) => e.name === 'Spring begins' && e.date === `${y}-03-20`));
  assert.ok(cal.slots.some((s) => s.id === slot.id && s.topic_id));
  assert.equal(typeof cal.budget.todayUsd, 'number');
});
