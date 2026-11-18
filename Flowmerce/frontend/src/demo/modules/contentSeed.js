/**
 * Synthetic sample content for the demo (articles, topics, keywords, products). Everything here is invented
 * placeholder copy about home textiles; it is not real business data and nothing here is published anywhere.
 */

const p = (t) => `<p>${t}</p>`;
const h2 = (t) => `<h2>${t}</h2>`;
const ul = (items) => `<ul>${items.map((i) => `<li>${i}</li>`).join('')}</ul>`;
const a = (href, t) => `<a href="${href}">${t}</a>`;
const join = (...parts) => parts.join('\n');

/* ---------------- Long, fully written bodies ---------------- */

const CARE_BODY = join(
  p(`A hand block printed cotton tablecloth is made to be used: Sunday lunches, birthday dinners, a quiet cup of tea at the kitchen table. With a little routine care, a block print tablecloth care plan can be simple, and the cloth will soften and settle into your home over the years. This guide walks through washing, drying, stain first aid and storage in plain steps.`),
  h2('Before the first wash'),
  p(`New cotton often holds a little loose dye and a light finish from the printing and finishing stages. Block printed cloths are made with traditional dyes, so a small amount of colour can release in the first wash. That is normal and a sign of a craft process rather than a factory shortcut.`),
  p(`Wash a new cloth on its own the first time, in cool water, with a mild liquid detergent. Keep it away from white or pale items. If the rinse water shows a tint, run one more cold rinse until it clears. Avoid soaking the cloth for long periods; a short rinse is usually enough.`),
  h2('Everyday washing'),
  p(`For regular washing, a gentle machine cycle at 30 degrees works well for most cotton tablecloths. Use a mild detergent without optical brighteners or bleach, because these can dull printed colours over time. Load the machine loosely so the cloth can move; a tightly packed drum creases the fabric and rubs the printed surface.`),
  ul([`Turn the cloth inside out before washing to protect the print.`, `Choose a short, gentle cycle and a low spin speed.`, `Wash dark and light prints separately for the first few washes.`, `Skip fabric softener: it coats the fibres and can make the cloth feel flat.`]),
  p(`If your cloth is very large, such as a long banquet size, a bathtub wash by hand is kind to both the fabric and your machine. Press out the water by rolling the cloth in a clean towel instead of wringing it.`),
  h2('Drying and ironing'),
  p(`Line drying in the shade is the gentlest option. Direct midday sun can fade any natural-dyed fabric, so hang the cloth in a bright but shaded spot. If you use a tumble dryer, choose a low heat and take the cloth out while it is still slightly damp. Cotton shrinks a little with high heat, and a damp cloth is easier to smooth.`),
  p(`Iron on the reverse side while the cloth is slightly damp, using a medium cotton setting. Pressing on the back keeps the printed face looking even. A light touch of steam helps relax any creases left from folding.`),
  h2('Stain first aid for a block print tablecloth'),
  p(`Accidents happen at the best tables. Act soon, and blot rather than rub, because rubbing pushes the stain deeper and can disturb the print.`),
  ul([`Wine or juice: blot, then rinse the back of the stain with cool water and wash as usual.`, `Oil or butter: dust with a little cornflour, wait ten minutes, brush away, then wash with a mild detergent.`, `Candle wax: let it set, lift off the surface gently, then place the area between sheets of paper and press with a warm iron.`, `Tea or coffee: rinse with cool water quickly and wash the same day.`]),
  p(`Avoid chlorine bleach and strong stain removers on printed cloth. If a mark remains after washing, repeat the cool rinse and wash again before drying, because heat can set a stain.`),
  h2('Storing your cloth'),
  p(`Fold the cloth loosely, or roll it around a tube, to avoid sharp creases in the same place every time. Store it in a cool, dry cupboard away from direct light. A breathable cotton bag is better than plastic, which can trap moisture. If you rotate cloths with the seasons, refold them along different lines each time.`),
  p(`If you are still choosing a cloth, browse our ${a('/collections/tablecloths', 'block print tablecloths')} and matching ${a('/collections/napkins', 'napkins')}. Both are made to be washed and used often.`),
  h2('A simple care routine to remember'),
  p(`Wash cool, dry in the shade, iron on the back, store loosely. That is all a hand block printed cloth asks of you. Over time the cotton softens, the colours mellow and the cloth becomes part of your table. Looked after well, it will keep its character through many gatherings.`),
);

const SIZE_BODY = join(
  p(`Choosing the right tablecloth size is the difference between a table that looks finished and one that looks like an afterthought. The goal is a drop, the length the cloth hangs below the tabletop, that feels deliberate. This guide explains how to measure your table, what drop to aim for and which tablecloth size suits round, square and rectangular tables.`),
  h2('Start by measuring your table'),
  p(`Measure the length and width of the tabletop, or the diameter if it is round. Do not measure the legs or the frame. If your table has leaves that extend it, measure both the closed and the extended size, and decide which you use most often.`),
  p(`Then decide how far you want the cloth to hang. A short drop is relaxed and everyday. A longer drop looks more formal and is better for gatherings. There is no wrong answer, only a choice about the mood of the table.`),
  h2('How much drop should a tablecloth have?'),
  ul([`Casual: a drop of about 15 to 20 cm (6 to 8 inches) keeps the cloth clear of laps and chair arms.`, `Everyday standard: around 25 to 30 cm (10 to 12 inches) is the most popular choice and suits most dining rooms.`, `Formal: 38 to 45 cm (15 to 18 inches) gives a graceful, floor-grazing look for special dinners, but only if the chairs have enough room.`]),
  p(`To calculate the cloth size, add twice your chosen drop to the tabletop measurement. For example, a table that is 150 by 90 cm with a 25 cm drop needs a cloth of about 200 by 140 cm.`),
  h2('Tablecloth size by table shape'),
  p(`Rectangular tables are the simplest: add the drop on every side. Keep the cloth long enough that the overhang at the ends matches the overhang along the sides, so the proportions look balanced. If you sit six people at a table that seats eight, a slightly longer cloth makes a smaller table feel generous.`),
  p(`Round tables need a cloth at least as wide as the diameter plus twice the drop. A square cloth on a round table can look charming when you turn it so the corners fall between the chairs, but a round cloth gives the cleanest line. For a small bistro table, a short drop keeps the cloth neat.`),
  p(`Square tables are best matched with a square cloth. Add your drop to every side, and consider a smaller square layered diagonally on top for a relaxed, layered style.`),
  h2('Seating and practical details'),
  p(`Think about how the table is actually used. Chairs with arms catch long cloths, and a very long drop can be awkward for people sitting close together. If you often pull the table out for guests, choose a cloth that still looks right at the extended size, or keep a second cloth for the long version.`),
  p(`Cotton can shrink slightly after washing, so if you are between two sizes, choose the larger. Our ${a('/collections/tablecloths', 'tablecloths')} are offered in several sizes, and you can match them with ${a('/collections/table-runners', 'table runners')} to extend or lighten the look.`),
  h2('A quick checklist'),
  ul([`Measure the tabletop, not the frame.`, `Pick a drop that suits the occasion.`, `Add twice the drop to the length and width, or to the diameter.`, `Round up if you are unsure, especially for cotton.`]),
  p(`With these steps, finding the right tablecloth size becomes a simple calculation rather than a guess. A well-sized cloth makes even a simple meal feel considered, and it frames the plates, glasses and flowers you place on top.`),
);

