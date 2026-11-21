// Run with: node --test tests/cro-batch5.test.mjs   (from the frontend folder; no packages needed)
// CRO batch 5: the demo answer for new vs returning customers, in the same shape as modules/cro/customers.py.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);

test('customers: new vs returning add up, with the comparison', async () => {
    resetDemo();
    const c = await get('/cro/customers?brand=ridhi');
    const nr = c.new_vs_returning;
    assert.equal(nr.new.orders + nr.returning.orders, nr.orders);
    assert.ok(nr.returning_customer_rate > 0 && nr.previous && nr.previous.orders > 0);
    assert.equal(c.new_vs_returning_error, null);
});
