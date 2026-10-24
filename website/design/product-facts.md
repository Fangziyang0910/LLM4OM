# Verified content

Source of truth: the current local checkout's README, GLOSSARY, user guide, method registry, and frontend implementation. This site describes that checkout; it does not claim a publicly released version number.

- The platform supports natural-language optimization modeling and actual solver execution.
- Two main entry points: optimization conversation and manual modeling workbench. An optional requirements conversation prepares an editable problem statement.
- 13 modeling methods and nine modeling libraries. Available engines and commercial licensing depend on deployment.
- Input attachments include CSV, TSV, JSON, text and XLSX. XLSX worksheets become CSV. Attachments can be inspected and edited.
- Saved runs retain models, code, steps and actual results. Revisions save separate plans; scenario comparisons use a fixed baseline.
- Multi-method/model comparison supports up to 12 runs. Conflict explanations need solver-provided evidence; Gurobi IIS and CPMpy MUS are the documented paths.
- Exports include full-variable Excel plans, CSV variables and Markdown reports.
- The documented integer production example is max 3A + 2B, subject to 2A + B <= 8 and A + 2B <= 8, with A,B nonnegative integers. Its optimum is A=3, B=2, value 13. The website's interactive example enumerates this small problem in the browser; it does not call an LLM or represent a live platform session.
- With cutting capacity 10, production becomes A=4, B=2, value 16. Requiring B>=5 is infeasible because processing capacity remains 8.
- The staffing illustration assigns four people over two days, exactly two people each day and one day per person. Monday/Tuesday costs are [[1,7],[2,8],[7,1],[8,2]]. Minimum cost is 6; forcing person 0 to Tuesday makes it 18.
- The delivery illustration matches three warehouses to three stores, one-to-one. Costs are [[4,8,6],[7,3,9],[5,6,2]]. Minimum cost is 9; closing warehouse B to store 2 makes it 17.
- The six workbench images are fresh bilingual dark captures from the actual application. A scripted LLM adapter provides fixed modeling responses while the real Pyomo/HiGHS solver produces objectives 13, 12 and 8. They demonstrate interface behavior and solver results, not the reliability or performance of a live LLM.
- Method/library counts remain internal reference facts and are not displayed in public page copy.
- User-supplied attribution: EIPI team. Interface copy must be available in both Chinese and English.

GitHub Pages is a static HTML/CSS/JS host. Verified against GitHub's official documentation:

- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages

The repository was initially private, which explained the unauthenticated 404. The user subsequently explicitly authorized making Fangziyang0910/LLM4OM public and deploying this site. Publish static contents on a separate gh-pages branch without pushing unrelated local platform commits. Verify public visibility, the Pages build and unauthenticated links after publication.

Publication verified on 2026-10-24: repository visibility is public; Pages source is gh-pages at root with HTTPS enforced; deployment 40060506135 succeeded for commit 1f18620b2286688d079c864a57e945f017c8872d. Live browser checks passed in both locales and six viewport sizes, plus normal-motion playback at 320px. Deployed HTML, CSS and JavaScript match local sources. Project, guide, deployment and license links return 200 without authentication.