const HOLIDAY_BODY = join(
  p(`A holiday table does not need to be elaborate to feel generous. A block printed cotton cloth, a few thoughtful layers and warm lighting can turn an ordinary dining table into the place everyone wants to linger. Here is a calm, step by step approach to a holiday table setting that you can adapt to your own home and guest list.`),
  h2('Begin with the cloth as your canvas'),
  p(`Choose the tablecloth first, because everything else answers to it. A boldly printed cloth sets the tone and asks for quieter plates and glassware. A softer, small-scale print gives you freedom to bring in colour through napkins and candles. Cotton has a lovely matte warmth that works with both traditional and modern dishes.`),
  p(`Lay the cloth the day before if you can and smooth it with your hands. Folds from storage usually relax overnight, which saves last-minute ironing. If you need a refresher on sizing, our ${a('/collections/tablecloths', 'tablecloth collection')} lists dimensions for every table.`),
  h2('Layer with napkins, runners and placemats'),
  p(`Layers give a table depth. A runner down the centre breaks up a long surface and gives you a base for candles and greenery. Placemats frame each setting. Napkins add the final accent, and they are the easiest place to introduce a second colour.`),
  ul([`Keep to two or three colours drawn from the print.`, `Mix scale: pair a large pattern with a small one.`, `Fold napkins simply, or tie them with a sprig of greenery.`, `Let one element stay plain so the eye has somewhere to rest.`]),
  p(`Our ${a('/collections/napkins', 'cotton napkins')} and ${a('/collections/placemats', 'placemats')} are designed to be mixed this way, so you can build a set over time instead of buying everything at once.`),
  h2('Light, flowers and small details'),
  p(`Candles do more for a holiday table than any ornament. Use a mix of heights, and keep flames below eye level so guests can see one another. If you use flowers, choose low arrangements or single stems in small bottles, and leave room for serving dishes.`),
  p(`A handwritten place card, a small seasonal gift at each setting or a bowl of fruit and nuts are all gestures that feel personal without adding cost. Cotton Print Club pieces are chosen to sit comfortably alongside the things you already own.`),
  h2('Plan the practical side'),
  p(`A beautiful table still needs to work. Leave room for elbows and for passing dishes. Keep serving spoons and water jugs within reach, and set up a side table for extra plates. If young guests are coming, a washable cloth gives you peace of mind, and cotton is happy in the machine.`),
  h2('A simple timeline for the week'),
  ul([`Three days before: check the cloth and napkins for creases, and wash anything that needs freshening.`, `Two days before: choose and place the dishes, glasses and serving pieces.`, `The day before: lay the cloth, set the table and add the centrepiece without candles.`, `On the day: light the candles and add flowers or greenery just before guests arrive.`]),
  p(`A holiday table is ultimately about the people sitting around it. Set it with care, keep it simple enough to enjoy, and let the cotton, the candlelight and the conversation do the rest.`),
);

/* ---------------- Short bodies ---------------- */

const short = (intro, sections, closing) => join(p(intro), ...sections.flatMap(([t, body]) => [h2(t), p(body)]), p(closing));

/* ---------------- Articles ----------------
 * status flow fields: n = review/publish history; see content.js `buildArticles`.
 * `img` indexes /demo/tile-N.svg. Times are hours before "now" (negative = future).
 */
