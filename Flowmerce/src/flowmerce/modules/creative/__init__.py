"""Creative Strategist: turns ad performance into insights, concepts, briefs and tests.

The loop from docs/product/Flowmerce_Project_Handoff.md section 3.4, in four stored shapes:
research and insight become an insight, the idea becomes a concept, the work order becomes a brief,
and the test carries one hypothesis, one variable and the learning it produced.

Flowmerce suggests; the team decides. Nothing here publishes an ad, changes a budget or makes an
image or a video, and every AI suggestion keeps the figures it came from so it can be checked.

Layout:
    config.py   settings and the Supabase client for schema `creative`
    insights.py reads ads.* and works out what performed
    service.py  the answers the /creative page asks for, demo figures included
    api.py      the /api/creative routes
"""
