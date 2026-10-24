# Docs learning materials

Keep the existing dark, bilingual website. Each method explains its actual platform implementation, a specific failure it addresses, intermediate artifacts, stopping rules and a worked example. Library pages explain mathematical domains, native models, executable examples and result interpretation.

## Diagram and demonstration sequence

| Material | Opening | Reader action | Visible change | Ending and check |
|---|---|---|---|---|
| Method walkthrough | Complete Mermaid graph and first step | Step, play, pause or choose a stage | Highlight the stage and show its input, decision and artifact | Stop at the final stage; every stage remains readable without JavaScript |
| Production geometry | Integer production plan, objective 13 | Change capacity, quantity domain or minimum demand | Feasible region, candidate points, best plan and resource use change together | Show the resource use and the constraints behind each result |
| Plan conversation | Saved original plan | Query, revise, compare scenarios or select any saved plan | Fixed example messages, saved plans and current baseline update | Browsing a result and selecting a baseline remain distinct |
| Data editor | Saved resource table and original plan | Edit, cancel, save a capacity, then start modeling | Save applies data edits; Start modeling computes a new result | Original result keeps its original input |
| Convex geometry | Target and a resource limit | Change the limit | The nearest feasible point and objective move together | Show the allocation, resource use and distance to the target |
| Local optimization | A nonconvex objective curve | Choose a starting point and play iterations | Gradient descent moves to one of two local minima | Identify the teaching algorithm explicitly; do not present it as an Ipopt recording |

Animations explain changes; method walkthroughs and iterations start on request. Playback pauses when the page becomes hidden. Reduced-motion users receive immediate updates. Controls have keyboard labels and fixed-example disclosures. Recorded product screenshots retain their original language and theme. All numeric teaching results are computed from the displayed model, rather than scripted LLM claims.

Mermaid is rendered to SVG during the build. The published site has no Mermaid runtime or CDN dependency. Graphs can be expanded or downloaded. Formulae use the already installed KaTeX build dependency.