export const ARTICLE_SPECS = [
  // ------------------------------- Ridhi Block Print -------------------------------
  { key: 'r-care', brand: 'ridhi', status: 'published', version: 4, author: 2, createdD: 70, publishedD: 52, img: 1, tags: 'care, tablecloth, cotton',
    title: 'How to Care for a Block Print Cotton Tablecloth', handle: 'how-to-care-for-block-print-tablecloth', kw: 'block print tablecloth care',
    metaTitle: 'Block Print Tablecloth Care: Wash, Dry and Store', meta: 'Learn how to wash, dry, iron and store a block print cotton tablecloth so the colours stay soft and the cloth lasts for years.',
    summary: 'Simple washing, drying, stain first aid and storage steps for a hand block printed cotton tablecloth.', body: CARE_BODY, traffic: 1.5, trend: 0.004 },
  { key: 'r-size', brand: 'ridhi', status: 'published', version: 3, author: 2, createdD: 48, publishedD: 33, img: 2, tags: 'tablecloth, sizing, guide',
    title: 'Choosing the Right Tablecloth Size for Your Dining Table', handle: 'choosing-the-right-tablecloth-size', kw: 'tablecloth size guide',
    metaTitle: 'Tablecloth Size Guide: How to Measure Your Table', meta: 'Measure your table, choose the right drop and match the cloth to round, square or rectangular tables with this clear tablecloth size guide.',
    summary: 'How to measure your table and pick a drop that suits round, square and rectangular tables.', body: SIZE_BODY, traffic: 1.8, trend: 0.01 },
  { key: 'r-napkins', brand: 'ridhi', status: 'published', version: 2, author: 2, createdD: 40, publishedD: 24, img: 3, tags: 'napkins, hosting, table setting',
    title: 'Block Print Napkins: A Simple Guide to a Relaxed Table', handle: 'block-print-napkins-relaxed-table', kw: 'block print napkins',
    metaTitle: 'Block Print Napkins: Style a Relaxed Table', meta: 'Cotton block print napkins add colour and warmth to everyday meals. See easy ways to fold, mix and style them for a relaxed table.',
    summary: 'Easy ways to fold, mix and style cotton napkins for everyday meals and weekend lunches.',
    body: short('Napkins are the quickest way to change the mood of a table. A set of block print cotton napkins brings pattern and colour without any fuss.', [
      ['Pick a palette', `Choose two shades from your tablecloth or plates and let the napkins repeat them. Mixed prints from the same colour family look collected rather than matched.`],
      ['Three easy folds', `A simple rectangle on the plate, a loose roll tucked under the fork, or a casual knot at the corner all work. Cotton holds a soft crease, so no starching is needed.`],
      ['Keep them in rotation', `Cloth napkins are happiest when they are used daily. Wash on a gentle cycle, iron on the reverse and keep a small stack near the table.`],
    ], `Browse our ${a('/collections/napkins', 'napkins')} and ${a('/collections/tablecloths', 'tablecloths')} to build a set that suits your table.`),
    traffic: 1.0, trend: 0.01 },
  { key: 'r-craft', brand: 'ridhi', status: 'published', version: 2, author: 2, createdD: 120, publishedD: 100, img: 4, tags: 'craft, hand block printing',
    title: 'Hand Block Printing Explained: From Carved Block to Finished Cloth', handle: 'hand-block-printing-explained', kw: 'hand block printing',
    metaTitle: 'Hand Block Printing Explained Step by Step', meta: 'A plain guide to hand block printing: how blocks are carved, how colour is applied and why every printed cloth carries small, human variations.',
    summary: 'How a carved wooden block becomes a printed cloth, and why no two pieces are exactly alike.',
    body: short('Hand block printing is a slow, careful craft. Understanding how it works helps you appreciate the small variations that make each cloth individual.', [
      ['Carving the block', `A pattern is drawn, then carved into a block of seasoned wood. Fine details are cut into the surface so they hold colour and press cleanly onto cloth.`],
      ['Printing the cloth', `The cloth is stretched on a padded table. The printer presses the block into colour, places it by eye along a guide and strikes it firmly with the hand. The motion is repeated across the length of the fabric.`],
      ['Why variations are normal', `Because the block is placed by hand, tiny shifts in alignment and ink density are part of the character. They are a sign that a person made the cloth.`],
    ], `You can see the result in our ${a('/collections/tablecloths', 'block print tablecloths')}.`),
    traffic: 0.9, trend: -0.025 },
  { key: 'r-cushion', brand: 'ridhi', status: 'approved', version: 3, author: 2, createdD: 12, img: 5, tags: 'cushions, pattern mixing',
    title: 'Block Print Cushion Covers: Mixing Patterns Without the Clutter', handle: 'block-print-cushion-covers-mixing-patterns', kw: 'block print cushion covers',
    metaTitle: 'Block Print Cushion Covers: Mix Patterns Well', meta: 'Mix block print cushion covers with confidence. Learn simple rules for scale, colour and layout so your sofa looks collected, not cluttered.',
    summary: 'Simple rules for combining printed cushion covers on a sofa or bed.',
    body: short('Pattern mixing feels risky until you know a few simple rules. Block print cushion covers are well suited to it because the motifs are naturally hand-drawn and forgiving.', [
      ['Vary the scale', `Combine one large motif, one medium print and one small repeat. Different scales give the eye variety while the shared colours keep it calm.`],
      ['Anchor with a solid', `A plain cushion in a colour from the prints gives the arrangement a resting point. Linen or cotton in a natural shade works with almost every print.`],
      ['Odd numbers and layers', `Three or five cushions look relaxed and balanced. Place the largest at the back and let the smaller ones overlap in front.`],
    ], `Explore ${a('/collections/cushion-covers', 'cushion covers')} to start your own mix.`), traffic: 0 },
  { key: 'r-runner', brand: 'ridhi', status: 'publish_requested', version: 2, author: 2, createdD: 9, img: 6, tags: 'table runner, hosting',
    title: 'Block Print Table Runners for Everyday Meals and Hosting', handle: 'block-print-table-runners-everyday-hosting', kw: 'block print table runner',
    metaTitle: 'Block Print Table Runners for Every Day', meta: 'A block print table runner dresses a table in minutes. Find out how to choose a length, layer it with placemats and use it for everyday meals.',
    summary: 'How to choose and layer a table runner for everyday meals and hosting.',
    body: short('A table runner is the smallest change that makes the biggest difference. It protects the wood, adds colour and gives you a clear spot for the centrepiece.', [
      ['Choosing a length', `Let the runner hang 20 to 30 cm over each end of the table. For a long table, two runners laid end to end can look intentional.`],
      ['Layering', `Place a runner over a plain cloth, or run it bare down a wooden table with placemats on either side.`],
      ['Everyday use', `Cotton runners are simple to wash and refresh, so keep one on the table between meals.`],
    ], `See the ${a('/collections/table-runners', 'table runner collection')} and pair with ${a('/collections/placemats', 'placemats')}.`),
    req: { id: 'r-runner-req', mode: 'publish_now', note: 'Ready for the weekend newsletter.', requestedBy: 2, hoursAgo: 20, status: 'pending' } },
  { key: 'r-autumn', brand: 'ridhi', status: 'publish_requested', version: 2, author: 2, createdD: 8, img: 2, tags: 'autumn, hosting, table setting',
    title: 'Autumn Table Setting Ideas with Handmade Cotton Linen', handle: 'autumn-table-setting-ideas-cotton-linen', kw: 'autumn table setting ideas',
    metaTitle: 'Autumn Table Setting Ideas with Cotton Linen', meta: 'Warm earth tones, soft light and hand block printed cotton: simple autumn table setting ideas for family dinners and relaxed weekend hosting.',
    summary: 'Warm, simple autumn table setting ideas using block printed cotton linen.',
    body: short('Autumn invites slower meals and warmer tables. A few well-chosen textiles are enough to set the scene.', [
      ['Earth tones', `Rust, ochre and deep green look right at this time of year. Choose one as the main colour and let the others appear in napkins and candles.`],
      ['Texture and light', `Cotton has a soft, matte surface that pairs well with wood, ceramics and candlelight. Add a few small bowls of seasonal fruit.`],
      ['Keep it relaxed', `Autumn tables are best when they feel lived in. Set the table early, then enjoy your guests.`],
    ], `Start with a ${a('/collections/tablecloths', 'tablecloth')} and add ${a('/collections/napkins', 'napkins')} in a second shade.`),
    req: { id: 'r-autumn-req', mode: 'schedule', publishAtH: -72, note: 'Please schedule for Thursday morning.', requestedBy: 2, hoursAgo: 30, status: 'pending' } },
  { key: 'r-bedding', brand: 'ridhi', status: 'scheduled', version: 2, author: 2, createdD: 16, img: 3, tags: 'bedding, layering',
    title: 'How to Layer Block Print Bedding for Autumn', handle: 'layer-block-print-bedding-autumn', kw: 'block print bedding',
    metaTitle: 'Layer Block Print Bedding for Autumn Comfort', meta: 'Layer block print bedding for cosy autumn nights: start with cotton sheets, add a quilt and finish with cushions and a throw for texture.',
    summary: 'A simple layering order for cosy autumn bedding using block printed cotton.',
    body: short('As evenings cool, bedding can be layered rather than replaced. Cotton breathes, so it works across the season.', [
      ['Start with a smooth base', `A plain cotton sheet is the foundation. Choose a shade from the print you plan to use on top.`],
      ['Add a quilt and a throw', `A printed quilt brings pattern. A folded throw at the foot of the bed is easy to pull up on colder nights.`],
      ['Finish with cushions', `Two or three cushion covers complete the look and can be changed with the seasons.`],
    ], `Browse ${a('/collections/bedding', 'bedding')} for covers and quilts.`),
    req: { id: 'r-bedding-req', mode: 'schedule', publishAtH: -50, note: 'Scheduled for Wednesday.', requestedBy: 2, hoursAgo: 60, status: 'executed', decidedBy: 3, decidedHoursAgo: 58, decisionNote: 'Looks good.' }, publishAtH: -50 },
  { key: 'r-review1', brand: 'ridhi', status: 'in_review', version: 2, author: 2, createdD: 6, img: 1, tags: 'tablecloth, gifting',
    title: 'The Best Cotton Tablecloths for Everyday Use', handle: 'best-cotton-tablecloths-everyday-use', kw: 'cotton tablecloth',
    metaTitle: 'Best Cotton Tablecloths for Everyday Use', meta: 'What to look for in a cotton tablecloth for daily meals: weave, weight, print and washing. A practical buying guide for busy households.',
    summary: 'What to look for in a cotton tablecloth you will use every day.',
    body: short('An everyday tablecloth has to be easy to live with. Cotton is a natural choice because it is breathable, washable and gets softer with use.', [
      ['Weave and weight', `A medium-weight, closely woven cotton drapes well and resists wrinkling at the table edge.`],
      ['Print and colour', `Smaller, repeating prints hide the occasional crumb. Mid-tone colours are the most forgiving.`],
      ['Care', `Choose a cloth you are happy to machine wash. The easier it is to care for, the more often it will be used.`],
    ], `See our ${a('/collections/tablecloths', 'tablecloths')}.`),
    notes: [['submitted', 2, 26, 'Ready for a first review, internal links still to add.', 2]] },
  { key: 'r-review2', brand: 'ridhi', status: 'in_review', version: 3, author: 2, createdD: 7, img: 5, tags: 'bedding, gifting',
    title: 'Gifting Handmade Bedding: A Thoughtful Guide for New Homes', handle: 'gifting-handmade-bedding-new-homes', kw: 'handmade bedding gift',
    metaTitle: 'Gifting Handmade Bedding for a New Home', meta: 'Handmade cotton bedding is a warm housewarming gift. Learn how to choose size, colour and care details that make the present feel personal.',
    summary: 'How to choose handmade cotton bedding as a housewarming or wedding gift.',
    body: short('A set of hand block printed bedding is a gift that is used every night. Choosing well comes down to size, colour and a little knowledge of the recipient.', [
      ['Check the size', `Bed sizes vary by country. Ask the couple, or choose a throw and cushion covers that suit any size.`],
      ['Choose a calm colour', `Natural, indigo and soft red prints are easy to live with. If unsure, a plain cotton sheet set with a printed quilt is safe.`],
      ['Add care notes', `A short card explaining cool washing and shade drying shows thought and helps the gift last.`],
    ], `Explore ${a('/collections/bedding', 'handmade bedding')}.`),
    notes: [['submitted', 2, 40, 'Second draft after edits.', 2], ['changes_requested', 3, 38, 'Please add a line about sizes by country.', 2], ['submitted', 2, 14, 'Added the sizes section.', 3]] },
  { key: 'r-changes', brand: 'ridhi', status: 'changes_requested', version: 2, author: 2, createdD: 10, img: 4, tags: 'napkins, seasonal',
    title: 'Winter Table Linen Ideas for a Cosy Dinner', handle: 'winter-table-linen-ideas-cosy-dinner', kw: 'winter table linen',
    metaTitle: 'Winter Table Linen Ideas for a Cosy Dinner', meta: 'Deep colours, layered cotton and candlelight make a winter dinner feel warm. Easy table linen ideas that suit small and large gatherings.',
    summary: 'Warm and simple winter table linen ideas.',
    body: short('Winter dinners are about warmth. Table linen is a quick way to bring it in.', [
      ['Deep colours', `Indigo and deep red cottons look rich by candlelight.`],
      ['Layers', `Add a runner and a napkin in a second shade.`],
    ], `More ideas are in our ${a('/collections/tablecloths', 'tablecloth range')}.`),
    reviewNote: 'The intro makes a general claim about candlelight that needs a source or a softer wording. Please also add a second internal link.',
    notes: [['submitted', 2, 80, 'First full draft.', 1], ['changes_requested', 3, 70, 'The intro makes a general claim about candlelight that needs a source or a softer wording. Please also add a second internal link.', 1]] },
  { key: 'r-draft1', brand: 'ridhi', status: 'draft', version: 2, author: 2, createdD: 4, img: 6, tags: 'care, napkins',
    title: 'How to Iron Cotton Napkins Quickly', handle: 'how-to-iron-cotton-napkins-quickly', kw: 'how to iron cotton napkins',
    metaTitle: '', meta: '', summary: '',
    body: short('Ironing cloth napkins does not have to be a chore. A few small habits make it quick.', [
      ['Iron while damp', `Damp cotton smooths in seconds. Take napkins from the line when slightly damp and press on the reverse.`],
    ], `Draft in progress: add tips on folds and storage.`) },
  { key: 'r-draft2', brand: 'ridhi', status: 'draft', version: 1, author: 1, createdD: 3, img: 3, tags: 'hosting',
    title: 'Casual Lunch Table Ideas with Block Print Placemats', handle: 'casual-lunch-table-ideas-placemats', kw: 'block print placemats',
    metaTitle: '', meta: 'Easy lunch table ideas using block print placemats.', summary: '', origin: 'claude',
    body: short('A relaxed lunch needs very little: good bread, good company and a table that feels welcoming.', [
      ['Placemats instead of a cloth', `Placemats protect the table and let the wood show. Choose a bold print and keep the plates plain.`],
    ], `This first draft was produced by the demo AI step and needs a human edit.`) },
  { key: 'r-idea', brand: 'ridhi', status: 'idea', version: 1, author: 2, createdD: 2, img: 1, tags: '',
    title: 'Natural Dyes on Cotton Home Textiles: What to Know', handle: 'natural-dyes-cotton-home-textiles', kw: 'natural dye cotton textiles', metaTitle: '', meta: '', summary: '', body: '' },
  { key: 'r-hidden', brand: 'ridhi', status: 'draft', version: 1, author: 2, createdD: 34, img: 2, tags: 'imported',
    title: 'Seasonal Tablecloth Swap: A Quick Guide', handle: 'seasonal-tablecloth-swap-guide', kw: 'seasonal tablecloth', origin: 'shopify_admin', shopifyHidden: true,
    metaTitle: '', meta: 'Swap your tablecloth with the seasons.', summary: '',
    body: short('Changing your tablecloth with the seasons is the easiest refresh a home can have.', [['Why swap', `Colour and weight change from season to season, and so does the mood of the room.`]], `Imported sample article that exists as a hidden entry in the demo store listing.`) },

  // ------------------------------- Cotton Print Club -------------------------------
  { key: 'c-holiday', brand: 'cpc', status: 'published', version: 3, author: 2, createdD: 60, publishedD: 41, img: 2, tags: 'holiday, tablescape, hosting',
    title: 'How to Set a Holiday Table with Block Print Cotton', handle: 'set-holiday-table-block-print-cotton', kw: 'holiday table setting',
    metaTitle: 'Holiday Table Setting with Block Print Cotton', meta: 'A calm, step by step guide to a holiday table setting with block printed cotton: cloth, layers, light and a simple timeline for the week.',
    summary: 'A calm approach to a holiday table with block printed cotton, layers and candlelight.', body: HOLIDAY_BODY, traffic: 1.4, trend: 0.006 },
  { key: 'c-placemats', brand: 'cpc', status: 'published', version: 2, author: 2, createdD: 45, publishedD: 30, img: 5, tags: 'placemats, everyday',
    title: 'Cotton Placemats vs Tablecloths: Which Should You Choose?', handle: 'cotton-placemats-vs-tablecloths', kw: 'placemats vs tablecloth',
    metaTitle: 'Cotton Placemats vs Tablecloths: How to Choose', meta: 'Placemats or a tablecloth? Compare cotton options for protection, style, washing and everyday ease, and learn when it works to use both together.',
    summary: 'When to use placemats, when to use a cloth and how to combine them.',
    body: short('Both placemats and tablecloths do a lovely job. The right choice depends on your table, your routine and the mood you want.', [
      ['Placemats', `They protect the table, wash easily and let a beautiful wooden surface show. They suit everyday meals.`],
      ['Tablecloths', `A cloth covers the whole table, hides wear and makes an occasion feel special.`],
      ['Using both', `A runner or cloth with placemats on top adds depth for gatherings.`],
    ], `Browse ${a('/collections/placemats', 'placemats')} or ${a('/collections/tablecloths', 'tablecloths')}.`), traffic: 0.9, trend: -0.01 },
  { key: 'c-gifts', brand: 'cpc', status: 'published', version: 1, author: 3, createdD: 28, publishedD: 18, img: 6, tags: 'gifting, hosting',
    title: 'Hostess Gift Ideas: Napkin Sets and Table Linens', handle: 'hostess-gift-ideas-napkin-sets', kw: 'hostess gift ideas',
    metaTitle: 'Hostess Gift Ideas: Napkin Sets and Linens', meta: 'Napkin sets, table runners and tea towels make thoughtful hostess gifts. See how to choose, wrap and personalise them for any gathering.',
    summary: 'Simple, useful textile gifts for hosts.',
    body: short('Arriving with a gift for the host is a lovely tradition. Textiles are practical, durable and easy to wrap.', [
      ['Napkin sets', `A set of four or six block printed napkins tied with ribbon suits almost any home.`],
      ['Runners and towels', `A table runner or a pair of tea towels feels personal without being expensive.`],
    ], `See ${a('/collections/napkins', 'napkin sets')} and ${a('/collections/gifts', 'gift ideas')}.`), traffic: 0.7, trend: 0.02 },
  { key: 'c-bundles', brand: 'cpc', status: 'publish_requested', version: 2, author: 2, createdD: 7, img: 1, tags: 'bundles, tablescape',
    title: 'Building a Table Linen Bundle: Cloth, Napkins and Runner', handle: 'table-linen-bundle-cloth-napkins-runner', kw: 'table linen set',
    metaTitle: 'Build a Table Linen Bundle That Matches', meta: 'Choose a cloth, napkins and runner that work together. A simple method for building a matching table linen set without overbuying.',
    summary: 'How to assemble a matching table linen bundle step by step.',
    body: short('A bundle works best when pieces share colour but not always pattern.', [
      ['Choose the cloth first', `It sets the palette and the scale of print.`],
      ['Add napkins and a runner', `Pick two shades from the cloth and repeat them.`],
    ], `Explore ${a('/collections/bundles', 'bundles')}.`),
    req: { id: 'c-bundles-req', mode: 'schedule', publishAtH: -96, note: 'Schedule for the weekend before the hosting season.', requestedBy: 2, hoursAgo: 16, status: 'pending' } },
  { key: 'c-failed', brand: 'cpc', status: 'failed', version: 2, author: 2, createdD: 14, img: 3, tags: 'tablescape, formal',
    title: 'Formal Table Setting Basics with Cotton Linen', handle: 'formal-table-setting-basics-cotton-linen', kw: 'formal table setting',
    metaTitle: 'Formal Table Setting Basics with Cotton Linen', meta: 'Place settings, cutlery order and linen etiquette made simple. Learn the basics of a formal table setting using elegant cotton linen.',
    summary: 'The basics of a formal setting, from cloth to cutlery.',
    body: short('A formal table follows a few simple rules. Once learned, they make any dinner feel considered.', [
      ['Cloth and napkins', `Choose a cloth with a gentle drop and fold the napkin to sit left of the forks or on the plate.`],
      ['Cutlery order', `Place cutlery in the order it will be used, working from the outside in.`],
    ], `More in our ${a('/collections/tablecloths', 'tablecloths')}.`),
    lastError: 'Demo error: the simulated Shopify step reported "Blog not found for handle journal". Nothing was sent anywhere.',
    req: { id: 'c-failed-req', mode: 'publish_now', note: 'Needed for the autumn newsletter.', requestedBy: 2, hoursAgo: 26, status: 'failed', decidedBy: 3, decidedHoursAgo: 25, attempts: 1,
      error: 'Demo error: the simulated Shopify step reported "Blog not found for handle journal". Nothing was sent anywhere.' } },
  { key: 'c-review1', brand: 'cpc', status: 'in_review', version: 2, author: 2, createdD: 5, img: 4, tags: 'thanksgiving, tablescape',
    title: 'A Thanksgiving Tablescape with Block Printed Cotton', handle: 'thanksgiving-tablescape-block-printed-cotton', kw: 'thanksgiving tablescape',
    metaTitle: 'Thanksgiving Tablescape with Block Printed Cotton', meta: 'Create a warm Thanksgiving tablescape with a printed cotton cloth, simple layers and seasonal touches that suit both small and large tables.',
    summary: 'A warm Thanksgiving tablescape in a few simple steps.',
    body: short('A Thanksgiving table works best when it feels abundant but not crowded.', [
      ['Start with the cloth', `A rust or ochre print sets a warm tone for the whole table.`],
      ['Add natural touches', `Small gourds, candles and a few stems of greenery are enough.`],
    ], `Browse ${a('/collections/tablecloths', 'tablecloths')}.`),
    notes: [['submitted', 2, 12, 'Please check the timeline section.', 2]] },
  { key: 'c-review2', brand: 'cpc', status: 'in_review', version: 1, author: 2, createdD: 3, img: 6, tags: 'napkins, hosting',
    title: 'Napkin Folding Ideas for Holiday Dinners', handle: 'napkin-folding-ideas-holiday-dinners', kw: 'napkin folding ideas',
    metaTitle: 'Napkin Folding Ideas for Holiday Dinners', meta: 'Five simple napkin folds for holiday dinners, from a relaxed knot to a classic pocket fold, all suited to block printed cotton napkins.',
    summary: 'Five easy napkin folds for holiday tables.',
    body: short('A folded napkin finishes the place setting. These folds suit cotton best.', [
      ['The pocket fold', `Fold into thirds, then slide cutlery into the pocket.`],
      ['The relaxed knot', `Tie a loose knot at one corner for a casual look.`],
    ], `Our ${a('/collections/napkins', 'napkins')} fold beautifully.`),
    notes: [['submitted', 2, 5, 'First version for review.', 1]] },
  { key: 'c-changes', brand: 'cpc', status: 'changes_requested', version: 2, author: 2, createdD: 11, img: 2, tags: 'seasonal',
    title: 'Spring Table Ideas with Soft Cotton Prints', handle: 'spring-table-ideas-soft-cotton-prints', kw: 'spring table decor',
    metaTitle: 'Spring Table Ideas with Soft Cotton Prints', meta: 'Fresh flowers, pale cotton prints and light colours bring spring to the table. Easy ideas for brunches and family meals.',
    summary: 'Light, fresh spring table ideas with cotton prints.',
    body: short('Spring tables feel light. Soft prints and fresh flowers do most of the work.', [['Soft colours', `Pale green, blush and cream feel fresh next to white dishes.`]], `More in ${a('/collections/tablecloths', 'tablecloths')}.`),
    reviewNote: 'Add a short section on flowers and trim the introduction. Also confirm the product names mentioned.',
    notes: [['submitted', 2, 100, 'Ready for review.', 1], ['changes_requested', 3, 90, 'Add a short section on flowers and trim the introduction. Also confirm the product names mentioned.', 1]] },
  { key: 'c-draft', brand: 'cpc', status: 'draft', version: 1, author: 2, createdD: 2, img: 5, tags: 'gifting',
    title: 'Wedding Gift Ideas in Handmade Cotton', handle: 'wedding-gift-ideas-handmade-cotton', kw: 'wedding gift table linen', metaTitle: '', meta: '', summary: '',
    body: short('A wedding gift that is used daily is remembered. Table linen fits that description.', [['Pairs and sets', `A matching cloth and napkins make a complete present.`]], `Draft in progress.`) },
  { key: 'c-idea', brand: 'cpc', status: 'idea', version: 1, author: 2, createdD: 1, img: 1, tags: '',
    title: 'Small Table Tablescapes for Apartments', handle: 'small-table-tablescapes-apartments', kw: 'small table decor', metaTitle: '', meta: '', summary: '', body: '' },
  { key: 'c-shopsched', brand: 'cpc', status: 'draft', version: 1, author: 2, createdD: 20, img: 4, tags: 'imported',
    title: 'Candle and Cotton: A Winter Dinner Mood', handle: 'candle-and-cotton-winter-dinner-mood', kw: 'winter dinner table', origin: 'shopify_admin', shopifyScheduledH: -120,
    metaTitle: '', meta: 'Candlelight and cotton for winter dinners.', summary: '',
    body: short('Candlelight and soft cotton create a winter mood at the table.', [['Light', `Use candles in a mix of heights.`]], `Imported sample entry that shows as scheduled in the demo store listing.`) },
];

