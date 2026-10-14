# Bundled libraries

Served locally so replies render offline (for example with Ollama). Each library's licence is next to it.

| File | Library | Version | Licence | Loaded |
|---|---|---|---|---|
| `purify.min.js` | DOMPurify | 3.4.16 | MPL-2.0 or Apache-2.0 | with the page |
| `katex/` | KaTeX (woff2 fonts only) | 0.18.9 | MIT | with the page |
| `highlight.min.js` | highlight.js common bundle, plus haskell, scala, x86asm, ocaml, matlab, prolog, verilog, vhdl, lisp, scheme, elixir, erlang, dart, latex, dockerfile, powershell, fortran and julia | 11.12.0 (`@highlightjs/cdn-assets`) | BSD-3-Clause | with the page |
| `mermaid.min.js` | Mermaid | 11.17.2 | MIT | only when a diagram first appears |

To update one, take the file from the npm package's `dist` folder (`npm pack <name>@<version>`), then run the UI tests.
