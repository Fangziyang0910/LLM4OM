# Brand assets

- Product: LLM4OM, Large Language Models for Optimization Modeling.
- Team attribution: EIPI team, supplied by the user. Team website: https://scut-eipi.github.io/.
- Product mark: the workbench logo (`frontend/src/components/Logo.tsx`): a rounded square with a brand-to-accent gradient, a white polygon and a dot. The site and Docs inline the same SVG; keep its path.
- Colors follow the workbench: brand `#314eee` (dark `#6b91ff`), accent `#8c5cf6` (dark `#a68bfa`), zinc surfaces. Green identifies an actual feasible result.
- Typeface: Inter, already used and licensed by the workbench; system CJK fonts for Chinese. Self-host the existing Inter font and its OFL notice.
- Product screenshots: full-window captures (1440×900, 2×) of the actual workbench with real model runs (DeepSeek) and Docker solving, in Chinese and English, light and dark. Each landing feature section shows one screenshot that follows the page language and theme. Screenshot contents are not recolored or fabricated; when a real run shows an error step, choose the viewport, never edit the record. The Docs recording is made by `website/capture.cjs` with scripted model replies and a real solver, and says so.
- The first interactive workspace is a purpose-built illustration with three finite, computed examples. It is labeled as an example and stays visually distinct from the real workbench gallery.
- Team mark: existing `images/logo-dark.svg` from the adjacent EIPI team website.
- GitHub mark: official favicon from https://github.githubassets.com/favicons/favicon.svg.
- Do not add testimonials, customer logos, speed claims, success rates, or a hosted platform address without evidence.
- Do not show benchmark tables or solve rates on the landing page unless they come from a recorded, reproducible run with its setup stated next to the numbers.
- The workbench has no built-in login; deployment copy says so.