/* ---------------- Topics ---------------- */
// [brand, title, keyword, secondary, intent, volume|null, kd|null, status, source, articleKey|null, note, rationale, validation]
export const TOPIC_SPECS = [
  ['ridhi', 'Block print tablecloth care guide', 'block print tablecloth care', 'wash block print cloth, care for cotton tablecloth', 'informational', 880, 21, 'published', 'manual', 'r-care', 'Evergreen care content.', '', 'Volume imported from the sample keyword file.'],
  ['ridhi', 'Tablecloth size guide', 'tablecloth size guide', 'tablecloth drop, round tablecloth size', 'informational', 2400, 34, 'published', 'claude', 'r-size', '', 'Frequent pre-purchase question with clear intent.', 'Volume and difficulty checked against the sample keyword file.'],
  ['ridhi', 'Napkin styling for relaxed tables', 'block print napkins', 'cloth napkins, napkin folds', 'commercial', 1300, 28, 'published', 'claude', 'r-napkins', '', 'Supports the napkin collection.', 'Checked.'],
  ['ridhi', 'Table runners for everyday and hosting', 'block print table runner', 'table runner length, cotton runner', 'commercial', 590, 24, 'in_production', 'claude', 'r-runner', '', 'Product-led topic that links to runners.', 'Checked.'],
  ['ridhi', 'Cushion covers pattern mixing', 'block print cushion covers', 'mixing patterns, cushion styling', 'informational', 720, 26, 'in_production', 'manual', 'r-cushion', '', '', 'Checked.'],
  ['ridhi', 'Natural dyes on cotton textiles', 'natural dye cotton textiles', 'plant dye, indigo cotton', 'informational', null, null, 'proposed', 'claude', 'r-idea', '', 'Craft story that supports brand trust.', 'No volume data yet: import keyword data to validate.'],
  ['ridhi', 'Autumn hosting with cotton linen', 'autumn table setting ideas', 'fall table decor, autumn hosting', 'informational', 1900, 31, 'approved', 'claude', null, 'Seasonal, plan for early October.', 'Seasonal demand and a good fit for the napkin and cloth ranges.', 'Checked.'],
  ['ridhi', 'Sustainable cotton bedding care', 'cotton bedding care', 'wash cotton quilt, bedding care tips', 'informational', 480, 19, 'validated', 'claude', null, '', 'Low difficulty and links to the bedding range.', 'Volume and difficulty present. Ready for a decision.'],
  ['ridhi', 'Best placemats for round tables', 'placemats for round table', 'round table placemat size', 'commercial', 260, 17, 'validated', 'claude', null, '', 'Long-tail commercial intent.', 'Volume present. Ready for a decision.'],
  ['ridhi', 'Is hand block printed fabric colourfast?', 'block print fabric colourfast', 'dye bleeding, first wash', 'informational', null, null, 'proposed', 'claude', null, '', 'Answers a common first-wash question.', 'No volume data yet.'],
  ['ridhi', 'Wholesale buyers guide to home textiles', 'wholesale home textiles', 'bulk table linen', 'transactional', 140, 48, 'rejected', 'manual', null, 'Out of scope for the consumer blog.', '', 'Rejected by Rohan Mehta: not a consumer topic.'],
  ['cpc', 'Holiday table setting step by step', 'holiday table setting', 'christmas table decor, holiday tablescape', 'informational', 3600, 38, 'published', 'claude', 'c-holiday', '', 'Peak seasonal interest.', 'Checked.'],
  ['cpc', 'Placemats vs tablecloths', 'placemats vs tablecloth', 'tablecloth or placemats', 'informational', 390, 18, 'published', 'claude', 'c-placemats', '', '', 'Checked.'],
  ['cpc', 'Hostess gifts in cotton', 'hostess gift ideas', 'host gift, napkin set gift', 'commercial', 2900, 44, 'published', 'manual', 'c-gifts', '', '', 'Checked.'],
  ['cpc', 'Thanksgiving tablescape', 'thanksgiving tablescape', 'thanksgiving table decor', 'informational', 5400, 41, 'in_production', 'claude', 'c-review1', '', 'High seasonal demand in the US.', 'Checked.'],
  ['cpc', 'Napkin folding ideas', 'napkin folding ideas', 'how to fold napkins, holiday napkin folds', 'informational', 4400, 36, 'approved', 'claude', null, 'Approved for the holiday calendar.', 'Evergreen with seasonal peaks.', 'Checked.'],
  ['cpc', 'Gift guide: housewarming textiles', 'housewarming gift table linen', 'new home gift ideas', 'commercial', 320, 29, 'validated', 'claude', null, '', 'Supports gifting season.', 'Ready for a decision.'],
  ['cpc', 'Christmas tablecloth ideas', 'christmas tablecloth ideas', 'red tablecloth, holiday linen', 'commercial', 2100, 33, 'proposed', 'claude', null, '', 'Seasonal product-led topic.', 'Awaiting validation.'],
  ['cpc', 'Eco claims for cotton linens', 'eco friendly table linen', 'sustainable napkins', 'informational', null, null, 'rejected', 'claude', null, 'Cannot support the claim with verified information.', 'Avoids unverified claims.', 'Rejected: claims cannot be verified.'],
];

/* ---------------- Keywords ---------------- */
// [brand, keyword, volume, kd, intent, daysOld]
export const KEYWORD_SPECS = [
  ['ridhi', 'block print tablecloth', 2900, 41, 'commercial', 20], ['ridhi', 'block print tablecloth care', 880, 21, 'informational', 20], ['ridhi', 'tablecloth size guide', 2400, 34, 'informational', 20],
  ['ridhi', 'tablecloth size for 6 seater', 1600, 29, 'informational', 20], ['ridhi', 'round tablecloth size chart', 1300, 27, 'informational', 20], ['ridhi', 'block print napkins', 1300, 28, 'commercial', 20],
  ['ridhi', 'cotton napkins set', 3100, 46, 'commercial', 20], ['ridhi', 'cloth napkin folding', 2200, 33, 'informational', 20], ['ridhi', 'block print table runner', 590, 24, 'commercial', 20],
  ['ridhi', 'cotton table runner', 1500, 37, 'commercial', 20], ['ridhi', 'block print cushion covers', 720, 26, 'commercial', 45], ['ridhi', 'how to mix cushion patterns', 540, 22, 'informational', 45],
  ['ridhi', 'block print bedding', 1100, 32, 'commercial', 45], ['ridhi', 'cotton bedding care', 480, 19, 'informational', 45], ['ridhi', 'hand block printing process', 1700, 30, 'informational', 45],
  ['ridhi', 'what is block printing', 4800, 35, 'informational', 45], ['ridhi', 'natural dye cotton textiles', 210, 23, 'informational', 90], ['ridhi', 'autumn table setting ideas', 1900, 31, 'informational', 20],
  ['ridhi', 'winter table linen', 320, 20, 'informational', 90], ['ridhi', 'placemats for round table', 260, 17, 'commercial', 90], ['ridhi', 'block print placemats', 480, 25, 'commercial', 90],
  ['ridhi', 'indigo block print fabric', 1000, 34, 'commercial', 200], ['ridhi', 'how to iron cotton napkins', 170, 14, 'informational', 200], ['ridhi', 'seasonal tablecloth', 390, 26, 'commercial', 200],
  ['cpc', 'holiday table setting', 3600, 38, 'informational', 15], ['cpc', 'christmas table decor ideas', 6600, 47, 'informational', 15], ['cpc', 'thanksgiving tablescape', 5400, 41, 'informational', 15],
  ['cpc', 'hostess gift ideas', 2900, 44, 'commercial', 15], ['cpc', 'placemats vs tablecloth', 390, 18, 'informational', 15], ['cpc', 'napkin folding ideas', 4400, 36, 'informational', 15],
  ['cpc', 'formal table setting', 3300, 39, 'informational', 40], ['cpc', 'christmas tablecloth ideas', 2100, 33, 'commercial', 40], ['cpc', 'table linen set', 1200, 36, 'commercial', 40],
  ['cpc', 'spring table decor', 2700, 35, 'informational', 40], ['cpc', 'housewarming gift table linen', 320, 29, 'commercial', 40], ['cpc', 'wedding gift table linen', 260, 27, 'commercial', 75],
  ['cpc', 'small table decor', 1900, 32, 'informational', 75], ['cpc', 'winter dinner table', 880, 28, 'informational', 75], ['cpc', 'cotton placemats set of 4', 1400, 40, 'commercial', 75],
  ['cpc', 'block print tablecloth rectangular', 720, 31, 'commercial', 210], ['cpc', 'easter table setting', 3000, 37, 'informational', 210], ['cpc', 'tea towel gift set', 590, 25, 'commercial', 210],
];

/* ---------------- Products (for the internal-link picker) ---------------- */
const RIDHI_PRODUCTS = ['Indigo Vine Block Print Tablecloth', 'Madder Red Block Print Tablecloth', 'Ochre Lotus Block Print Tablecloth', 'Sage Fern Block Print Napkins, Set of 4', 'Indigo Vine Napkins, Set of 6', 'Marigold Table Runner',
  'Block Print Cushion Cover, Indigo Leaf', 'Block Print Cushion Cover, Rust Bloom', 'Rose Garden Quilt, Queen', 'Cotton Duvet Cover, Indigo Dot', 'Rust Check Placemats, Set of 4', 'Hand Block Print Tea Towel', 'Charcoal Paisley Tablecloth, Round',
  'Sage Diamond Table Runner', 'Block Print Pillow Sham Pair', 'Blossom Cotton Throw'];
const CPC_PRODUCTS = ['Berry Holiday Tablecloth', 'Evergreen Napkin Set of 6', 'Ivory Garland Table Runner', 'Gold Trim Placemats, Set of 4', 'Cranberry Block Print Napkins', 'Winter Berry Cushion Cover', 'Harvest Rust Tablecloth', 'Snowdrop Tea Towel Pair',
  'Hostess Gift Bundle: Cloth and Napkins', 'Forest Leaf Placemat Set', 'Cotton Print Round Tablecloth', 'Spring Blossom Table Runner'];
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
export const productsFor = (brand) => (brand === 'ridhi' ? RIDHI_PRODUCTS : brand === 'cpc' ? CPC_PRODUCTS : null)?.map((title, i) => ({
  handle: slug(title), title, url: `https://${brand}.demo.invalid/products/${slug(title)}`, image_url: `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/demo/tile-${(i % 6) + 1}.svg`,
}));

/* ---------------- Query terms for analytics ---------------- */
export const QUERY_MODIFIERS = ['', ' guide', ' ideas', ' how to', ' best', ' tips'];
